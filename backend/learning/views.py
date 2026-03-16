import os

from django.conf import settings
from django.db.models import Sum, Count, F
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
)
from .serializers import (
    PlanListSerializer,
    PlanDetailSerializer,
    UnitDetailSerializer,
    AnswerCreateSerializer,
)
from .services_generation import LLMClient


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
        return Plan.objects.filter(owner=self.request.user)


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
                answered_count = (
                    Answer.objects.filter(
                        attempt__enrollment=enrollment,
                        question__unit=unit,
                    )
                    .values("question_id")
                    .distinct()
                    .count()
                )
                progress_percent = (answered_count / total_q_in_unit) * 100.0

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
        )

        return Response(
            {
                "id": doc.id,
                "original_name": doc.original_name,
                "file_path": doc.file_path,
                "file_size": doc.file_size,
            },
            status=status.HTTP_201_CREATED,
        )

