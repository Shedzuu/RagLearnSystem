import json
import os
from pathlib import Path
from typing import List, Dict, Any

from django.conf import settings

from .models import Plan, Section, Unit, Question, Choice, Document


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

        self._client = OpenAI(api_key=self.api_key)
        # You can change model name here if needed
        self.model_name = os.getenv("LLM_MODEL", "gpt-4.1-mini")

    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """
        Call the model and expect JSON in the response.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        resp = self._client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError("Empty response from LLM")
        return json.loads(content)


def _load_document_text(doc: Document) -> str:
    """
    Very simple text loader based on file extension.
    For диплома можно начать с plain-text и PDF с текстовым слоем,
    а полноценный парсинг расширить позже.
    """
    path = Path(settings.BASE_DIR) / doc.file_path
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")

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
        return "\n".join(text_parts)

    if suffix in {".docx"}:
        try:
            import docx  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("python-docx is required to extract text from DOCX") from exc
        d = docx.Document(str(path))
        return "\n".join(p.text for p in d.paragraphs)

    # Fallback: try to read as text
    return path.read_text(encoding="utf-8", errors="ignore")


def _build_materials_context(plan: Plan) -> str:
    """
    Build a text context from all documents attached to the plan.
    For now: concatenate truncated texts with filenames.
    """
    parts: List[str] = []
    for doc in plan.documents.all():
        try:
            text = _load_document_text(doc)
        except Exception:
            continue
        # ограничиваемся первыми 4000 символами на документ, чтобы не убить модель
        snippet = text[:4000]
        header = f"[{doc.original_name}]"
        parts.append(f"{header}\n{snippet}")
    return "\n\n---\n\n".join(parts)


def _normalize_goals_with_llm(plan: Plan, llm: LLMClient) -> List[str]:
    """
    Use LLM as a normalizer: turn free-form goals text into a list of short topics.
    """
    if not plan.goals:
        return []

    system_prompt = (
        "You are an assistant that extracts learning topics from user goals. "
        "Return a JSON object with a single field 'topics' which is an array of short English phrases."
    )
    user_prompt = (
        "User's raw learning goals:\n\n"
        f"{plan.goals}\n\n"
        "Extract and normalize them into 3-10 concise topics (English), without explanations."
    )
    data = llm.complete_json(system_prompt, user_prompt)
    topics = data.get("topics") or []
    return [str(t).strip() for t in topics if str(t).strip()]


def _generate_course_structure_with_llm(plan: Plan, context: str, topics: List[str], llm: LLMClient) -> Dict[str, Any]:
    """
    Ask LLM to generate full course structure based ONLY on provided context and topics.
    """
    system_prompt = (
        "You are an assistant that designs a course structure (sections, units, questions) "
        "STRICTLY based on the provided study materials. Do not invent facts that are not supported "
        "by the materials. Output must be valid JSON."
    )

    topics_str = ", ".join(topics) if topics else "not specified explicitly"
    user_prompt = (
        f"Course title: {plan.title}\n\n"
        f"Course description: {plan.description or 'N/A'}\n\n"
        f"User learning topics: {topics_str}\n\n"
        "Study materials (excerpts):\n"
        f"{context}\n\n"
        "Using ONLY the information in the materials, design a course plan and return JSON with the following structure:\n\n"
        "{\n"
        '  "sections": [\n'
        "    {\n"
        '      "title": "string",\n'
        '      "units": [\n'
        "        {\n"
        '          "title": "string",\n'
        '          "theory": "1-3 paragraphs of explanation based only on the materials",\n'
        '          "questions": [\n'
        "            {\n"
        '              "text": "question text",\n'
        '              "type": "single_choice" | "multiple_choice" | "open_text" | "code",\n'
        '              "choices": [\n'
        '                {"text": "option text", "is_correct": true/false}\n'
        "              ] (omit or empty array for open_text/code)\n"
        "            }\n"
        "          ]\n"
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Ensure JSON is valid and does not contain comments."
    )

    return llm.complete_json(system_prompt, user_prompt)


def generate_plan_from_documents(plan: Plan) -> None:
    """
    High-level entry point: use attached documents + goals to generate
    sections, units, questions and choices for the plan.
    This function overwrites existing sections/units/questions of the plan.
    """
    llm = LLMClient()

    # 1) Build context from documents
    context = _build_materials_context(plan)
    if not context:
        raise RuntimeError("No text could be extracted from plan documents")

    # 2) Normalize goals -> topics
    topics = _normalize_goals_with_llm(plan, llm)

    # 3) Ask LLM for course structure
    structure = _generate_course_structure_with_llm(plan, context, topics, llm)

    sections_data: List[Dict[str, Any]] = structure.get("sections") or []

    # 4) Wipe previous structure
    plan.sections.all().delete()

    # 5) Persist new structure
    for s_idx, s in enumerate(sections_data, start=1):
        section = Section.objects.create(
            plan=plan,
            title=str(s.get("title") or f"Section {s_idx}"),
            order=s_idx,
            generation_status=Section.GenerationStatus.READY,
        )
        for u_idx, u in enumerate(s.get("units") or [], start=1):
            unit = Unit.objects.create(
                section=section,
                title=str(u.get("title") or f"Unit {s_idx}.{u_idx}"),
                order=u_idx,
                theory=str(u.get("theory") or ""),
                generation_status=Unit.GenerationStatus.READY,
            )
            for q_idx, q in enumerate(u.get("questions") or [], start=1):
                q_type = str(q.get("type") or "open_text")
                # normalize type to expected enum values
                if q_type not in {
                    Question.QuestionType.SINGLE_CHOICE,
                    Question.QuestionType.MULTIPLE_CHOICE,
                    Question.QuestionType.OPEN_TEXT,
                    Question.QuestionType.CODE,
                }:
                    q_type = Question.QuestionType.OPEN_TEXT

                question = Question.objects.create(
                    unit=unit,
                    text=str(q.get("text") or ""),
                    type=q_type,
                    difficulty=1,
                    order=q_idx,
                    points=1,
                )
                # choices for choice questions
                if q_type in {
                    Question.QuestionType.SINGLE_CHOICE,
                    Question.QuestionType.MULTIPLE_CHOICE,
                }:
                    for c_idx, c in enumerate(q.get("choices") or [], start=1):
                        Choice.objects.create(
                            question=question,
                            text=str(c.get("text") or ""),
                            is_correct=bool(c.get("is_correct")),
                            order=c_idx,
                        )

    # 6) Update plan status
    plan.generation_status = Plan.GenerationStatus.READY
    plan.save(update_fields=["generation_status"])

