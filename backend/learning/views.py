import os

from django.conf import settings
from django.shortcuts import get_object_or_404
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

