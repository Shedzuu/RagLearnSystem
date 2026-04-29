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
        Follow-up drill-down (subtopics) is handled later via fast-path skip + LLM/RAG or stored subtopics.
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

    @staticmethod
    def _user_requests_subtopics_drilldown(message: str) -> bool:
        """User asks for subsections / nested headings under a chapter or topic number."""
        m = (message or "").strip().lower()
        if not m:
            return False
        markers = (
            "подтем",
            "под тем",
            "под топ",
            "подтопик",
            "подраздел",
            "подразд",
            "сабтопик",
            "subtopic",
            "subsection",
            "дочерн",
            "вложен",
            "детализ",
            "раскрой",
            "раскрыть",
            "внутр",
            "что входит",
            "содержание глав",
            "состав глав",
            "пункты ",
            "подпункт",
            "нижн уров",
            "детальн список",
        )
        if any(x in m for x in markers):
            return True
        if re.search(
            r"(?:тем\w*|глав\w*|раздел\w*|пункт\w*|chapter|section)\s*[№#]?\s*\d+",
            m,
            flags=re.IGNORECASE,
        ):
            return True
        if re.search(r"\b#\s*\d+\b", m):
            return True
        return False

    @staticmethod
    def _exact_top_level_outline_already_sent(history) -> bool:
        if not isinstance(history, list):
            return False
        for h in history:
            if h.get("role") != "assistant":
                continue
            c = str(h.get("content") or "").lower()
            if "верхний уровень оглавления" in c:
                return True
            if "exact topics from sources" in c:
                return True
        return False

    @staticmethod
    def _exact_outline_fast_path_ok(message: str, history) -> bool:
        """
        First shot: return stored top-level outline only once.
        Follow-ups (subtopics, «тема 2», etc.) must go to LLM / stored children.
        """
        if PreplanChatView._user_requests_subtopics_drilldown(message):
            return False
        if PreplanChatView._exact_top_level_outline_already_sent(history):
            return False
        return True

    @staticmethod
    def _parse_section_index_from_message(message: str) -> int | None:
        """1-based index from «тема 2», «глава 3», etc. Returns None if not found."""
        m = (message or "").strip().lower()
        ma = re.search(
            r"(?:тем\w*|глав\w*|раздел\w*|пункт\w*|chapter|section)\s*[№#]?\s*(\d{1,3})\b",
            m,
            flags=re.IGNORECASE,
        )
        if ma:
            return int(ma.group(1))
        ma = re.search(r"\b#\s*(\d{1,3})\b", m)
        if ma:
            return int(ma.group(1))
        return None

    @staticmethod
    def _try_stored_subtopics_for_section(
        combined_outline: list[dict], message: str
    ) -> tuple[list[dict], str] | None:
        """
        If outline nodes have subtopics and user points to section N, return flat exact_topics.
        Returns (exact_topics_list, reply_text) or None to fall back to LLM.
        """
        if not combined_outline or not PreplanChatView._user_requests_subtopics_drilldown(message):
            return None
        idx_1 = PreplanChatView._parse_section_index_from_message(message)
        if idx_1 is None or idx_1 < 1 or idx_1 > len(combined_outline):
            return None
        node = combined_outline[idx_1 - 1]
        if not isinstance(node, dict):
            return None
        title = PreplanChatView._clean_topic_text(node.get("title") or "")
        raw_children = node.get("subtopics") or []
        if not raw_children:
            return None
        out: list[dict] = []
        for ch in raw_children:
            if not isinstance(ch, dict):
                continue
            ct = PreplanChatView._clean_topic_text(ch.get("title") or "")
            if not ct:
                continue
            pg = ch.get("page") if isinstance(ch.get("page"), int) else None
            out.append({"title": ct, "page": pg})
        if not out:
            return None
        reply = (
            f"Подтемы для «{title}» из сохранённого оглавления (как в документе). "
            "Если списка мало — в исходном извлечении не было вложенности; тогда нужен второй проход по тексту."
        )
        return (out, reply)

    @staticmethod
    def _coerce_preplan_json_payload(data) -> dict:
        """Some providers return a list or scalar; normalize to the expected object shape."""
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            if not data:
                return {"reply": "", "suggested_goals": "", "topics": [], "questions": []}
            if all(isinstance(x, str) for x in data):
                return {"reply": "", "suggested_goals": "", "topics": data, "questions": []}
            if all(isinstance(x, dict) for x in data):
                merged: dict = {}
                for item in data:
                    merged.update(item)
                if merged:
                    return merged
            try:
                blob = json.dumps(data, ensure_ascii=False)
            except (TypeError, ValueError):
                blob = str(data)
            return {"reply": blob, "suggested_goals": "", "topics": [], "questions": []}
        if isinstance(data, bool):
            return {
                "reply": "да" if data else "нет",
                "suggested_goals": "",
                "topics": [],
                "questions": [],
            }
        if isinstance(data, (int, float)):
            # Top-level number from provider — not a valid preplan object; avoid showing raw floats in UI.
            return {"reply": "", "suggested_goals": "", "topics": [], "questions": []}
        return {
            "reply": strip_light_markdown_for_ui(str(data)),
            "suggested_goals": "",
            "topics": [],
            "questions": [],
        }

    @staticmethod
    def _preplan_json_string_field(val) -> str:
        """
        LLM sometimes returns numbers/bools in 'reply' or 'suggested_goals'; never stringify floats for display.
        """
        if val is None:
            return ""
        if isinstance(val, str):
            return strip_light_markdown_for_ui(val)
        if isinstance(val, bool):
            return "да" if val else "нет"
        if isinstance(val, (int, float)):
            return ""
        if isinstance(val, (dict, list)):
            try:
                return strip_light_markdown_for_ui(json.dumps(val, ensure_ascii=False))
            except (TypeError, ValueError):
                return strip_light_markdown_for_ui(str(val))
        return strip_light_markdown_for_ui(str(val))

    @staticmethod
    def _preplan_reply_fallback_if_bad_numeric(data: dict, reply_text: str) -> str:
        if reply_text.strip():
            return reply_text
        raw = data.get("reply")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return (
                "Модель вернула число вместо текста в поле ответа (ошибка формата JSON). "
                "Повторите вопрос одной фразой, например: «Что в разделе 6 про классы, атрибуты и методы?»"
            )
        return reply_text

    def post(self, request, *args, **kwargs):
        raw_doc_ids = request.data.get("document_ids")
        if raw_doc_ids is None:
            raw_doc_ids = []
        if not isinstance(raw_doc_ids, list):
            return Response(
                {"detail": "document_ids must be a list (may be empty)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        document_ids: list[int] = []
        for x in raw_doc_ids:
            try:
                document_ids.append(int(x))
            except (TypeError, ValueError):
                continue
        message = (request.data.get("message") or "").strip()
        history = request.data.get("history") or []
        requested_mode = (request.data.get("mode") or "auto").strip().lower()
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

        # No materials: still help with goals from form fields (title, description, draft).
        if not document_ids:
            mode = "semantic"
            plan_title = (request.data.get("plan_title") or "").strip()
            plan_description = (request.data.get("plan_description") or "").strip()
            goals_draft = (request.data.get("goals_draft") or "").strip()
            form_context = (
                f"Plan title: {plan_title or 'N/A'}\n"
                f"Plan description: {plan_description or 'N/A'}\n"
                f"Current learning goals draft: {goals_draft or 'N/A'}\n"
            )
            system_prompt = (
                "You are an expert instructional designer and tutor.\n"
                "The user is creating a study plan but has not selected attached documents in this step.\n"
                "Help them write clear learning goals using ONLY the plan title, description, and goals draft below.\n"
                "Do not claim you read a book or document; infer broad topic areas only from the title/description.\n\n"
                "Rules:\n"
                "- List plausible topic areas inferred from the title/description.\n"
                "- Ask 3-7 clarifying questions (level, scope, priorities, time, prerequisites).\n"
                "- Propose 'suggested_goals' as concise text the user can paste into a form.\n"
                "- Reply in the same language as the user.\n\n"
                "Return ONLY valid JSON with keys:\n"
                "- reply: string (plain text, no markdown)\n"
                "- suggested_goals: string\n"
                "- topics: array of strings\n"
                "- questions: array of strings\n"
                "- IMPORTANT: 'reply' and 'suggested_goals' must be JSON strings (quoted), never bare numbers.\n\n"
                f"Form context:\n{form_context}\n"
            )
            messages = [{"role": "system", "content": system_prompt}]
            for h in history[-20:]:
                role = h.get("role", "user")
                content = h.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": message})
            try:
                resp = llm._client.chat.completions.create(
                    model=llm.model_name,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.3,
                    max_tokens=1200,
                )
                content = resp.choices[0].message.content or "{}"
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    repair_system = (
                        "You repair malformed JSON. "
                        "Return ONLY valid JSON object, no markdown/comments."
                    )
                    repair_user = (
                        "Repair this malformed JSON while preserving meaning and keys when possible:\n\n"
                        f"{content}"
                    )
                    data = llm.complete_json(repair_system, repair_user)
                data = self._coerce_preplan_json_payload(data)
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
                reply_out = PreplanChatView._preplan_reply_fallback_if_bad_numeric(
                    data,
                    PreplanChatView._preplan_json_string_field(data.get("reply")),
                )
                goals_out = PreplanChatView._preplan_json_string_field(data.get("suggested_goals"))
                return Response(
                    {
                        "reply": reply_out,
                        "suggested_goals": goals_out,
                        "topics": topics_plain,
                        "questions": questions_plain,
                        "exact_topics": [],
                        "truncated": bool(data.get("truncated", False)),
                        "mode": mode,
                    },
                    status=status.HTTP_200_OK,
                )
            except Exception as exc:
                return Response(
                    {"detail": f"AI error: {str(exc)}"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

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

            if combined_outline and self._exact_outline_fast_path_ok(message, history):
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

            if combined_outline and self._user_requests_subtopics_drilldown(message):
                stored_sub = self._try_stored_subtopics_for_section(combined_outline, message)
                if stored_sub is not None:
                    sub_list, sub_reply = stored_sub
                    return Response(
                        {
                            "reply": sub_reply,
                            "suggested_goals": "",
                            "topics": [x["title"] for x in sub_list],
                            "questions": [],
                            "exact_topics": sub_list,
                            "truncated": False,
                            "mode": mode,
                        },
                        status=status.HTTP_200_OK,
                    )

        exact_drilldown = mode == "exact" and not self._exact_outline_fast_path_ok(message, history)

        outline_for_drill_query: list[dict] = []
        if mode == "exact" and exact_drilldown:
            outline_for_drill_query = self._unwrap_toc_root_outline(self._build_combined_outline(docs))
            if not outline_for_drill_query:
                outline_for_drill_query = self._outline_from_flat_extracted_topics(docs)

        rag = DocumentRAGService()
        try:
            if mode == "exact":
                if exact_drilldown:
                    rag_query = message
                    sec_idx = self._parse_section_index_from_message(message)
                    if (
                        sec_idx is not None
                        and 1 <= sec_idx <= len(outline_for_drill_query)
                    ):
                        parent_title = PreplanChatView._clean_topic_text(
                            outline_for_drill_query[sec_idx - 1].get("title") or ""
                        )
                        if parent_title:
                            rag_query = (
                                f"{message}\n\n"
                                f"Section from book outline (use this to find subheadings in the source): {parent_title}"
                            )
                    context = rag.build_context(
                        docs,
                        query=rag_query,
                        top_k=42,
                        max_total_chars=24000,
                    )
                    if not context:
                        context = self._build_exact_context_from_document_start(
                            docs,
                            max_total_chars=28000,
                            per_doc_cap=12000,
                        )
                else:
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
                context = rag.build_context(
                    docs,
                    query=message,
                    top_k=40,
                    max_total_chars=24000,
                )
        except Exception:
            # Fallback until migrations/embeddings are fully available.
            # Keeps pre-plan flow working even if doc-level vector chunks are not ready.
            parts = []
            total = 0
            if mode == "exact":
                per_doc_cap = 4500
                max_total_chars = 18000
            else:
                per_doc_cap = 5500
                max_total_chars = 22000
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
            if exact_drilldown:
                exact_scope_rules = (
                    "- The user asks for SUBTOPICS, subsections, or nested headings under a specific chapter/section.\n"
                    "- Copy titles EXACTLY as in the excerpts (no paraphrase).\n"
                    "- Return ONLY lines that are children of the section the user meant (e.g. «тема 2», «глава 3»).\n"
                    "- Preserve numbering prefixes from the source in 'title' when they appear (e.g. «2.1 …»).\n"
                    "- If excerpts do not show subheadings for that section, say so in 'reply' and return empty exact_topics.\n"
                )
            else:
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
                "- exact_topics: array of objects with keys: title (string), page (number|null)\n"
                "- IMPORTANT: 'reply' and 'suggested_goals' must be JSON strings (quoted), never bare numbers.\n\n"
                f"Materials excerpts (retrieved):\n{context}\n"
            )
        else:
            system_prompt = (
                "You are an expert instructional designer and tutor.\n"
                "You will receive excerpts from the user's selected study documents.\n"
                "You help with (A) questions about what the book/materials contain and (B) refining learning goals.\n\n"
                "Rules:\n"
                "- For questions like «что в книге про X», «основы Python», «что такое классы»: answer mainly in 'reply'. "
                "Ground every claim in the excerpts (sections, pages, examples when visible). "
                "Give enough detail to be useful — several short paragraphs or a structured list is OK; do not artificially shorten.\n"
                "- When the user wants to define a study plan, also populate 'topics' with main themes from the materials, "
                "'questions' with 3-7 clarifying questions, and 'suggested_goals' with text they can paste into the form.\n"
                "- If excerpts do not contain enough to answer, say so in 'reply' and still list what *is* visible.\n"
                "- If the user asks something outside the provided materials, say it and propose how to proceed.\n"
                "- Reply in the same language as the user.\n\n"
                "Return ONLY valid JSON with keys:\n"
                "- reply: string (your full answer as plain text, no markdown)\n"
                "- suggested_goals: string (clean text the user can paste; may be empty if the user only asked for content, not goals)\n"
                "- topics: array of strings\n"
                "- questions: array of strings (may be empty if the user only asked for a factual summary)\n"
                "- IMPORTANT: 'reply' and 'suggested_goals' must be JSON strings (quoted), never bare numbers.\n\n"
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
            # Prefer JSON response format when supported.
            # Semantic preplan packs reply + topics + questions + suggested_goals — needs a larger budget than 1200 tokens.
            _semantic_max = int(os.getenv("LLM_PREPLAN_SEMANTIC_MAX_TOKENS", "4096"))
            _semantic_max = max(1200, min(_semantic_max, 8000))
            _exact_max = (
                2200
                if (mode == "exact" and exact_drilldown)
                else (1300 if mode == "exact" else _semantic_max)
            )
            resp = llm._client.chat.completions.create(
                model=llm.model_name,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=_exact_max,
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
            data = self._coerce_preplan_json_payload(data)
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
            reply_out = PreplanChatView._preplan_reply_fallback_if_bad_numeric(
                data,
                PreplanChatView._preplan_json_string_field(data.get("reply")),
            )
            goals_out = PreplanChatView._preplan_json_string_field(data.get("suggested_goals"))
            return Response(
                {
                    "reply": reply_out,
                    "suggested_goals": goals_out,
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

