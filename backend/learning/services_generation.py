import json
import logging
import os
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Set

from .models import Plan, Section, Unit, Question, Choice
from .services_rag import DocumentRAGService, index_documents

logger = logging.getLogger(__name__)

# Outline step: broad RAG slice for structuring the course.
_DEFAULT_GENERATION_CONTEXT_CHARS = int(os.getenv("LLM_GENERATION_CONTEXT_CHARS", "52000"))
_DEFAULT_GENERATION_TOP_K_PER_TOPIC = int(os.getenv("LLM_GENERATION_TOP_K_PER_TOPIC", "28"))
_DEFAULT_OUTLINE_MAX_TOKENS = int(os.getenv("LLM_OUTLINE_MAX_TOKENS", "6000"))
# Per-unit step: focused context + large completion for theory + many questions.
_DEFAULT_UNIT_CONTEXT_CHARS = int(os.getenv("LLM_UNIT_CONTEXT_CHARS", "36000"))
_DEFAULT_UNIT_CONTEXT_TOP_K = int(os.getenv("LLM_UNIT_CONTEXT_TOP_K", "40"))
_DEFAULT_UNIT_MAX_TOKENS = int(os.getenv("LLM_UNIT_MAX_TOKENS", "10000"))
_DEFAULT_UNIT_MIN_QUESTIONS = int(os.getenv("LLM_UNIT_MIN_QUESTIONS", "5"))
# RAG for a single unit title can be nearly empty (e.g. topic not in source); then merge broad context.
_MIN_UNIT_RAG_CHARS = int(os.getenv("LLM_MIN_UNIT_RAG_CHARS", "900"))
_MIN_SAVED_THEORY_CHARS = int(os.getenv("LLM_MIN_SAVED_THEORY_CHARS", "200"))
_MIN_SAVED_QUESTIONS = int(os.getenv("LLM_MIN_SAVED_QUESTIONS", "3"))
# Extra LLM call per unit: paraphrases / synonyms for richer, less redundant retrieval.
_UNIT_QUERY_EXPAND_MAX_TOKENS = int(os.getenv("LLM_UNIT_QUERY_EXPAND_MAX_TOKENS", "500"))
_DEFAULT_UNIT_MULTI_TOPK = int(os.getenv("LLM_UNIT_MULTI_TOPK", "12"))


def _output_language_instruction(plan: Plan) -> str:
    """Single block appended to LLM prompts so titles/theory/questions stay in one language."""
    code = getattr(plan, "content_language", None) or Plan.ContentLanguage.AUTO
    if code not in {
        Plan.ContentLanguage.AUTO,
        Plan.ContentLanguage.RU,
        Plan.ContentLanguage.EN,
    }:
        code = Plan.ContentLanguage.AUTO
    if code == Plan.ContentLanguage.RU:
        return (
            "LANGUAGE: Output in Russian only — section titles, unit titles, theory, and every question "
            "and choice. Latin letters only for usual technical symbols/identifiers (e.g. Python, ML). "
            "Do not mix in English sentences."
        )
    if code == Plan.ContentLanguage.EN:
        return (
            "LANGUAGE: Output in English only — section titles, unit titles, theory, and every question "
            "and choice. Do not use Cyrillic."
        )
    return (
        "LANGUAGE: Infer one working language from the user's goals and the study-material excerpts. "
        "Use that language consistently for all titles, theory, and questions. If goals and excerpts "
        "conflict, follow the excerpts. Never mix two natural languages in the same unit."
    )


def strip_light_markdown_for_ui(text: str) -> str:
    """
    Remove bold/underscore markdown that the UI shows verbatim (no markdown renderer).
    Keeps plain text; strips **word** and __word__ repeatedly.
    """
    if not text:
        return ""
    s = str(text)
    for _ in range(16):
        nxt = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        nxt = re.sub(r"__([^_]+)__", r"\1", nxt)
        if nxt == s:
            break
        s = nxt
    return s


class LLMClient:
    """
    Thin wrapper around an LLM API.

    Expects LLM_API_KEY in environment and uses a generic OpenAI-compatible client.
    You can swap the implementation to your provider without changing callers.
    """

    def __init__(self) -> None:
        self.api_key = os.getenv("LLM_API_KEY")
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY is not set in environment")

        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError(
                "openai package is required for LLMClient. Install it in backend image."
            ) from exc

        base_url = os.getenv("LLM_BASE_URL")  # e.g. https://openrouter.ai/api/v1
        self._client = OpenAI(api_key=self.api_key, **({"base_url": base_url} if base_url else {}))
        self.model_name = os.getenv("LLM_MODEL", "gpt-4.1-mini")

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        """
        Call the model and expect JSON in the response.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs: dict = {"temperature": temperature}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    response_format={"type": "json_object"},
                    **kwargs,
                )
                content = resp.choices[0].message.content
                if not content:
                    raise RuntimeError("Empty response from LLM")
                return json.loads(content)
            except Exception as exc:  # pragma: no cover - network/runtime errors
                last_exc = exc
                wait_s = 2 * (attempt + 1)
                logger.warning(
                    "[generate] LLM call failed on attempt %s/3: %s. Retrying in %ss...",
                    attempt + 1,
                    exc,
                    wait_s,
                )
                time.sleep(wait_s)
        # Если все попытки провалились — пробрасываем последнее исключение
        assert last_exc is not None
        raise last_exc


def _normalize_goals_with_llm(plan: Plan, llm: LLMClient) -> List[str]:
    """
    Use LLM as a normalizer: turn free-form goals text into a list of short topics.
    """
    if not plan.goals:
        return []

    lang = getattr(plan, "content_language", None) or Plan.ContentLanguage.AUTO
    if lang == Plan.ContentLanguage.RU:
        topics_rule = (
            "Return a JSON object with a single field 'topics' which is an array of short Russian phrases "
            "(learning-focus labels for search), without explanations."
        )
        user_topics = "Extract and normalize them into 3-10 concise topics in Russian, without explanations."
    elif lang == Plan.ContentLanguage.EN:
        topics_rule = (
            "Return a JSON object with a single field 'topics' which is an array of short English phrases."
        )
        user_topics = "Extract and normalize them into 3-10 concise topics in English, without explanations."
    else:
        topics_rule = (
            "Return a JSON object with a single field 'topics' which is an array of short phrases. "
            "Use Russian if the goals are mainly in Cyrillic, otherwise English."
        )
        user_topics = (
            "Extract and normalize them into 3-10 concise topics in that same language, without explanations."
        )

    system_prompt = "You are an assistant that extracts learning topics from user goals. " + topics_rule
    user_prompt = (
        "User's raw learning goals:\n\n"
        f"{plan.goals}\n\n"
        f"{user_topics}\n\n"
        f"{_output_language_instruction(plan)}"
    )
    logger.info("[generate] Normalizing goals -> topics (LLM)...")
    data = llm.complete_json(system_prompt, user_prompt)
    topics = data.get("topics") or []
    result = [str(t).strip() for t in topics if str(t).strip()]
    logger.info("[generate] Topics: %s", result)
    return result


def _generate_course_outline_with_llm(
    plan: Plan, context: str, topics: List[str], llm: LLMClient
) -> Dict[str, Any]:
    """
    Step 1 — outline only: section titles and unit titles (no theory/questions here).
    """
    system_prompt = (
        "You are an assistant that designs a course OUTLINE (sections and unit titles only) "
        "STRICTLY based on the provided study materials. "
        "Do not invent major topics not supported by the materials. Output valid JSON only."
    )
    topics_str = ", ".join(topics) if topics else "not specified explicitly"
    user_prompt = (
        f"Course title: {plan.title}\n\n"
        f"Course description: {plan.description or 'N/A'}\n\n"
        f"User learning topics: {topics_str}\n\n"
        "Study materials (excerpts):\n"
        f"{context}\n\n"
        f"{_output_language_instruction(plan)}\n\n"
        "Return JSON exactly of the form:\n"
        "{\n"
        '  "sections": [\n'
        "    {\n"
        '      "title": "string",\n'
        '      "units": [\n'
        '        { "title": "string" }\n'
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- 3–8 sections typical; each section 2–6 units (prefer more smaller units over one huge unit).\n"
        "- Unit titles must be specific (not 'Introduction' everywhere).\n"
        "- Cover user learning topics across the outline.\n"
        "- No theory or questions in this step — titles only.\n"
    )
    logger.info("[generate] LLM: course outline (sections / unit titles)...")
    return llm.complete_json(
        system_prompt,
        user_prompt,
        max_tokens=_DEFAULT_OUTLINE_MAX_TOKENS,
        temperature=0.2,
    )


def _expand_unit_search_queries_llm(
    plan: Plan,
    llm: LLMClient,
    section_title: str,
    unit_title: str,
    topics: List[str],
    base_query: str,
) -> List[str]:
    """
    Short LLM step: diverse search strings for embedding retrieval (synonyms, related concepts).
    """
    if os.getenv("LLM_UNIT_QUERY_EXPAND", "1").lower() in ("0", "false", "no"):
        return [base_query] if base_query.strip() else [f"{section_title} {unit_title}".strip()]

    topics_str = ", ".join(topics[:8]) if topics else ""
    try:
        data = llm.complete_json(
            "Return ONLY JSON {\"queries\": [\"\", ...]}.\n"
            "You generate 2–4 SHORT search queries (keywords / short phrases) for semantic search over a textbook. "
            "They should paraphrase the learning focus: synonyms, equivalent statistical/ML terms, "
            "and adjacent subtopics that still belong to THIS unit only.\n"
            f"{_output_language_instruction(plan)}\n"
            "For queries: prefer the same language as required for course content; mix in standard English "
            "technical tokens only if they help retrieval.\n"
            "No explanations, no numbering outside the JSON.",
            f"Section: {section_title}\nUnit: {unit_title}\nGoals (hints): {topics_str}\nBase query: {base_query}\n",
            max_tokens=_UNIT_QUERY_EXPAND_MAX_TOKENS,
            temperature=0.35,
        )
        extra = [str(x).strip() for x in (data.get("queries") or []) if str(x).strip()]
        out: List[str] = []
        for q in [base_query.strip()] + extra:
            if not q:
                continue
            if q.lower() not in {x.lower() for x in out}:
                out.append(q)
        return out[:6] if out else [base_query]
    except Exception:
        logger.warning("[generate] query expand failed; using base query only")
        return [base_query] if base_query.strip() else [f"{section_title} {unit_title}".strip()]


def _generate_unit_payload_with_llm(
    plan: Plan,
    section_title: str,
    unit_title: str,
    topics: List[str],
    context: str,
    llm: LLMClient,
) -> Dict[str, Any]:
    """
    Step 2 — one unit: long theory + many questions, grounded in context.
    """
    topics_str = ", ".join(topics) if topics else "not specified explicitly"
    system_prompt = (
        "You are an assistant that writes ONE study unit (theory + assessment questions) "
        "from several excerpt blocks of the same source (possibly from different chapters). "
        "Synthesize a clear explanation in plain language — not copy-pasted sentences; "
        "combine ideas where it helps, but do NOT add facts that are not supported by the excerpts. "
        "Plain text only for theory and questions — no markdown. Output valid JSON.\n"
        f"{_output_language_instruction(plan)}"
    )
    user_prompt = (
        f"Course: {plan.title}\n"
        f"Section: {section_title}\n"
        f"Unit: {unit_title}\n"
        f"Overall learning topics: {topics_str}\n\n"
        "Excerpts from materials (multiple passages; may overlap or complement each other):\n"
        f"{context}\n\n"
        "Return JSON:\n"
        "{\n"
        f'  "theory": "string (plain text only, no markdown). Minimum length: aim for '
        f'{_DEFAULT_UNIT_MIN_QUESTIONS * 120}+ characters of real explanation — multiple paragraphs: '
        "definitions, intuition, worked intuition or steps if the source supports it, key formulas in plain text if present.\",\n"
        '  "questions": [\n'
        "    {\n"
        '      "text": "string",\n'
        '      "type": "single_choice" | "multiple_choice" | "open_text" | "code",\n'
        '      "choices": [{"text": "string", "is_correct": true/false}]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Requirements: at least {_DEFAULT_UNIT_MIN_QUESTIONS} questions. "
        "Include at least two single_choice, at least two open_text, and at least one multiple_choice "
        "(use type code only if the source contains executable-style snippets or algorithms). "
        "Choice items: at least 4 options; single_choice has exactly one is_correct true; "
        "multiple_choice has two or more is_correct true. "
        "Vary difficulty; ask both recall and short applied problems when excerpts allow.\n"
    )
    logger.info("[generate] LLM: unit payload %s / %s", section_title[:40], unit_title[:40])
    return llm.complete_json(
        system_prompt,
        user_prompt,
        max_tokens=_DEFAULT_UNIT_MAX_TOKENS,
        temperature=0.25,
    )


def _merge_narrow_and_broad_context(narrow: str, broad: str, max_chars: int) -> str:
    """If per-unit retrieval is thin, append slice of outline-level context so the LLM always sees source text."""
    n = (narrow or "").strip()
    b = (broad or "").strip()
    if len(n) >= _MIN_UNIT_RAG_CHARS:
        return n[:max_chars]
    budget = max(0, max_chars - len(n) - 80)
    merged = (
        n
        + "\n\n--- Additional excerpts from the same materials (broader retrieval) ---\n\n"
        + b[:budget]
    )
    return merged[:max_chars]


def _unit_payload_meets_minimum(payload: Dict[str, Any]) -> bool:
    theory = strip_light_markdown_for_ui(str(payload.get("theory") or "")).strip()
    if len(theory) < _MIN_SAVED_THEORY_CHARS:
        return False
    qs = payload.get("questions") or []
    valid = [
        q
        for q in qs
        if isinstance(q, dict) and str(q.get("text") or "").strip()
    ]
    return len(valid) >= _MIN_SAVED_QUESTIONS


def _persist_questions_for_unit(unit: Unit, raw_questions: List[Dict[str, Any]]) -> None:
    unit.questions.all().delete()
    for q_idx, q in enumerate(raw_questions or [], start=1):
        q_type = str(q.get("type") or "open_text")
        if q_type not in {
            Question.QuestionType.SINGLE_CHOICE,
            Question.QuestionType.MULTIPLE_CHOICE,
            Question.QuestionType.OPEN_TEXT,
            Question.QuestionType.CODE,
        }:
            q_type = Question.QuestionType.OPEN_TEXT

        question = Question.objects.create(
            unit=unit,
            text=strip_light_markdown_for_ui(str(q.get("text") or "")),
            type=q_type,
            difficulty=1,
            order=q_idx,
            points=1,
        )
        if q_type in {
            Question.QuestionType.SINGLE_CHOICE,
            Question.QuestionType.MULTIPLE_CHOICE,
        }:
            for c_idx, c in enumerate(q.get("choices") or [], start=1):
                Choice.objects.create(
                    question=question,
                    text=strip_light_markdown_for_ui(str(c.get("text") or "")),
                    is_correct=bool(c.get("is_correct")),
                    order=c_idx,
                )


def generate_plan_from_documents(plan: Plan) -> None:
    """
    High-level entry point: use attached documents + goals to generate
    sections, units, questions and choices for the plan.
    This function overwrites existing sections/units/questions of the plan.
    """
    llm = LLMClient()

    logger.info("[generate] Step 1/4: Normalizing goals -> topics...")
    topics = _normalize_goals_with_llm(plan, llm)

    logger.info("[generate] Step 2/4: Building doc-level RAG context from chunks...")
    rag = DocumentRAGService()
    documents = list(plan.documents.all())

    # Ensure doc-level chunks exist. Re-index only documents that are missing.
    try:
        missing = [d for d in documents if not d.doc_chunks.exists()]
        if missing:
            logger.info(
                "[generate] Doc-level indexing missing for %s doc(s); indexing now...",
                len(missing),
            )
            index_documents(missing)
    except Exception:
        # If indexing check fails, we'll still try to build context; it may raise.
        pass

    try:
        context = rag.build_context_for_topics(
            documents,
            topics,
            top_k_per_topic=_DEFAULT_GENERATION_TOP_K_PER_TOPIC,
            max_total_chars=_DEFAULT_GENERATION_CONTEXT_CHARS,
        )
    except Exception:
        # Fallback until doc-level migrations/indexing are fully available.
        parts = []
        total = 0
        per_doc_cap = min(12_000, _DEFAULT_GENERATION_CONTEXT_CHARS // 2)
        max_total_chars = _DEFAULT_GENERATION_CONTEXT_CHARS
        from .services_rag import _load_document_text

        for doc in documents:
            try:
                text = _load_document_text(doc) or ""
            except Exception:
                text = ""
            if not text:
                continue
            snippet = text[:per_doc_cap]
            block = f"[doc: {doc.original_name}]\n{snippet}"
            if total + len(block) > max_total_chars:
                break
            parts.append(block)
            total += len(block)
        context = "\n\n---\n\n".join(parts)
    if not context:
        raise RuntimeError("No context could be built from plan documents")
    logger.info("[generate] RAG context (outline) length: %s chars", len(context))

    logger.info("[generate] Step 3/4: Outline via LLM (sections + unit titles)...")
    structure = _generate_course_outline_with_llm(plan, context, topics, llm)

    sections_data: List[Dict[str, Any]] = structure.get("sections") or []
    if not sections_data:
        raise RuntimeError("LLM returned empty course outline")

    logger.info("[generate] Persisting skeleton: %s sections", len(sections_data))
    plan.sections.all().delete()

    for s_idx, s in enumerate(sections_data, start=1):
        section = Section.objects.create(
            plan=plan,
            title=strip_light_markdown_for_ui(str(s.get("title") or f"Section {s_idx}")),
            order=s_idx,
            generation_status=Section.GenerationStatus.GENERATING,
        )
        units_raw = s.get("units") or []
        for u_idx, u in enumerate(units_raw, start=1):
            if isinstance(u, dict):
                utitle = u.get("title")
            else:
                utitle = u
            Unit.objects.create(
                section=section,
                title=strip_light_markdown_for_ui(str(utitle or f"Unit {s_idx}.{u_idx}")),
                order=u_idx,
                theory="",
                generation_status=Unit.GenerationStatus.GENERATING,
            )

    logger.info("[generate] Step 4/4: Filling units one by one (RAG + LLM per unit)...")
    units_ok = 0
    units_failed = 0
    used_chunk_ids: Set[int] = set()

    for section in Section.objects.filter(plan=plan).order_by("order", "id"):
        for unit in Unit.objects.filter(section=section).order_by("order", "id"):
            try:
                query_bits = [section.title, unit.title] + (topics[:8] if topics else [])
                base_query = ". ".join(strip_light_markdown_for_ui(x) for x in query_bits if x)
                search_queries = _expand_unit_search_queries_llm(
                    plan, llm, section.title, unit.title, topics, base_query
                )
                try:
                    unit_ctx, picked_ids = rag.build_context_multiquery(
                        documents,
                        search_queries,
                        top_k_per_query=_DEFAULT_UNIT_MULTI_TOPK,
                        max_total_chars=_DEFAULT_UNIT_CONTEXT_CHARS,
                        exclude_chunk_ids=used_chunk_ids,
                    )
                    used_chunk_ids |= picked_ids
                except Exception:
                    unit_ctx = ""
                    picked_ids = set()

                if len((unit_ctx or "").strip()) < _MIN_UNIT_RAG_CHARS:
                    unit_ctx = _merge_narrow_and_broad_context(unit_ctx, context, _DEFAULT_UNIT_CONTEXT_CHARS)

                payload = _generate_unit_payload_with_llm(
                    plan,
                    section.title,
                    unit.title,
                    topics,
                    unit_ctx,
                    llm,
                )
                if not _unit_payload_meets_minimum(payload):
                    logger.warning(
                        "[generate] Thin LLM payload for unit id=%s (%s), retry with broad outline context",
                        unit.id,
                        unit.title[:60],
                    )
                    payload = _generate_unit_payload_with_llm(
                        plan,
                        section.title,
                        unit.title,
                        topics,
                        context[:_DEFAULT_UNIT_CONTEXT_CHARS],
                        llm,
                    )
                if not _unit_payload_meets_minimum(payload):
                    n_theory = len(strip_light_markdown_for_ui(str(payload.get("theory") or "")).strip())
                    n_q = len(
                        [
                            q
                            for q in (payload.get("questions") or [])
                            if isinstance(q, dict) and str(q.get("text") or "").strip()
                        ]
                    )
                    raise ValueError(
                        f"Insufficient generated content after retry (theory_chars={n_theory}, questions={n_q}). "
                        "Try different goals or materials."
                    )

                theory = strip_light_markdown_for_ui(str(payload.get("theory") or ""))
                unit.theory = theory
                unit.save(update_fields=["theory"])
                _persist_questions_for_unit(unit, payload.get("questions") or [])
                unit.generation_status = Unit.GenerationStatus.READY
                unit.save(update_fields=["generation_status"])
                units_ok += 1
                logger.info(
                    "[generate] unit id=%s OK: theory_chars=%s question_count=%s",
                    unit.id,
                    len(theory),
                    unit.questions.count(),
                )
            except Exception as exc:
                logger.exception("[generate] Unit id=%s failed: %s", unit.id, exc)
                if getattr(plan, "content_language", None) == Plan.ContentLanguage.EN:
                    fail_msg = (
                        "This unit could not be generated automatically. Try running generation again "
                        f"or simplify your goals. Details: {str(exc)[:240]}"
                    )
                else:
                    fail_msg = (
                        "Модуль не удалось сгенерировать автоматически. Попробуйте запустить генерацию снова "
                        f"или упростите цели. Детали: {str(exc)[:240]}"
                    )
                unit.theory = strip_light_markdown_for_ui(fail_msg)
                unit.generation_status = Unit.GenerationStatus.FAILED
                unit.save(update_fields=["theory", "generation_status"])
                units_failed += 1

        if Unit.objects.filter(section=section, generation_status=Unit.GenerationStatus.READY).exists():
            section.generation_status = Section.GenerationStatus.READY
        else:
            section.generation_status = Section.GenerationStatus.FAILED
        section.save(update_fields=["generation_status"])

    if units_ok == 0:
        plan.generation_status = Plan.GenerationStatus.FAILED
    else:
        plan.generation_status = Plan.GenerationStatus.READY
    plan.save(update_fields=["generation_status"])
    logger.info(
        "[generate] Done: plan_id=%s units_ok=%s units_failed=%s plan_status=%s",
        plan.id,
        units_ok,
        units_failed,
        plan.generation_status,
    )

