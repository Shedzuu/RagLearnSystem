## Current project state (backend + frontend)

### Backend

- **Stack**: Django 4.2, DRF, PostgreSQL (Dockerized), JWT auth (simplejwt).
- **Apps**:
  - `users`: кастомный `User` (email as login), регистрация/логин, `GET /api/auth/me/`.
  - `learning`: вся логика курсов, материалов, попыток, ответов и AI.

#### Main models in `learning`

- **`Plan`**
  - `owner` → `users.User`
  - `title`, `description`
  - `goals` — свободный текст “чему хочу научиться”
  - `generation_status` — `pending / processing / ready / failed`
  - `is_public`, `created_at`, `updated_at`

- **`Document`**
  - `owner` → `users.User`
  - `plan` → `Plan` (nullable; материал может быть просто в библиотеке)
  - `file_path`, `original_name`, `file_size`, `uploaded_at`

- **Структура курса**
  - `Section` (→ `Plan`): `title`, `order`, `generation_status`
  - `Unit` (→ `Section`): `title`, `order`, `theory`, `generation_status`
  - `Question` (→ `Unit`): `text`, `type (single_choice/multiple_choice/open_text/code)`, `difficulty`, `order`, `points`
  - `Choice` (→ `Question`): `text`, `is_correct`, `order`

- **Прохождение**
  - `Enrollment` (user ↔ plan), `Attempt`, `Answer`, `AnswerChoice`
  - Прогресс и статистика: `UnitProgress`, `SectionProgress`, `QuestionStats`, `CourseFeedback`

- **AI chat**
  - `AiChatMessage` (user + optional plan/section/unit/question + role + content)

#### Learning API (главное)

- **Auth**: `/api/auth/*` (из `users`).
- **Plans**:
  - `GET /api/plans/` — список планов пользователя.
  - `POST /api/plans/` — создать план (`title`, `description`, `goals`).
  - `GET /api/plans/{id}/` — детали плана + разделы/юниты.
- **Units**:
  - `GET /api/units/{id}/` — юнит с теорией и вопросами.
- **Materials**:
  - `GET /api/documents/` — библиотека материалов пользователя.
  - `POST /api/documents/upload/` — загрузить материал без плана (`owner=user`, `plan=NULL`).
  - `POST /api/plans/{id}/attach-documents/` — привязать список `document_ids` к плану.
  - `POST /api/plans/{id}/documents/` — загрузить файл сразу в план (сейчас используется редко, т.к. основной поток идёт через библиотеку).
- **Прохождение**:
  - `POST /api/attempts/start/` — начать попытку по плану.
  - `POST /api/answers/submit/` — сохранить ответ на вопрос, посчитать `is_correct`/`earned_points` для тестов.
- **LLM‑генерация курса**:
  - `POST /api/plans/{id}/generate/` — сгенерировать разделы/юниты/вопросы на основе:
    - текстов всех `Document` плана,
    - поля `goals` в `Plan`.

#### LLM‑генерация (что уже есть)

- Файл `learning/services_generation.py`:
  - `LLMClient`:
    - читает `LLM_API_KEY` и `LLM_MODEL` из env;
    - использует OpenAI‑совместимый API (через `openai.OpenAI`) для `chat.completions` с `response_format={"type": "json_object"}`.
  - `_load_document_text(doc)`:
    - `txt/md` читается напрямую;
    - `pdf` через `PyPDF2`;
    - `docx` через `python-docx`;
    - fallback — попытка прочитать как текст.
  - `_build_materials_context(plan)`:
    - собирает куски вида `[filename]\n<snippet>` для всех документов плана;
    - каждый текст режется до ~4000 символов, затем всё склеивается.
  - `_normalize_goals_with_llm(plan, llm)`:
    - через LLM превращает свободный текст `goals` в список коротких тем `topics: [...]`.
  - `_generate_course_structure_with_llm(plan, context, topics, llm)`:
    - даёт модели:
      - title, description, topics,
      - склеенный текст материалов (`context`);
    - просит вернуть JSON (`sections → units → theory → questions → choices`), не придумывая факты вне материалов.
  - `generate_plan_from_documents(plan)`:
    - читает материалы → `context`,
    - нормализует `goals` → `topics`,
    - получает структуру курса из LLM,
    - очищает старые `Section/Unit/Question/Choice` плана,
    - создаёт новые, помечая `generation_status=READY`.

- Файл `learning/views_generation.py`:
  - `PlanGenerateView`:
    - `POST /api/plans/{plan_id}/generate/`
    - проверяет владельца и наличие документов;
    - ставит `generation_status=processing`,
    - вызывает `generate_plan_from_documents(plan)`,
    - при ошибке → `FAILED`, при успехе → `READY` и отдаёт детальный план.

**Важно:** сейчас LLM получает **сырое склеенное содержимое всех документов**, без семантического отбора через эмбеддинги/pgvector.

---

## План интеграции RAG с чанками и эмбеддингами

Цель: вместо “скармливать ЛЛМ всю книгу” делать:

1. Индексацию материалов в виде чанков с эмбеддингами.
2. Семантический поиск релевантных чанков по темам из `goals` (через pgvector).
3. Давать ЛЛМ только отобранный контекст, а не весь текст.

### Шаг 1. Модель `Chunk` с pgvector

**Задача:** хранить куски текста (чанки) материалов для каждого плана, с векторным представлением для поиска.

Добавляем в `learning/models.py` модель (примерная форма):

```python
from pgvector.django import VectorField

class Chunk(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="chunks")
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    content = models.TextField()
    page_number = models.IntegerField(null=True, blank=True)
    chunk_index = models.IntegerField()
    start_char = models.IntegerField(null=True, blank=True)
    end_char = models.IntegerField(null=True, blank=True)
    embedding = VectorField(dimensions=1024, null=True, blank=True)

    class Meta:
        indexes = [
            # ivfflat индекс создадим в миграции raw SQL
        ]
```

**Миграции:**

- Установить зависимости в backend‑образ:
  - `pgvector` (для Django),
  - `psycopg2-binary` (если ещё нет),
  - `sentence-transformers`, `PyPDF2`, `python-docx` (часть уже может быть).
- В Postgres:
  - `CREATE EXTENSION IF NOT EXISTS vector;`
  - добавить поле `embedding vector(1024)` в таблицу `learning_chunk`;
  - создать ivfflat‑индекс:

```sql
CREATE INDEX IF NOT EXISTS learning_chunk_embedding_ivfflat
ON learning_chunk
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

Это можно оформить как `RunSQL` в миграции Django.

Результат: у нас есть таблица `learning_chunk` с колонкой `embedding`, поддерживаемой pgvector.

---

### Шаг 2. Индексация документов плана (чанкинг + эмбеддинги)

**Задача:** после того как пользователь привязал материалы к плану, один раз проиндексировать текст в чанки и сохранить их в БД с эмбеддингами.

Добавляем сервис `EmbeddingService` (например, в `learning/services_rag.py`):

```python
from sentence_transformers import SentenceTransformer
import numpy as np

class EmbeddingService:
    def __init__(self) -> None:
        self.model = SentenceTransformer("intfloat/multilingual-e5-large")

    def embed_texts(self, texts, is_query: bool = False) -> np.ndarray:
        if is_query:
            texts = [f"query: {t}" for t in texts]
        else:
            texts = [f"passage: {t}" for t in texts]
        return self.model.encode(texts, convert_to_numpy=True)
```

**Функция индексации одного плана** (черновая логика):

```python
from .models import Chunk
from .services_generation import _load_document_text  # уже есть

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

def split_text_with_overlap(text: str, page_number: int | None = None) -> list[dict]:
    chunks = []
    start = 0
    idx = 0
    n = len(text)
    while start < n:
        end = min(start + CHUNK_SIZE, n)
        # попытка обрезать по границе предложения во второй половине чанка
        slice_text = text[start:end]
        cut = slice_text.rfind(". ")
        if cut > CHUNK_SIZE // 2:
            end = start + cut + 1
            slice_text = text[start:end]
        chunks.append(
            {
                "content": slice_text,
                "page_number": page_number,
                "chunk_index": idx,
                "start_char": start,
                "end_char": end,
            }
        )
        idx += 1
        start = end - CHUNK_OVERLAP
        if start < 0:
            start = 0
        if start >= n:
            break
    return chunks


def index_plan_documents(plan: Plan) -> None:
    embedder = EmbeddingService()

    # Удаляем старые чанки плана (если пересоздаём)
    Chunk.objects.filter(plan=plan).delete()

    all_chunks = []
    for doc in plan.documents.all():
        text = _load_document_text(doc)
        # если умеем определять страницы — можно передавать page_number, пока None
        for ch in split_text_with_overlap(text, page_number=None):
            all_chunks.append((doc, ch))

    if not all_chunks:
        return

    contents = [c["content"] for _, c in all_chunks]
    embeddings = embedder.embed_texts(contents, is_query=False)

    objs = []
    for (doc, ch), emb in zip(all_chunks, embeddings):
        objs.append(
            Chunk(
                plan=plan,
                document=doc,
                content=ch["content"],
                page_number=ch["page_number"],
                chunk_index=ch["chunk_index"],
                start_char=ch["start_char"],
                end_char=ch["end_char"],
                embedding=emb,  # pgvector.django умеет принимать list/ndarray
            )
        )
    Chunk.objects.bulk_create(objs, batch_size=100)
```

Это можно вызывать:
- либо сразу после `attach-documents`,
- либо внутри `generate_plan_from_documents`, до вызова RAG/LLM.

---

### Шаг 3. RAGService (поиск релевантных чанков) и связка с LLM

**Задача:** по каждой теме из `goals` вместо всего текста материалов брать только топ‑чанки по смыслу.

Пример `RAGService` (упрощённо, реальный синтаксис для pgvector‑order_by может отличаться в зависимости от версии библиотеки):

```python
from .models import Chunk

class RAGService:
    def __init__(self) -> None:
        self.embedder = EmbeddingService()

    def search_similar_chunks(self, plan: Plan, query: str, top_k: int = 20) -> list[Chunk]:
        q_vec = self.embedder.embed_texts([query], is_query=True)[0]
        # Вариант с pgvector.django:
        return (
            Chunk.objects
            .filter(plan=plan, embedding__isnull=False)
            .order_by(("embedding", q_vec, "cosine_distance"))[:top_k]
        )
```

*В реальном коде надо будет посмотреть документацию `pgvector.django` по синтаксису `order_by`; идея — передать `q_vec` и отсортировать по косинусному расстоянию.*

**Интеграция в генерацию плана:**

- Вместо `_build_materials_context(plan)`:
  - нормализуем `goals` → список `topics`;
  - для каждой темы:
    - берём `candidate_chunks = rag.search_similar_chunks(plan, topic, top_k=20)`;
    - (опционально) прогоняем кандидатов через LLM‑фильтр, который оценивает релевантность (0..1) и выбрасывает мусор;
    - собранные top‑чанки по темам склеиваем в `context` с указанием файла/страницы.
- `_generate_course_structure_with_llm` и остальной код остаются такими же, только на вход вместо “вся книга” получают аккуратный контекст из RAG.

В результате:

- эмбеддинги лежат **в pgvector‑поле `Chunk.embedding`** в Postgres;
- поиск релевантных кусков идёт через `embedding <=>` (косинусная дистанция);
- ЛЛМ видит только отфильтрованный контекст и цели, а не весь документ целиком.

Это и есть переход от “LLM по всей книге” к честному **RAG‑генератору курса**.

