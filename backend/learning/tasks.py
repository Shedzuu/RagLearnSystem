from celery import shared_task
import logging
import os
import re

from .models import Document
from .services_rag import index_documents, load_document_text_for_toc
from .services_generation import LLMClient

logger = logging.getLogger(__name__)

# Single LLM pass: текст для TOC уже урезан в load_document_text_for_toc (начало книги).
# Доп. потолок на всякий случай (плотный PDF за 30 стр.).
OUTLINE_INPUT_CHAR_LIMIT = int(os.getenv("OUTLINE_INPUT_CHAR_LIMIT", "140000"))
# Deep outlines (3+ levels). DashScope allows max_tokens in [1, 16384] for many chat models.
OUTLINE_LLM_MAX_TOKENS = min(
    16_384,
    int(os.getenv("OUTLINE_LLM_MAX_TOKENS", "16384")),
)


def _preprocess_toc_text(text: str) -> str:
    s = text or ""
    # Restore missing spaces in merged tokens: "AQuickReview" -> "A Quick Review"
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    # "13MultipleTesting" -> "13 Multiple Testing"
    s = re.sub(r"(\d)([A-Za-zА-Яа-я])", r"\1 \2", s)
    # Normalize dot leaders and whitespace
    s = re.sub(r"\.{3,}", " ... ", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s


def _parse_toc_outline_fallback(text: str) -> tuple[list[dict], list[str]]:
    """
    Deterministic fallback for TOC-like lines:
    - main: X Title
    - L2: X.Y Title
    - L3: X.Y.Z Title (nested under the current X.Y node)
    """
    outline: list[dict] = []
    topics: list[str] = []
    seen_main = set()
    seen_topic = set()
    current_main: dict | None = None
    current_l2: dict | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if len(line) < 4:
            continue
        m = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?\s+(.+?)\s*(?:\.{3,}\s*|\s+)?(\d{1,4})?$", line)
        if not m:
            continue
        a, b, c, title, page = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        title = title.strip(" .-")
        if not title:
            continue
        page_num = int(page) if page and page.isdigit() else None

        if b is None:
            label = f"{a} {title}"
            key = label.lower()
            if key in seen_main:
                continue
            seen_main.add(key)
            current_main = {"title": label, "page": page_num, "subtopics": []}
            outline.append(current_main)
            current_l2 = None
            if key not in seen_topic:
                seen_topic.add(key)
                topics.append(label)
            continue

        if current_main is None:
            current_main = {"title": f"{a}", "page": None, "subtopics": []}
            outline.append(current_main)

        if c is None:
            label = f"{a}.{b}"
            sub_title = f"{label} {title}"
            skey = sub_title.lower()
            if skey in seen_topic:
                continue
            seen_topic.add(skey)
            node = {"title": sub_title, "page": page_num, "subtopics": []}
            current_main["subtopics"].append(node)
            current_l2 = node
            topics.append(sub_title)
            continue

        # Third level: a.b.c — attach under current L2 if it matches a.b
        sub_title = f"{a}.{b}.{c} {title}"
        skey = sub_title.lower()
        if skey in seen_topic:
            continue
        seen_topic.add(skey)
        entry = {"title": sub_title, "page": page_num, "subtopics": []}
        prefix = f"{a}.{b}"
        placed = False
        if current_l2 is not None:
            t2 = (current_l2.get("title") or "").strip()
            if t2.startswith(prefix + " ") or t2.startswith(prefix + "."):
                current_l2["subtopics"].append(entry)
                placed = True
        if not placed and current_main is not None:
            for child in current_main.get("subtopics") or []:
                if not isinstance(child, dict):
                    continue
                t2 = (child.get("title") or "").strip()
                if t2.startswith(prefix + " ") or t2.startswith(prefix + "."):
                    child["subtopics"].append(entry)
                    placed = True
                    break
        if not placed and current_main is not None:
            current_main["subtopics"].append(entry)
        topics.append(sub_title)

    for n in outline:
        k = n["title"].lower()
        if k not in seen_topic:
            topics.insert(0, n["title"])
            seen_topic.add(k)
    return outline, topics


def _has_numbered_subtopics(text: str) -> bool:
    return bool(re.search(r"\b\d+\.\d+\b", text or ""))


def _descendant_topic_count(node: dict) -> int:
    n = 0
    for s in node.get("subtopics") or []:
        if isinstance(s, dict):
            n += 1 + _descendant_topic_count(s)
    return n


def _total_descendants_in_outline(outline: list[dict]) -> int:
    return sum(_descendant_topic_count(n) for n in outline if isinstance(n, dict))


def _normalize_outline_node(raw: dict) -> dict | None:
    """Recursive outline node: title, page, subtopics (each may nest further)."""
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None
    page = raw.get("page") if isinstance(raw.get("page"), int) else None
    seen_sub: set[str] = set()
    children: list[dict] = []
    for sub in raw.get("subtopics") or []:
        if not isinstance(sub, dict):
            continue
        st = str(sub.get("title") or "").strip()
        if not st:
            continue
        sk = st.lower()
        if sk in seen_sub:
            continue
        seen_sub.add(sk)
        child = _normalize_outline_node(sub)
        if child:
            children.append(child)
    return {"title": title, "page": page, "subtopics": children}


def _flatten_topics_dfs(outline: list[dict]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()

    def visit(node: dict) -> None:
        t = str(node.get("title") or "").strip()
        if not t:
            return
        k = t.lower()
        if k not in seen:
            seen.add(k)
            order.append(t)
        for ch in node.get("subtopics") or []:
            if isinstance(ch, dict):
                visit(ch)

    for n in outline:
        if isinstance(n, dict):
            visit(n)
    return order


def _extract_outline_with_llm(text: str) -> tuple[list[dict], list[str]]:
    """
    One LLM call over the beginning of the document: full outline + flat topics list.
    Caller should pass only the document head (e.g. first pages) — see load_document_text_for_toc.
    """
    llm = LLMClient()
    preprocessed = _preprocess_toc_text(text)
    system_prompt = (
        "You are a strict document structure extractor.\n"
        "Extract a table of contents / outline from the provided text.\n"
        "Return ONLY valid JSON.\n"
        "Do not include noise: ISBN, copyright, random OCR garbage, financial tables, "
        "price lists, or body paragraphs that are NOT headings.\n"
        "If there is NO real table of contents or chapter headings (e.g. only business calculations), "
        'return "outline": [] and "topics": [].\n'
        "Keep titles as in the source where they are real headings; fix obvious OCR spacing only.\n"
        "Outline structure (THREE levels minimum where the book has them):\n"
        "- Each item: {\"title\": string, \"page\": number|null, \"subtopics\": [...] }\n"
        "- Level 1 = main chapters (e.g. \"2 Statistical Learning\").\n"
        "- Level 2 = sections (e.g. \"2.1 What Is Statistical Learning?\").\n"
        "- Level 3 = subsections under a level-2 heading — put each in that level-2 item's "
        "\"subtopics\" array (e.g. \"2.1.1 Why Estimate f?\").\n"
        "Nest deeper (4+) the same way if the source has more depth.\n"
        "- topics: flat array of strings (optional; may be empty — we can derive from outline).\n"
    )
    user_prompt = (
        "Extract outline from this document beginning text:\n\n"
        f"{preprocessed[:OUTLINE_INPUT_CHAR_LIMIT]}"
    )
    data = llm.complete_json(
        system_prompt,
        user_prompt,
        max_tokens=OUTLINE_LLM_MAX_TOKENS,
    )

    raw_outline = data.get("outline") or []
    raw_topics = data.get("topics") or []

    outline: list[dict] = []
    seen_main = set()
    for node in raw_outline if isinstance(raw_outline, list) else []:
        if not isinstance(node, dict):
            continue
        title = str(node.get("title") or "").strip()
        if not title:
            continue
        key = title.lower()
        if key in seen_main:
            continue
        seen_main.add(key)
        norm = _normalize_outline_node(node)
        if norm:
            outline.append(norm)

    topics: list[str] = []
    seen_topics = set()
    if isinstance(raw_topics, list):
        for t in raw_topics:
            st = str(t or "").strip()
            if not st:
                continue
            sk = st.lower()
            if sk in seen_topics:
                continue
            seen_topics.add(sk)
            topics.append(st)

    if not topics:
        topics = _flatten_topics_dfs(outline)

    total_nested = _total_descendants_in_outline(outline)
    if _has_numbered_subtopics(preprocessed) and total_nested == 0:
        fb_outline, fb_topics = _parse_toc_outline_fallback(preprocessed)
        if fb_outline:
            logger.info("[topics] numbered subsections in text but LLM returned none; using line fallback")
            return fb_outline, fb_topics
    return outline, topics


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def index_document_task(self, document_id: int) -> int:
    try:
        doc = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return 0

    doc.index_status = Document.IndexStatus.PROCESSING
    doc.index_error = ""
    doc.save(update_fields=["index_status", "index_error"])

    try:
        stored = index_documents([doc])
        doc.index_status = Document.IndexStatus.READY
        doc.index_error = ""
        doc.save(update_fields=["index_status", "index_error"])
        extract_document_topics_task.delay(doc.id)
        return int(stored)
    except Exception as exc:
        doc.index_status = Document.IndexStatus.FAILED
        doc.index_error = str(exc)[:2000]
        doc.save(update_fields=["index_status", "index_error"])
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def extract_document_topics_task(self, document_id: int) -> int:
    try:
        doc = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return 0

    doc.topics_status = Document.TopicsStatus.PROCESSING
    doc.topics_error = ""
    doc.save(update_fields=["topics_status", "topics_error"])

    try:
        text = load_document_text_for_toc(doc) or ""
        outline, topics = _extract_outline_with_llm(text)
        # Final fallback for hard OCR cases.
        if not outline and text:
            outline, topics = _parse_toc_outline_fallback(_preprocess_toc_text(text))
        doc.extracted_topics = topics
        doc.extracted_outline = outline
        doc.topics_status = Document.TopicsStatus.READY
        doc.topics_error = ""
        doc.save(update_fields=["extracted_topics", "extracted_outline", "topics_status", "topics_error"])
        return len(topics)
    except Exception as exc:
        doc.topics_status = Document.TopicsStatus.FAILED
        doc.topics_error = str(exc)[:2000]
        doc.save(update_fields=["topics_status", "topics_error"])
        raise


@shared_task
def generate_plan_task(plan_id: int) -> None:
    """
    Background course generation: outline first (persisted), then each unit filled incrementally.
    Frontend polls PlanDetail until generation_status != processing.
    """
    from .models import Plan
    from .services_generation import generate_plan_from_documents
    from .services_rag import InsufficientCoverageError

    try:
        plan = Plan.objects.get(pk=plan_id)
    except Plan.DoesNotExist:
        logger.warning("[generate] plan %s not found", plan_id)
        return

    try:
        generate_plan_from_documents(plan)
    except InsufficientCoverageError as exc:
        logger.warning("[generate] plan %s insufficient coverage: %s", plan_id, exc)
        plan.refresh_from_db()
        plan.generation_status = Plan.GenerationStatus.FAILED
        plan.save(update_fields=["generation_status"])
    except Exception:
        logger.exception("[generate] plan %s task failed", plan_id)
        plan.refresh_from_db()
        if plan.generation_status == Plan.GenerationStatus.PROCESSING:
            plan.generation_status = Plan.GenerationStatus.FAILED
            plan.save(update_fields=["generation_status"])
