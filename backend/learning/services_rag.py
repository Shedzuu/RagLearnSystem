from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Dict, Tuple

import numpy as np
from django.conf import settings
from sentence_transformers import SentenceTransformer  # type: ignore

from .models import Plan, Document, Chunk

logger = logging.getLogger(__name__)


CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
MAX_CHUNKS_PER_PLAN = 5000
# Для оценки покрытости целей материалами
MIN_CHUNKS_PER_TOPIC = 2
# Защита от «раздутого» текста из docx/pdf (служебные данные, повторы)
MAX_CHARS_PER_DOCUMENT = 300_000


class EmbeddingService:
    """
    Wrapper around local sentence-transformers model for embeddings.
    """

    _model: SentenceTransformer | None = None

    def __init__(self) -> None:
        # Keep model local and CPU-friendly (no external embedding API dependency).
        if EmbeddingService._model is None:
            model_name = getattr(
                settings,
                "EMBEDDING_MODEL_NAME",
                "intfloat/multilingual-e5-large",
            )
            EmbeddingService._model = SentenceTransformer(model_name)
        self.model = EmbeddingService._model

    def embed_texts(self, texts: List[str], is_query: bool = False) -> np.ndarray:
        if not texts:
            return np.empty((0, 1024), dtype=np.float32)

        if is_query:
            texts = [f"query: {t}" for t in texts]
        else:
            texts = [f"passage: {t}" for t in texts]

        return self.model.encode(texts, convert_to_numpy=True)


def _load_document_text(doc: Document) -> str:
    """
    Reuse the same simple text loading logic as in services_generation,
    but keep it local to RAG to avoid circular imports.
    """
    path = Path(settings.BASE_DIR) / doc.file_path
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return text[:MAX_CHARS_PER_DOCUMENT] if len(text) > MAX_CHARS_PER_DOCUMENT else text

    if suffix == ".pdf":
        try:
            import PyPDF2  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PyPDF2 is required to extract text from PDF") from exc
        text_parts: List[str] = []
        with path.open("rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text_parts.append(page.extract_text() or "")
        text = "\n".join(text_parts)
        return text[:MAX_CHARS_PER_DOCUMENT] if len(text) > MAX_CHARS_PER_DOCUMENT else text

    if suffix == ".docx":
        try:
            import docx  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "python-docx is required to extract text from DOCX"
            ) from exc
        d = docx.Document(str(path))
        # Только параграфы тела документа (без повторяющихся headers/footers и т.д.)
        text = "\n".join(p.text or "" for p in d.paragraphs)
        return text[:MAX_CHARS_PER_DOCUMENT] if len(text) > MAX_CHARS_PER_DOCUMENT else text

    # Fallback: try to read as text
    return path.read_text(encoding="utf-8", errors="ignore")


def split_text_with_overlap(text: str, page_number: int | None = None) -> List[Dict]:
    chunks: List[Dict] = []
    start = 0
    idx = 0
    n = len(text)
    while start < n and len(chunks) < MAX_CHUNKS_PER_PLAN:
        end = min(start + CHUNK_SIZE, n)
        slice_text = text[start:end]
        # try to cut on sentence boundary in the second half of the chunk
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
        # If we reached end of text — stop to avoid infinite loop with overlap
        if end >= n:
            break
        start = end - CHUNK_OVERLAP
        if start < 0:
            start = 0
    return chunks


def index_plan_documents(plan: Plan) -> None:
    """
    Build or rebuild text chunks and embeddings for all documents of a plan.
    This is a synchronous operation; for production scale it could be moved to a background task.
    """
    docs = list(plan.documents.all())
    logger.info("[RAG] Indexing plan id=%s: %s document(s)", plan.id, len(docs))
    if not docs:
        return

    embedder = EmbeddingService()
    Chunk.objects.filter(plan=plan).delete()

    all_chunks: List[Tuple[Document, Dict]] = []
    for i, doc in enumerate(docs, 1):
        try:
            text = _load_document_text(doc)
        except Exception as e:
            logger.warning("[RAG] Skip document id=%s %s: %s", doc.id, doc.original_name, e)
            continue
        if not text:
            continue
        n_chunks = max(1, (len(text) - CHUNK_OVERLAP) // (CHUNK_SIZE - CHUNK_OVERLAP))
        logger.info("[RAG] Document %s (%s of %s): %s chars -> ~%s chunks", doc.original_name, i, len(docs), len(text), n_chunks)
        for ch in split_text_with_overlap(text, page_number=None):
            all_chunks.append((doc, ch))
            if len(all_chunks) >= MAX_CHUNKS_PER_PLAN:
                logger.warning("[RAG] Reached MAX_CHUNKS_PER_PLAN=%s, stopping", MAX_CHUNKS_PER_PLAN)
                break
        if len(all_chunks) >= MAX_CHUNKS_PER_PLAN:
            break

    if not all_chunks:
        logger.warning("[RAG] No chunks extracted from plan documents")
        return

    logger.info("[RAG] Chunks created: %s, computing embeddings...", len(all_chunks))
    contents = [c["content"] for _, c in all_chunks]
    embeddings = embedder.embed_texts(contents, is_query=False)
    logger.info("[RAG] Embeddings done, saving to DB...")

    objs: List[Chunk] = []
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
                embedding=emb,
            )
        )
    Chunk.objects.bulk_create(objs, batch_size=100)
    logger.info("[RAG] Indexing complete: %s chunks stored for plan id=%s", len(objs), plan.id)


from pgvector.django import CosineDistance  # noqa E402


class InsufficientCoverageError(Exception):
    """
    Raised when RAG cannot find enough relevant chunks for requested topics.
    """


class RAGService:
    """
    High-level API for retrieving relevant chunks for a plan.
    """

    def __init__(self) -> None:
        self.embedder = EmbeddingService()

    def search_similar_chunks(
        self, plan: Plan, query: str, top_k: int = 20
    ) -> List[Chunk]:
        q_vec = self.embedder.embed_texts([query], is_query=True)[0]
        # pgvector.django ordering by cosine distance
        return (
            Chunk.objects.filter(plan=plan, embedding__isnull=False)
            .order_by(CosineDistance("embedding", q_vec))[:top_k]
        )

    def build_context_for_topics(
        self,
        plan: Plan,
        topics: List[str],
        top_k_per_topic: int = 20,
        max_total_chars: int = 16000,
    ) -> str:
        """
        Build a textual context for LLM by selecting top chunks per topic.
        """
        chunks_by_id: Dict[int, str] = {}
        order: List[int] = []
        topic_chunk_counts: Dict[str, int] = {}

        if not topics:
            # Fallback: take first N chunks by order if no explicit goals.
            qs = Chunk.objects.filter(plan=plan).order_by("chunk_index", "id")[:top_k_per_topic]
            for ch in qs:
                chunks_by_id[ch.id] = self._format_chunk(ch, topic=None)
                order.append(ch.id)
        else:
            for topic in topics:
                count_for_topic = 0
                for ch in self.search_similar_chunks(plan, topic, top_k=top_k_per_topic):
                    if ch.id not in chunks_by_id:
                        chunks_by_id[ch.id] = self._format_chunk(ch, topic=topic)
                        order.append(ch.id)
                        count_for_topic += 1
                topic_chunk_counts[topic] = count_for_topic

        if not order:
            # нет ни одного релевантного чанка вообще
            raise InsufficientCoverageError(
                "В загруженных материалах не найдено ни одного релевантного фрагмента "
                "для указанных целей обучения."
            )

        # проверяем покрытие по темам
        if topics:
            poor_topics = [
                topic
                for topic in topics
                if topic_chunk_counts.get(topic, 0) < MIN_CHUNKS_PER_TOPIC
            ]
            if poor_topics:
                logger.warning(
                    "[RAG] Insufficient coverage for topics: %s (counts=%s)",
                    poor_topics,
                    {t: topic_chunk_counts.get(t, 0) for t in topics},
                )
                raise InsufficientCoverageError(
                    "По следующим целям в материалах очень мало или совсем нет информации: "
                    + "; ".join(poor_topics)
                )

        parts: List[str] = []
        total_len = 0
        for cid in order:
            text = chunks_by_id[cid]
            if total_len + len(text) > max_total_chars:
                break
            parts.append(text)
            total_len += len(text)

        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _format_chunk(chunk: Chunk, topic: str | None) -> str:
        header_parts = []
        if topic:
            header_parts.append(f"[topic: {topic}]")
        header_parts.append(f"[doc: {chunk.document.original_name}]")
        if chunk.page_number is not None:
            header_parts.append(f"[page: {chunk.page_number}]")
        header = " ".join(header_parts)
        return f"{header}\n{chunk.content}"

