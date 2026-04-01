import logging
import os

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Plan
from .serializers import PlanDetailSerializer
from .services_generation import generate_plan_from_documents
from .services_rag import InsufficientCoverageError
from .tasks import generate_plan_task

logger = logging.getLogger(__name__)


class PlanGenerateView(APIView):
    """
    Trigger LLM-based generation of sections/units/questions for a plan,
    using attached documents and plan.goals as input.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, plan_id, *args, **kwargs):
        try:
            plan = Plan.objects.get(id=plan_id, owner=request.user)
        except Plan.DoesNotExist:
            return Response(
                {"detail": "Plan not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not plan.documents.exists():
            return Response(
                {"detail": "This plan has no attached documents."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        use_sync = os.getenv("GENERATE_PLAN_SYNC", "").lower() in ("1", "true", "yes")

        plan.generation_status = Plan.GenerationStatus.PROCESSING
        plan.save(update_fields=["generation_status"])
        logger.info(
            "[generate] Plan %s: queued generation (documents=%s, sync=%s)",
            plan_id,
            plan.documents.count(),
            use_sync,
        )

        if use_sync:
            try:
                generate_plan_from_documents(plan)
            except InsufficientCoverageError as exc:
                logger.warning("[generate] Plan %s: insufficient coverage: %s", plan_id, exc)
                plan.generation_status = Plan.GenerationStatus.FAILED
                plan.save(update_fields=["generation_status"])
                return Response(
                    {
                        "detail": (
                            "По загруженным материалам недостаточно информации для некоторых целей обучения. "
                            f"{exc}"
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except Exception:
                logger.exception("[generate] Plan %s: generation failed", plan_id)
                plan.generation_status = Plan.GenerationStatus.FAILED
                plan.save(update_fields=["generation_status"])
                return Response(
                    {
                        "detail": "LLM сервис временно недоступен или вернул ошибку. "
                        "Попробуйте запустить генерацию ещё раз чуть позже."
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            plan.refresh_from_db()
            serializer = PlanDetailSerializer(plan)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # Drop stale structure immediately so the first poll reflects async rebuild.
        plan.sections.all().delete()
        generate_plan_task.delay(plan.id)
        plan.refresh_from_db()
        serializer = PlanDetailSerializer(plan)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

