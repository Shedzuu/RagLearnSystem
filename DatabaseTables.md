## Database tables

Если курс генерируется через RAG (загрузка документа → эмбеддинги → семантический поиск → генерация структуры и заданий), и тебе нужно:

- прогресс по каждой задаче
- прогресс по каждому модулю
- фидбек
- выявление слабых мест

то архитектура немного усложняется — но логично.

Ниже — чистая, нормализованная, production-ready схема.

---

### 1. Пользователи

#### `users_user`

Твоя кастомная модель пользователя (наследник `AbstractUser`).

---

### 2. План (курс)

#### `plans_plan`

```text
id               BIGSERIAL PRIMARY KEY
owner_id         BIGINT NOT NULL REFERENCES users_user(id) ON DELETE CASCADE

title            VARCHAR(255) NOT NULL
description      TEXT NULL

generation_status VARCHAR(30) NOT NULL DEFAULT 'pending'
# pending / processing / ready / failed

is_public        BOOLEAN NOT NULL DEFAULT FALSE

created_at       TIMESTAMP NOT NULL DEFAULT now()
updated_at       TIMESTAMP NOT NULL DEFAULT now()
```

- `generation_status` важен для RAG: пока курс генерируется, его нельзя проходить.

---

### 3. Исходный документ

#### `plans_document`

```text
id               BIGSERIAL PRIMARY KEY
plan_id          BIGINT NOT NULL REFERENCES plans_plan(id) ON DELETE CASCADE

file_path        VARCHAR(500) NOT NULL
original_name    VARCHAR(255) NOT NULL
file_size        INTEGER NOT NULL

uploaded_at      TIMESTAMP NOT NULL DEFAULT now()
```

---

### 4. Структура курса

#### 4.1 Раздел

#### `plans_section`

```text
id          BIGSERIAL PRIMARY KEY
plan_id     BIGINT NOT NULL REFERENCES plans_plan(id) ON DELETE CASCADE

title       VARCHAR(255) NOT NULL
order       INTEGER NOT NULL

generation_status VARCHAR(30) NOT NULL DEFAULT 'draft'
# draft / generating / ready / failed

UNIQUE(plan_id, order)
```

---

#### 4.2 Unit (урок)

Экран: теория + вопросы.

#### `plans_unit`

```text
id              BIGSERIAL PRIMARY KEY
section_id      BIGINT NOT NULL REFERENCES plans_section(id) ON DELETE CASCADE

title           VARCHAR(255) NOT NULL
order           INTEGER NOT NULL

theory          TEXT NOT NULL

generation_status VARCHAR(30) NOT NULL DEFAULT 'draft'
# draft / generating / ready / failed

UNIQUE(section_id, order)
```

> Привязка к векторному хранилищу (эмбеддинги) делается через метаданные
> в самой векторной базе: туда можно передавать `plan_id`, `section_id`, `unit_id`.
> В реляционной БД отдельное поле `embedding_id` не обязательно.

---

### 5. Вопросы

#### `plans_question`

```text
id          BIGSERIAL PRIMARY KEY
unit_id     BIGINT NOT NULL REFERENCES plans_unit(id) ON DELETE CASCADE

text        TEXT NOT NULL
type        VARCHAR(30) NOT NULL
# single_choice
# multiple_choice
# open_text
# code

difficulty  SMALLINT NOT NULL DEFAULT 1
# 1 easy, 2 medium, 3 hard

order       INTEGER NOT NULL
points      INTEGER NOT NULL DEFAULT 1

UNIQUE(unit_id, order)
```

---

### 6. Варианты ответов

#### `plans_choice`

```text
id              BIGSERIAL PRIMARY KEY
question_id     BIGINT NOT NULL REFERENCES plans_question(id) ON DELETE CASCADE

text            TEXT NOT NULL
is_correct      BOOLEAN NOT NULL DEFAULT FALSE
order           INTEGER NOT NULL

UNIQUE(question_id, order)
```

---

### 7. Прохождение курса

Этот блок отвечает за аналитику и прогресс.

#### 7.1 Enrollment (запись на курс)

Даже если сейчас пользователь сам себе создаёт курс, лучше сразу сделать правильно.

#### `learning_enrollment`

```text
id          BIGSERIAL PRIMARY KEY
user_id     BIGINT NOT NULL REFERENCES users_user(id) ON DELETE CASCADE
plan_id     BIGINT NOT NULL REFERENCES plans_plan(id) ON DELETE CASCADE

status      VARCHAR(30) NOT NULL DEFAULT 'active'
# active / completed / dropped

enrolled_at TIMESTAMP NOT NULL DEFAULT now()

UNIQUE(user_id, plan_id)
```

---

#### 7.2 Попытка

#### `learning_attempt`

```text
id              BIGSERIAL PRIMARY KEY
enrollment_id   BIGINT NOT NULL REFERENCES learning_enrollment(id) ON DELETE CASCADE

started_at      TIMESTAMP NOT NULL DEFAULT now()
completed_at    TIMESTAMP NULL

score_percent   NUMERIC(5,2) NULL
```

---

#### 7.3 Ответ на вопрос

#### `learning_answer`

```text
id              BIGSERIAL PRIMARY KEY
attempt_id      BIGINT NOT NULL REFERENCES learning_attempt(id) ON DELETE CASCADE
question_id     BIGINT NOT NULL REFERENCES plans_question(id) ON DELETE CASCADE

text_answer     TEXT NULL
code_answer     TEXT NULL

is_correct      BOOLEAN NULL
earned_points   INTEGER NULL

feedback_text   TEXT NULL
# объяснение LLM по конкретному ответу (что не так, что повторить)

answered_at     TIMESTAMP NOT NULL DEFAULT now()

UNIQUE(attempt_id, question_id)
```

---

#### 7.4 Выбранные варианты

#### `learning_answer_choice`

```text
id              BIGSERIAL PRIMARY KEY
answer_id       BIGINT NOT NULL REFERENCES learning_answer(id) ON DELETE CASCADE
choice_id       BIGINT NOT NULL REFERENCES plans_choice(id) ON DELETE CASCADE

UNIQUE(answer_id, choice_id)
```

---

### 8. Прогресс по Unit

Чтобы быстро показывать прогресс без пересчёта каждый раз.

#### `learning_unit_progress`

```text
id                  BIGSERIAL PRIMARY KEY
enrollment_id       BIGINT NOT NULL REFERENCES learning_enrollment(id) ON DELETE CASCADE
unit_id             BIGINT NOT NULL REFERENCES plans_unit(id) ON DELETE CASCADE

completion_percent  NUMERIC(5,2) NOT NULL DEFAULT 0
is_completed        BOOLEAN NOT NULL DEFAULT FALSE

last_updated        TIMESTAMP NOT NULL DEFAULT now()

UNIQUE(enrollment_id, unit_id)
```

---

### 9. Прогресс по Section

#### `learning_section_progress`

```text
id                  BIGSERIAL PRIMARY KEY
enrollment_id       BIGINT NOT NULL REFERENCES learning_enrollment(id) ON DELETE CASCADE
section_id          BIGINT NOT NULL REFERENCES plans_section(id) ON DELETE CASCADE

completion_percent  NUMERIC(5,2) NOT NULL DEFAULT 0
is_completed        BOOLEAN NOT NULL DEFAULT FALSE

UNIQUE(enrollment_id, section_id)
```

---

### 10. Аналитика слабых мест

#### `learning_question_stats`

```text
id              BIGSERIAL PRIMARY KEY
enrollment_id   BIGINT NOT NULL REFERENCES learning_enrollment(id) ON DELETE CASCADE
question_id     BIGINT NOT NULL REFERENCES plans_question(id) ON DELETE CASCADE

times_answered  INTEGER NOT NULL DEFAULT 0
times_correct   INTEGER NOT NULL DEFAULT 0
success_rate    NUMERIC(5,2) NOT NULL DEFAULT 0

last_attempt_at TIMESTAMP NULL

UNIQUE(enrollment_id, question_id)
```

---

### 11. Фидбек пользователя

#### `learning_feedback`

```text
id              BIGSERIAL PRIMARY KEY
enrollment_id   BIGINT NOT NULL REFERENCES learning_enrollment(id) ON DELETE CASCADE

rating          SMALLINT NOT NULL
comment         TEXT NULL

created_at      TIMESTAMP NOT NULL DEFAULT now()
```

---

### 12. Сообщения AI‑чата (опционально)

Если нужен чат‑репетитор, который отвечает в контексте курса/раздела/юнита/вопроса,
можно добавить таблицу истории сообщений.

#### `ai_chat_message`

```text
id              BIGSERIAL PRIMARY KEY
user_id         BIGINT NOT NULL REFERENCES users_user(id) ON DELETE CASCADE

plan_id         BIGINT NULL REFERENCES plans_plan(id) ON DELETE CASCADE
section_id      BIGINT NULL REFERENCES plans_section(id) ON DELETE CASCADE
unit_id         BIGINT NULL REFERENCES plans_unit(id) ON DELETE CASCADE
question_id     BIGINT NULL REFERENCES plans_question(id) ON DELETE CASCADE

role            VARCHAR(20) NOT NULL
# 'user' / 'assistant' / 'system'

content         TEXT NOT NULL

created_at      TIMESTAMP NOT NULL DEFAULT now()
```

Через `plan_id` / `unit_id` / `question_id` бэкенд понимает,
в каком контексте был задан вопрос, и поднимает нужную теорию/вопросы
для промпта в LLM.

---

### Логические уровни системы

1. **Контент (статический слой)**
  `plans_plan` → `plans_section` → `plans_unit` → `plans_question` → `plans_choice`  
   Структура курса, не меняющаяся при прохождении.
2. **Действия пользователя (динамический слой)**
  `learning_enrollment` → `learning_attempt` → `learning_answer` → `learning_answer_choice`  
   История взаимодействия пользователя с курсом.
3. **Агрегированная аналитика**
  `learning_unit_progress`, `learning_section_progress`, `learning_question_stats`  
   Быстрый доступ к прогрессу и слабым местам без тяжёлых пересчётов.

Такая схема хорошо подходит под RAG‑генерацию курсов, адаптивное обучение и аналитику прогресса.