from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Plan, Unit, Attempt, Enrollment, Question, Choice, Answer, AnswerChoice
from .serializers import (
    PlanListSerializer,
    PlanDetailSerializer,
    UnitDetailSerializer,
    AnswerCreateSerializer,
)


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

        answer.save()

        return Response(
            {
                "answer_id": answer.id,
                "is_correct": answer.is_correct,
                "earned_points": answer.earned_points,
            },
            status=status.HTTP_200_OK,
        )

