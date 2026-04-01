import json
import os
import re
from pathlib import Path

from django.conf import settings
from django.db.models import Prefetch, Sum, Count, F
from django.db.models.functions import NullIf
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Plan,
    Unit,
    Attempt,
    Enrollment,
    Question,
    Choice,
    Answer,
    AnswerChoice,
    Document,
    UnitProgress,
    SectionProgress,
    QuestionStats,
    AiChatMessage,
)
from .serializers import (
    PlanListSerializer,
    PlanDetailSerializer,
    UnitDetailSerializer,
    AnswerCreateSerializer,
)
from .services_generation import LLMClient, strip_light_markdown_for_ui
from .services_rag import DocumentRAGService, _load_document_text
from .tasks import index_document_task, extract_document_topics_task


class PlanListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PlanListSerializer

    def get_queryset(self):
        return Plan.objects.filter(owner=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class PlanDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PlanDetailSerializer
    queryset = Plan.objects.all()

    def get_queryset(self):
        return Plan.objects.filter(owner=self.request.user).prefetch_related(
            Prefetch(
                "documents",
                queryset=Document.objects.order_by("-uploaded_at"),
            )
        )


class UnitDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UnitDetailSerializer
    queryset = Unit.objects.select_related("section__plan").prefetch_related(
        "questions__choices"
    )

    def get_queryset(self):
        # Разрешаем доступ только к юнитам планов текущего пользователя
        return (
            super()
            .get_queryset()
            .filter(section__plan__owner=self.request.user)
        )


class UnitStateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, unit_id, *args, **kwargs):
        unit = get_object_or_404(
            Unit.objects.select_related("section__plan").prefetch_related("questions"),
            id=unit_id,
            section__plan__owner=request.user,
        )

        enrollment = Enrollment.objects.filter(
            user=request.user, plan=unit.section.plan
        ).first()
        if not enrollment:
            return Response(
                {
                    "unit_id": unit.id,
                    "section_id": unit.section_id,
                    "plan_id": unit.section.plan_id,
                    "attempt_id": None,
                    "has_finished": False,
                    "result": None,
                    "answers": [],
                },
                status=status.HTTP_200_OK,
            )

        # Приоритет: последняя попытка, у которой ЕСТЬ ответы по этому юниту
        # (неважно, active или finished). Если таких нет — любая active.
        latest_with_answers = (
            Attempt.objects.filter(
                enrollment=enrollment,
                answers__question__unit=unit,
            )
            .distinct()
            .order_by("-started_at")
            .first()
        )
        if not latest_with_answers:
            latest_with_answers = (
                Attempt.objects.filter(
                    enrollment=enrollment, finished_at__isnull=True
                )
                .order_by("-started_at")
                .first()
            )
        selected_attempt = latest_with_answers

        if not selected_attempt:
            return Response(
                {
                    "unit_id": unit.id,
                    "section_id": unit.section_id,
                    "plan_id": unit.section.plan_id,
                    "attempt_id": None,
                    "has_finished": False,
                    "result": None,
                    "answers": [],
                },
                status=status.HTTP_200_OK,
            )

        answers_qs = (
            Answer.objects.filter(attempt=selected_attempt, question__unit=unit)
            .select_related("question")
            .prefetch_related("selected_choices")
        )

        answers_payload = []
        for answer in answers_qs:
            answers_payload.append(
                {
                    "question_id": answer.question_id,
                    "text_answer": answer.text_answer or "",
                    "code_answer": answer.code_answer or "",
                    "selected_choice_ids": list(
                        answer.selected_choices.values_list("choice_id", flat=True)
                    ),
                    "last_result": {
                        "is_correct": answer.is_correct,
                        "earned_points": answer.earned_points,
                        "feedback_text": answer.feedback_text or "",
                    },
                }
            )

        has_finished = selected_attempt.finished_at is not None
        result_payload = None
        if has_finished and answers_qs.exists():
            max_points = float(
                Question.objects.filter(
                    id__in=answers_qs.values_list("question_id", flat=True)
                ).aggregate(total=Sum("points"))["total"]
                or 0.0
            )
            earned_points = float(
                answers_qs.aggregate(total=Sum("earned_points"))["total"] or 0.0
            )
            correct_count = answers_qs.filter(is_correct=True).count()
            total_questions = answers_qs.count()
            score_percent = (earned_points / max_points * 100.0) if max_points > 0 else 0.0
            result_payload = {
                "score_percent": score_percent,
                "correct_count": correct_count,
                "total_questions": total_questions,
                "earned_points": earned_points,
                "max_points": max_points,
            }

        return Response(
            {
                "unit_id": unit.id,
                "section_id": unit.section_id,
                "plan_id": unit.section.plan_id,
                "attempt_id": selected_attempt.id,
                "has_finished": has_finished,
                "result": result_payload,
                "answers": answers_payload,
            },
            status=status.HTTP_200_OK,
        )


class PlanProgressView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, plan_id, *args, **kwargs):
        plan = get_object_or_404(Plan, id=plan_id, owner=request.user)
        enrollment = Enrollment.objects.filter(user=request.user, plan=plan).first()

        sections = plan.sections.prefetch_related("units").all()
        units = [u for section in sections for u in section.units.all()]
        total_units = len(units)

        if not enrollment or total_units == 0:
            return Response(
                {
                    "plan_id": plan.id,
                    "plan_progress_percent": 0.0,
                    "completed_units": 0,
                    "total_units": total_units,
                    "sections": [
                        {
                            "section_id": section.id,
                            "title": section.title,
                            "progress_percent": 0.0,
                            "completed": False,
                            "units": [
                                {
                                    "unit_id": unit.id,
                                    "title": unit.title,
                                    "progress_percent": 0.0,
                                    "completed": False,
                                }
                                for unit in section.units.all()
                            ],
                        }
                        for section in sections
                    ],
                },
                status=status.HTTP_200_OK,
            )

        unit_progress_map = {
            up.unit_id: up
            for up in UnitProgress.objects.filter(enrollment=enrollment, unit__in=units)
        }
        section_progress_map = {
            sp.section_id: sp
            for sp in SectionProgress.objects.filter(
                enrollment=enrollment, section__in=sections
            )
        }

        completed_units = 0
        units_progress_sum = 0.0
        sections_payload = []

        for section in sections:
            section_units_payload = []
            section_units = list(section.units.all())
            section_completed_units = 0
            section_progress_sum = 0.0

            for unit in section_units:
                up = unit_progress_map.get(unit.id)
                progress_percent = float(up.progress_percent) if up else 0.0
                completed = bool(up.completed) if up else False
                if completed:
                    completed_units += 1
                    section_completed_units += 1
                units_progress_sum += progress_percent
                section_progress_sum += progress_percent
                section_units_payload.append(
                    {
                        "unit_id": unit.id,
                        "title": unit.title,
                        "progress_percent": progress_percent,
                        "completed": completed,
                    }
                )

            sp = section_progress_map.get(section.id)
            if sp:
                section_progress_percent = float(sp.progress_percent)
                section_completed = bool(sp.completed)
            else:
                section_progress_percent = (
                    section_progress_sum / len(section_units) if section_units else 0.0
                )
                section_completed = (
                    section_completed_units == len(section_units) and len(section_units) > 0
                )

            sections_payload.append(
                {
                    "section_id": section.id,
                    "title": section.title,
                    "progress_percent": section_progress_percent,
                    "completed": section_completed,
                    "units": section_units_payload,
                }
            )

        plan_progress_percent = units_progress_sum / total_units if total_units else 0.0
        return Response(
            {
                "plan_id": plan.id,
                "plan_progress_percent": plan_progress_percent,
                "completed_units": completed_units,
                "total_units": total_units,
                "sections": sections_payload,
            },
            status=status.HTTP_200_OK,
        )


class StartAttemptView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        plan_id = request.data.get("plan_id")
        if not plan_id:
            return Response(
                {"detail": "plan_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan = get_object_or_404(Plan, id=plan_id, owner=request.user)
        enrollment, _ = Enrollment.objects.get_or_create(
            user=request.user, plan=plan
        )
        # Переиспользуем активную попытку, чтобы не терять ответы
        # при переходах между юнитами в рамках одной сессии обучения.
        attempt = (
            Attempt.objects.filter(
                enrollment=enrollment,
                finished_at__isnull=True,
            )
            .order_by("-started_at")
            .first()
        )
        if attempt:
            return Response({"attempt_id": attempt.id}, status=status.HTTP_200_OK)

        attempt = Attempt.objects.create(enrollment=enrollment)
        return Response({"attempt_id": attempt.id}, status=status.HTTP_201_CREATED)


class SubmitAnswerView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = AnswerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        attempt = get_object_or_404(
            Attempt,
            id=data["attempt_id"],
            enrollment__user=request.user,
        )
        question = get_object_or_404(
            Question,
            id=data["question_id"],
            unit__section__plan__owner=request.user,
        )

        answer, _ = Answer.objects.get_or_create(
            attempt=attempt,
            question=question,
        )
        answer.text_answer = data.get("text_answer", "")
        answer.code_answer = data.get("code_answer", "")

        # Обработка выбранных вариантов для choice-вопросов
        selected_choices = data.get("selected_choices") or []
        AnswerChoice.objects.filter(answer=answer).delete()
        if selected_choices:
            for item in selected_choices:
                choice = get_object_or_404(
                    Choice, id=item["choice_id"], question=question
                )
                AnswerChoice.objects.create(answer=answer, choice=choice)

        # Простейшая проверка корректности для тестов с вариантами
        if question.type in {
            Question.QuestionType.SINGLE_CHOICE,
            Question.QuestionType.MULTIPLE_CHOICE,
        }:
            correct_ids = set(
                question.choices.filter(is_correct=True).values_list("id", flat=True)
            )
            selected_ids = set(
                AnswerChoice.objects.filter(answer=answer).values_list(
                    "choice_id", flat=True
                )
            )
            is_correct = selected_ids == correct_ids and bool(correct_ids)
            answer.is_correct = is_correct
            answer.earned_points = question.points if is_correct else 0
        elif question.type in {
            Question.QuestionType.OPEN_TEXT,
            Question.QuestionType.CODE,
        }:
            # LLM grading for open_text/code, grounded by unit theory.
            user_answer = (
                answer.code_answer
                if question.type == Question.QuestionType.CODE
                else answer.text_answer
            ).strip()
            if user_answer:
                llm = LLMClient()
                unit = question.unit
                system_prompt = (
                    "You are a strict tutor and grader. "
                    "Grade the student's answer using ONLY the provided theory context. "
                    "Return a JSON object with fields: "
                    "'score' (number 0..1), 'is_correct' (boolean), "
                    "'correct_answer' (string), 'feedback' (string). "
                    "Be concise, specific, and cite what part of theory applies. "
                    "If theory is insufficient to judge, set score=0, is_correct=false "
                    "and explain what is missing."
                )
                user_prompt = (
                    f"THEORY CONTEXT:\n{unit.theory}\n\n"
                    f"QUESTION:\n{question.text}\n\n"
                    f"STUDENT ANSWER:\n{user_answer}\n\n"
                    "Now return JSON."
                )
                data = llm.complete_json(system_prompt, user_prompt)
                score = float(data.get("score") or 0.0)
                if score < 0:
                    score = 0.0
                if score > 1:
                    score = 1.0
                is_correct = bool(data.get("is_correct")) or score >= 0.8

                answer.is_correct = is_correct
                answer.earned_points = (question.points or 1) * score
                answer.feedback_text = str(data.get("feedback") or "").strip()
                correct_answer = str(data.get("correct_answer") or "").strip()
            else:
                correct_answer = ""

        answer.save()

        return Response(
            {
                "answer_id": answer.id,
                "is_correct": answer.is_correct,
                "earned_points": answer.earned_points,
                "feedback_text": answer.feedback_text,
                "correct_answer": correct_answer if question.type in {Question.QuestionType.OPEN_TEXT, Question.QuestionType.CODE} else "",
            },
            status=status.HTTP_200_OK,
        )


class FinishAttemptView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        attempt_id = request.data.get("attempt_id")
        section_id = request.data.get("section_id")
        unit_id = request.data.get("unit_id")
        if not attempt_id:
            return Response(
                {"detail": "attempt_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not section_id and not unit_id:
            return Response(
                {"detail": "section_id or unit_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        attempt = get_object_or_404(
            Attempt,
            id=attempt_id,
            enrollment__user=request.user,
        )
        enrollment = attempt.enrollment

        answers_filter = {"attempt": attempt}
        if unit_id:
            # Приоритетно считаем по одному юниту (UI-странице), если передан unit_id.
            answers_filter["question__unit_id"] = unit_id
        else:
            answers_filter["question__unit__section_id"] = section_id

        answers_qs = Answer.objects.filter(**answers_filter).select_related(
            "question__unit__section"
        )
        if not answers_qs.exists():
            return Response(
                {
                    "attempt_id": attempt.id,
                    "score_percent": 0.0,
                    "correct_count": 0,
                    "total_questions": 0,
                    "earned_points": 0.0,
                    "max_points": 0.0,
                    "unit_progress": [],
                    "section_progress": [],
                },
                status=status.HTTP_200_OK,
            )

        question_ids = answers_qs.values_list("question_id", flat=True).distinct()
        questions = Question.objects.filter(id__in=question_ids)

        max_points = float(questions.aggregate(total=Sum("points"))["total"] or 0.0)
        earned_points = float(
            answers_qs.aggregate(total=Sum("earned_points"))["total"] or 0.0
        )
        correct_count = answers_qs.filter(is_correct=True).count()
        total_questions = questions.count()

        score_percent = 0.0
        if max_points > 0:
            score_percent = (earned_points / max_points) * 100.0

        attempt.score = score_percent
        attempt.finished_at = timezone.now()
        attempt.save(update_fields=["score", "finished_at"])

        now = timezone.now()
        for ans in answers_qs:
            q = ans.question
            stats, _ = QuestionStats.objects.get_or_create(
                enrollment=enrollment,
                question=q,
            )
            stats.attempts_count = F("attempts_count") + 1
            if ans.is_correct:
                stats.correct_count = F("correct_count") + 1
            stats.last_attempt_at = now
            stats.save(update_fields=["attempts_count", "correct_count", "last_attempt_at"])

        stats_qs = QuestionStats.objects.filter(
            enrollment=enrollment, question_id__in=question_ids
        )
        stats_qs.update(
            success_rate=100.0 * F("correct_count") / NullIf(F("attempts_count"), 0)
        )

        # Все юниты внутри секции, по которым есть вопросы в этой попытке.
        unit_ids = questions.values_list("unit_id", flat=True).distinct()

        unit_progress_payload = []
        for unit in Unit.objects.filter(id__in=unit_ids).select_related("section"):
            total_q_in_unit = Question.objects.filter(unit=unit).count()
            if total_q_in_unit == 0:
                progress_percent = 0.0
            else:
                correct_count_in_unit = (
                    Answer.objects.filter(
                        attempt__enrollment=enrollment,
                        question__unit=unit,
                        is_correct=True,
                    )
                    .values("question_id")
                    .distinct()
                    .count()
                )
                progress_percent = (correct_count_in_unit / total_q_in_unit) * 100.0

            unit_progress_obj, _ = UnitProgress.objects.get_or_create(
                enrollment=enrollment,
                unit=unit,
            )
            unit_progress_obj.progress_percent = progress_percent
            unit_progress_obj.completed = progress_percent >= 99.9
            unit_progress_obj.save(update_fields=["progress_percent", "completed"])

            unit_progress_payload.append(
                {
                    "unit_id": unit.id,
                    "section_id": unit.section_id,
                    "progress_percent": progress_percent,
                    "completed": unit_progress_obj.completed,
                }
            )

        section_progress_payload = []
        sections = {u.section for u in Unit.objects.filter(id__in=unit_ids).select_related("section")}
        for section in sections:
            unit_progress_qs = UnitProgress.objects.filter(
                enrollment=enrollment,
                unit__section=section,
            )
            if not unit_progress_qs.exists():
                progress_percent = 0.0
                completed = False
            else:
                agg = unit_progress_qs.aggregate(
                    avg_progress=Sum("progress_percent") / Count("id"),
                )
                progress_percent = float(agg["avg_progress"] or 0.0)
                completed = unit_progress_qs.filter(completed=True).count() == unit_progress_qs.count()

            section_progress_obj, _ = SectionProgress.objects.get_or_create(
                enrollment=enrollment,
                section=section,
            )
            section_progress_obj.progress_percent = progress_percent
            section_progress_obj.completed = completed
            section_progress_obj.save(update_fields=["progress_percent", "completed"])

            section_progress_payload.append(
                {
                    "section_id": section.id,
                    "progress_percent": progress_percent,
                    "completed": completed,
                }
            )

        return Response(
            {
                "attempt_id": attempt.id,
                "score_percent": score_percent,
                "correct_count": correct_count,
                "total_questions": total_questions,
                "earned_points": earned_points,
                "max_points": max_points,
                "unit_progress": unit_progress_payload,
                "section_progress": section_progress_payload,
            },
            status=status.HTTP_200_OK,
        )


class PlanDocumentUploadView(APIView):
    """Upload a source document file for a plan."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, plan_id, *args, **kwargs):
        plan = get_object_or_404(Plan, id=plan_id, owner=request.user)
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response(
                {"detail": "file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Ensure directory exists
        documents_dir = os.path.join(settings.BASE_DIR, "media", "documents")
        os.makedirs(documents_dir, exist_ok=True)

        filename = uploaded_file.name
        # Simple unique filename
        unique_name = f"{plan.id}_{filename}"
        file_path = os.path.join(documents_dir, unique_name)

        with open(file_path, "wb+") as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        rel_path = os.path.relpath(file_path, settings.BASE_DIR)

        doc = Document.objects.create(
            owner=request.user,
            plan=plan,
            file_path=rel_path,
            original_name=filename,
            file_size=uploaded_file.size,
            index_status=Document.IndexStatus.PROCESSING,
            topics_status=Document.TopicsStatus.IDLE,
            extracted_topics=[],
            extracted_outline=[],
        )
        index_document_task.delay(doc.id)

        return Response(
            {
                "id": doc.id,
                "original_name": doc.original_name,
                "file_path": doc.file_path,
                "file_size": doc.file_size,
                "index_status": doc.index_status,
                "topics_status": doc.topics_status,
            },
            status=status.HTTP_201_CREATED,
        )


class AiChatView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        unit_id = request.data.get("unit_id")
        question_id = request.data.get("question_id")
        message = (request.data.get("message") or "").strip()
        history = request.data.get("history") or []

        if not unit_id or not message:
            return Response(
                {"detail": "unit_id and message are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        unit = get_object_or_404(
            Unit.objects.select_related("section__plan"),
            id=unit_id,
        )
        plan = unit.section.plan
        is_owner = plan.owner == request.user
        is_enrolled = Enrollment.objects.filter(
            plan=plan, user=request.user
        ).exists()
        if not is_owner and not is_enrolled:
            return Response(
                {"detail": "Access denied."},
                status=status.HTTP_403_FORBIDDEN,
            )

        question_context = ""
        if question_id:
            question = Question.objects.filter(
                id=question_id, unit=unit
            ).first()
            if question:
                question_context = (
                    f"\n\nSTUDENT IS ASKING ABOUT THIS QUESTION:\n"
                    f"Question text: {question.text}\n"
                    f"Question type: {question.type}\n"
                )
                if question.type in {
                    Question.QuestionType.SINGLE_CHOICE,
                    Question.QuestionType.MULTIPLE_CHOICE,
                }:
                    choices = question.choices.all().order_by("order")
                    choices_text = "\n".join(
                        f"  - {c.text}" for c in choices
                    )
                    question_context += f"Answer options:\n{choices_text}\n"

        system_prompt = (
            "You are a friendly and patient tutor helping a student who is learning. "
            "You have the unit theory as context. "
            "Your goal is to help the student understand the material, NOT to give direct answers. "
            "Instead:\n"
            "- Explain concepts in simpler terms if the student is confused.\n"
            "- Give hints and guide them toward the correct answer step by step.\n"
            "- If the student asks for help with a specific question, "
            "explain the relevant theory and give a gentle hint, "
            "but do NOT reveal the exact answer unless explicitly asked.\n"
            "- You can use your own knowledge to provide simpler analogies or examples "
            "beyond the provided theory if it helps the student understand.\n"
            "- Be concise but thorough. Plain text only — do not use markdown (no **bold**, no # headings).\n\n"
            f"UNIT THEORY:\n{unit.theory}\n"
            f"{question_context}"
        )

        messages = [{"role": "system", "content": system_prompt}]
        for h in history[-20:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})

        try:
            llm = LLMClient()
            resp = llm._client.chat.completions.create(
                model=llm.model_name,
                messages=messages,
                temperature=0.5,
                max_tokens=1024,
            )
            reply = strip_light_markdown_for_ui(resp.choices[0].message.content or "")
        except Exception as exc:
            return Response(
                {"detail": f"AI error: {str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        AiChatMessage.objects.create(
            user=request.user,
            plan=unit.section.plan,
            unit=unit,
            question_id=question_id,
            role=AiChatMessage.Role.USER,
            content=message,
        )
        AiChatMessage.objects.create(
            user=request.user,
            plan=unit.section.plan,
            unit=unit,
            question_id=question_id,
            role=AiChatMessage.Role.ASSISTANT,
            content=reply,
        )

        return Response(
            {"reply": reply},
            status=status.HTTP_200_OK,
        )


LANDING_SYSTEM_PROMPT = (
    "You are the AI assistant for Smart Knowledge Hub — an educational platform.\n\n"
    "HOW THE PLATFORM WORKS:\n"
    "1. UPLOAD — The user uploads a study document (PDF, DOCX, TXT) on the main page or the Materials page.\n"
    "2. MATERIALS — All uploaded documents appear on the 'Materials' page. The user can manage them there.\n"
    "3. CREATE A PLAN — The user goes to 'Plans' → 'Create Plan', gives it a title, description, "
    "and learning goals, then attaches one or more documents from their library.\n"
    "4. GENERATE — The system uses AI + RAG to analyze the documents and automatically generates "
    "a structured course: Sections → Units → Theory + Questions (single choice, multiple choice, open text, code).\n"
    "5. STUDY — The user opens a plan, navigates units in the left sidebar, reads the theory, and answers questions.\n"
    "6. SUBMIT — At the bottom of each unit there is a 'Submit answers' button. "
    "After submitting, the user sees their score and whether they passed.\n"
    "7. RETRY — If the user didn't pass, they can click 'Retry unit' to try again.\n"
    "8. PROGRESS — Progress bars in the sidebar show plan-level and unit-level completion. "
    "Only correctly answered questions count toward progress.\n"
    "9. AI TUTOR — On each unit page there is an AI chat panel on the right side. "
    "The user can ask questions about the theory or click the lightbulb icon next to any question "
    "to get targeted AI help (hints, not direct answers).\n\n"
    "GENERAL RULES:\n"
    "- Be friendly, concise, and helpful.\n"
    "- Answer questions about how to use the platform.\n"
    "- If the user asks something unrelated to the platform, politely redirect them.\n"
    "- Plain text only in answers — no markdown (no ** or #).\n"
    "- Answer in the same language the user writes in."
)


class LandingChatView(APIView):
    authentication_classes = ()
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        message = (request.data.get("message") or "").strip()
        history = request.data.get("history") or []

        if not message:
            return Response(
                {"detail": "message is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        messages = [{"role": "system", "content": LANDING_SYSTEM_PROMPT}]
        for h in history[-20:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})

        try:
            llm = LLMClient()
            resp = llm._client.chat.completions.create(
                model=llm.model_name,
                messages=messages,
                temperature=0.5,
                max_tokens=1024,
            )
            reply = strip_light_markdown_for_ui(resp.choices[0].message.content or "")
        except Exception as exc:
            return Response(
                {"detail": f"AI error: {str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"reply": reply}, status=status.HTTP_200_OK)


class PreplanChatView(APIView):
    """
    Pre-plan assistant chat:
    takes selected document ids (owned by user), builds a short context,
    and asks LLM to (1) list topics, (2) ask clarifying questions, (3) propose suggested goals.
    """

    permission_classes = [permissions.IsAuthenticated]

    # Single-root wrappers from LLM/TOC — not real "chapters" for exact-topic listing.
    _TOC_WRAPPER_TITLES = frozenset(
        {
            "оглавление",
            "table of contents",
            "contents",
            "содержание",
            "content",
            "toc",
        }
    )

    @staticmethod
    def _extract_page_num(text: str) -> int | None:
        if not text:
            return None
        # Prefer page-like number near line end (typical TOC format).
        matches = re.findall(r"(\d{1,4})\s*$", text.strip())
        if matches:
            try:
                return int(matches[-1])
            except ValueError:
                return None
        return None

    @staticmethod
    def _clean_topic_text(text: str) -> str:
        if not text:
            return ""
        s = str(text)
        # Remove common markdown/OCR artifacts.
        s = s.replace("**", "")
        s = re.sub(r"[_]{2,}", " ", s)
        s = re.sub(r"[.]{3,}", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        # Normalize spaced hyphen artifacts from OCR, e.g. "СЕТКИ -РАБИЦЫ".
        s = re.sub(r"\s+-\s*", "-", s)
        return s

    @staticmethod
    def _normalize_exact_topics(raw_topics):
        if not isinstance(raw_topics, list):
            return []
        normalized = []
        seen = set()
        for item in raw_topics:
            if not isinstance(item, dict):
                continue
            title = PreplanChatView._clean_topic_text(item.get("title") or "")
            if not title:
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)

            page = item.get("page")
            if isinstance(page, int):
                normalized_page = page
            else:
                normalized_page = (
                    PreplanChatView._extract_page_num(title)
                )
            normalized.append(
                {
                    "title": title,
                    "page": normalized_page,
                }
            )
        return normalized

    @staticmethod
    def _build_exact_topics_fallback(data: dict) -> list[dict]:
        """
        Build exact_topics fallback when model omitted exact_topics field.
        Uses topics list first, then tries to parse numbered lines from reply.
        """
        raw_topics = data.get("topics") or []
        result = []
        seen = set()

        if isinstance(raw_topics, list):
            for t in raw_topics:
                title = PreplanChatView._clean_topic_text(t)
                if not title:
                    continue
                key = title.lower()
                if key in seen:
                    continue
                seen.add(key)
                result.append({"title": title, "page": PreplanChatView._extract_page_num(title)})

        if result:
            return result

        reply = str(data.get("reply") or "")
        for line in reply.splitlines():
            line = PreplanChatView._clean_topic_text(line)
            if not line:
                continue
            if re.match(r"^\d+\.\s+", line) or re.match(r"^[ivxlcdm]+\.\s+", line, flags=re.IGNORECASE):
                key = line.lower()
                if key in seen:
                    continue
                seen.add(key)
                result.append({"title": line, "page": PreplanChatView._extract_page_num(line)})
        return result

    @staticmethod
    def _history_has_exact_topics(history) -> bool:
        if not isinstance(history, list):
            return False
        for h in history[-20:]:
            content = str(h.get("content") or "")
            if "Exact topics from sources" in content:
                return True
        return False

    @staticmethod
    def _route_preplan_mode(llm: LLMClient, message: str, history, requested_mode: str) -> str:
        """
        LLM router: exact (TOC-like listing from sources) vs semantic (goals / discussion).
        Subtopics drill-down intentionally disabled — only main themes are used in exact mode.
        """
        route = llm.complete_json(
            "You are an intent router for a pre-plan study assistant. "
            "Return ONLY JSON with key: mode. "
            "mode must be exactly 'exact' or 'semantic'. "
            "Choose mode='exact' if the user asks to list topics from the materials, table of contents, "
            "chapter/section headings as in the book, or continues in that same extraction thread. "
            "Choose mode='semantic' for general chat, clarifying learning goals, or questions not focused "
            "on verbatim topic listing. "
            "Do not switch to exact just because the user says 'да' or a number — use recent history.",
            (
                f"Requested mode from client: {requested_mode}\n\n"
                f"User message:\n{message}\n\n"
                f"Recent history (last up to 10 turns):\n{json.dumps(history[-10:] if isinstance(history, list) else [], ensure_ascii=False)}"
            ),
        )
        if requested_mode in {"exact", "semantic"}:
            mode = requested_mode
        else:
            mode = str(route.get("mode") or "semantic").strip().lower()
            if mode not in {"semantic", "exact"}:
                mode = "semantic"
        return mode

    @staticmethod
    def _build_exact_context_from_document_start(
        docs: list[Document],
        max_total_chars: int = 80000,
        per_doc_cap: int = 30000,
    ) -> str:
        """
        Build context from the beginning of documents (format-agnostic strategy).
        Same logic for PDF/DOCX/TXT/MD: use extracted plain text and take the start.
        """
        parts = []
        total = 0

        for doc in docs:
            block = ""

            try:
                text = _load_document_text(doc) or ""
                if text:
                    block = f"[doc: {doc.original_name}]\n{text[:per_doc_cap]}"
            except Exception:
                block = ""

            if not block:
                continue
            if total + len(block) > max_total_chars:
                break
            parts.append(block)
            total += len(block)

        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _merge_outline_node_recursive(node: dict) -> dict | None:
        """Recursive outline branch: supports 3+ levels (subtopics under subtopics)."""
        title = PreplanChatView._clean_topic_text(node.get("title") or "")
        if not title:
            return None
        subs_out = []
        for sub in node.get("subtopics") or []:
            if not isinstance(sub, dict):
                continue
            merged = PreplanChatView._merge_outline_node_recursive(sub)
            if merged:
                subs_out.append(merged)
        return {
            "title": title,
            "page": node.get("page") if isinstance(node.get("page"), int) else None,
            "subtopics": subs_out,
        }

    @staticmethod
    def _build_combined_outline(docs: list[Document]) -> list[dict]:
        combined = []
        seen = set()
        for doc in docs:
            outline = doc.extracted_outline or []
            if not isinstance(outline, list):
                continue
            for node in outline:
                if not isinstance(node, dict):
                    continue
                title = PreplanChatView._clean_topic_text(node.get("title") or "")
                if not title:
                    continue
                key = title.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged = PreplanChatView._merge_outline_node_recursive(node)
                if merged:
                    combined.append(merged)
        return combined

    @staticmethod
    def _unwrap_toc_root_outline(outline: list[dict]) -> list[dict]:
        """
        If the outline is a single synthetic TOC node (e.g. «Оглавление»), expose its
        children as the real top level so exact-mode lists match user expectations.
        """
        current = outline
        guard = 0
        while len(current) == 1 and guard < 8:
            guard += 1
            node = current[0]
            if not isinstance(node, dict):
                break
            title = PreplanChatView._clean_topic_text(node.get("title") or "").strip().lower()
            if title not in PreplanChatView._TOC_WRAPPER_TITLES:
                break
            subs = node.get("subtopics") or []
            if not subs:
                break
            next_outline: list[dict] = []
            for s in subs:
                if not isinstance(s, dict):
                    continue
                merged = PreplanChatView._merge_outline_node_recursive(s)
                if merged:
                    next_outline.append(merged)
            if not next_outline:
                break
            current = next_outline
        return current

    @staticmethod
    def _outline_from_flat_extracted_topics(docs: list[Document]) -> list[dict]:
        """When extracted_outline is empty but Celery already filled extracted_topics."""
        combined: list[dict] = []
        seen: set[str] = set()
        for doc in docs:
            topics = doc.extracted_topics or []
            if not isinstance(topics, list):
                continue
            for t in topics:
                title = PreplanChatView._clean_topic_text(str(t or ""))
                if not title:
                    continue
                key = title.lower()
                if key in seen:
                    continue
                seen.add(key)
                combined.append({"title": title, "page": None, "subtopics": []})
        return combined

    def post(self, request, *args, **kwargs):
        document_ids = request.data.get("document_ids") or []
        message = (request.data.get("message") or "").strip()
        history = request.data.get("history") or []
        requested_mode = (request.data.get("mode") or "auto").strip().lower()

        if not isinstance(document_ids, list) or not document_ids:
            return Response(
                {"detail": "document_ids (non-empty list) is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not message:
            return Response(
                {"detail": "message is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if requested_mode not in {"semantic", "exact", "auto"}:
            return Response(
                {"detail": "mode must be 'semantic', 'exact' or 'auto'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            llm = LLMClient()
        except Exception as exc:
            return Response(
                {"detail": f"AI is not configured: {str(exc)}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Centralized routing via LLM for all client modes (auto/semantic/exact).
        try:
            mode = self._route_preplan_mode(
                llm=llm,
                message=message,
                history=history,
                requested_mode=requested_mode,
            )
        except Exception:
            if requested_mode in {"semantic", "exact"}:
                mode = requested_mode
            else:
                mode = "exact" if self._history_has_exact_topics(history) else "semantic"

        docs = list(
            Document.objects.filter(id__in=document_ids, owner=request.user).order_by("id")
        )
        if not docs:
            return Response(
                {"detail": "No accessible documents found for provided document_ids."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Ensure documents are indexed asynchronously.
        # If some documents are not ready yet, queue indexing and return progress state.
        missing = [d for d in docs if d.index_status != Document.IndexStatus.READY or not d.doc_chunks.exists()]
        if missing:
            for d in missing:
                if d.index_status != Document.IndexStatus.PROCESSING:
                    d.index_status = Document.IndexStatus.PENDING
                    d.index_error = ""
                    d.save(update_fields=["index_status", "index_error"])
                    index_document_task.delay(d.id)
            return Response(
                {
                    "reply": "Идет обработка материалов. Попробуйте снова через несколько секунд.",
                    "suggested_goals": "",
                    "topics": [],
                    "questions": [],
                    "exact_topics": [],
                    "truncated": False,
                    "mode": mode,
                    "processing": True,
                    "documents_status": [
                        {
                            "id": d.id,
                            "original_name": d.original_name,
                            "index_status": d.index_status,
                            "topics_status": d.topics_status,
                        }
                        for d in docs
                    ],
                },
                status=status.HTTP_200_OK,
            )

        if mode == "exact":
            # Ensure topics extraction is running/completed in background.
            not_ready_topics = []
            for d in docs:
                if d.topics_status == Document.TopicsStatus.IDLE:
                    d.topics_status = Document.TopicsStatus.PROCESSING
                    d.topics_error = ""
                    d.save(update_fields=["topics_status", "topics_error"])
                    extract_document_topics_task.delay(d.id)
                    not_ready_topics.append(d)
                elif d.topics_status == Document.TopicsStatus.PROCESSING:
                    not_ready_topics.append(d)
            if not_ready_topics:
                return Response(
                    {
                        "reply": "Идет извлечение тем. Попробуйте снова через несколько секунд.",
                        "suggested_goals": "",
                        "topics": [],
                        "questions": [],
                        "exact_topics": [],
                        "truncated": False,
                        "mode": mode,
                        "processing": True,
                        "documents_status": [
                            {
                                "id": d.id,
                                "original_name": d.original_name,
                                "index_status": d.index_status,
                                "topics_status": d.topics_status,
                            }
                            for d in docs
                        ],
                    },
                    status=status.HTTP_200_OK,
                )

            combined_outline = self._build_combined_outline(docs)
            combined_outline = self._unwrap_toc_root_outline(combined_outline)
            if not combined_outline:
                combined_outline = self._outline_from_flat_extracted_topics(docs)
            if combined_outline:
                return Response(
                    {
                        "reply": (
                            "Вот основные темы из материалов (верхний уровень оглавления). "
                            "Порядок в списке — сверху вниз; он может не совпадать с номером главы в книге."
                        ),
                        "suggested_goals": "",
                        "topics": [n["title"] for n in combined_outline],
                        "questions": [],
                        "exact_topics": [{"title": n["title"], "page": n.get("page")} for n in combined_outline],
                        "truncated": False,
                        "mode": mode,
                    },
                    status=status.HTTP_200_OK,
                )

        rag = DocumentRAGService()
        try:
            if mode == "exact":
                # Prefer deterministic "start of book" extraction for TOC-like requests.
                context = self._build_exact_context_from_document_start(
                    docs,
                    max_total_chars=22000,
                    per_doc_cap=9000,
                )
                # Fallback to vector RAG only if start-of-document extraction is empty.
                if not context:
                    context = rag.build_context(
                        docs,
                        query=message,
                        top_k=35,
                        max_total_chars=18000,
                    )
            else:
                context = rag.build_context(docs, query=message, top_k=30, max_total_chars=16000)
        except Exception:
            # Fallback until migrations/embeddings are fully available.
            # Keeps pre-plan flow working even if doc-level vector chunks are not ready.
            parts = []
            total = 0
            if mode == "exact":
                per_doc_cap = 4500
                max_total_chars = 18000
            else:
                per_doc_cap = 4000
                max_total_chars = 16000
            for doc in docs:
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
            return Response(
                {"detail": "No indexed chunks available for selected documents."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if mode == "exact":
            exact_scope_rules = (
                "- Return ONLY top-level themes/sections (main headings).\n"
                "- Do NOT include nested subtopics or subsections.\n"
                "- In 'reply', briefly confirm you listed main headings only — do NOT ask about subtopics.\n"
            )
            system_prompt = (
                "You are a precise document analyst.\n"
                "You will receive excerpts from selected study materials.\n"
                "Extract topics EXACTLY as they appear in the materials (section/chapter names, headings, explicit topic phrases).\n\n"
                "Rules:\n"
                "- Do NOT paraphrase topic names.\n"
                "- Do NOT invent topics that are not explicitly present.\n"
                f"{exact_scope_rules}"
                "- Keep the response concise.\n"
                "- If a topic is uncertain, skip it.\n"
                "- If page numbers are not available in context, set page to null.\n"
                "- Reply in the same language as the user.\n\n"
                "Return ONLY valid JSON with keys:\n"
                "- reply: string (short plain-text answer, no markdown)\n"
                "- suggested_goals: string (can be empty string)\n"
                "- topics: array of strings (exact topic names from source)\n"
                "- questions: array of strings (keep empty array)\n"
                "- truncated: boolean (true if output had to be shortened)\n"
                "- exact_topics: array of objects with keys: title (string), page (number|null)\n\n"
                f"Materials excerpts (retrieved):\n{context}\n"
            )
        else:
            system_prompt = (
                "You are an expert instructional designer and tutor.\n"
                "You will receive excerpts from the user's selected study documents.\n"
                "Your job is to help the user clarify what they want to learn and produce a high-quality 'learning goals' text.\n\n"
                "Rules:\n"
                "- First, list the main topics you can confidently identify from the materials.\n"
                "- Then ask 3-7 clarifying questions to refine scope, level, and priorities.\n"
                "- Then propose 'suggested_goals' as a concise paragraph (or bullet list) the user can paste into the plan form.\n"
                "- If the user asks something outside the provided materials, say it and propose how to proceed.\n"
                "- Reply in the same language as the user.\n\n"
                "Return ONLY valid JSON with keys:\n"
                "- reply: string (your full answer as plain text, no markdown)\n"
                "- suggested_goals: string (clean text the user can paste)\n"
                "- topics: array of strings\n"
                "- questions: array of strings\n\n"
                f"Materials excerpts (retrieved):\n{context}\n"
            )

        # Convert chat history to OpenAI format
        messages = [{"role": "system", "content": system_prompt}]
        for h in history[-20:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})

        # llm already initialized above (used by router and generation).

        try:
            # Prefer JSON response format when supported
            resp = llm._client.chat.completions.create(
                model=llm.model_name,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1300 if mode == "exact" else 1200,
            )
            content = resp.choices[0].message.content or "{}"
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # Some providers occasionally return malformed JSON despite json_object mode.
                repair_system = (
                    "You repair malformed JSON. "
                    "Return ONLY valid JSON object, no markdown/comments."
                )
                repair_user = (
                    "Repair this malformed JSON while preserving meaning and keys when possible:\n\n"
                    f"{content}"
                )
                data = llm.complete_json(repair_system, repair_user)
            if not isinstance(data, dict):
                raise ValueError("LLM returned non-object JSON.")
            exact_topics = self._normalize_exact_topics(data.get("exact_topics") or [])
            if mode == "exact" and not exact_topics:
                exact_topics = self._normalize_exact_topics(self._build_exact_topics_fallback(data))
            if mode == "exact":
                Document.objects.filter(id__in=[d.id for d in docs]).update(
                    topics_status=Document.TopicsStatus.READY,
                    topics_error="",
                )
            raw_topics = data.get("topics") or []
            if isinstance(raw_topics, list):
                topics_plain = [strip_light_markdown_for_ui(str(t)) for t in raw_topics]
            else:
                topics_plain = []
            raw_qs = data.get("questions") or []
            if isinstance(raw_qs, list):
                questions_plain = [strip_light_markdown_for_ui(str(t)) for t in raw_qs]
            else:
                questions_plain = []
            return Response(
                {
                    "reply": strip_light_markdown_for_ui(str(data.get("reply") or "")),
                    "suggested_goals": strip_light_markdown_for_ui(str(data.get("suggested_goals") or "")),
                    "topics": topics_plain,
                    "questions": questions_plain,
                    "exact_topics": exact_topics,
                    "truncated": bool(data.get("truncated", False)),
                    "mode": mode,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            if mode == "exact":
                Document.objects.filter(id__in=[d.id for d in docs]).update(
                    topics_status=Document.TopicsStatus.FAILED,
                    topics_error=str(exc)[:2000],
                )
            return Response(
                {"detail": f"AI error: {str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

