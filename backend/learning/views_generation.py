from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Plan
from .serializers import PlanDetailSerializer
from .services_generation import generate_plan_from_documents


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

        try:
            # mark as processing
            plan.generation_status = Plan.GenerationStatus.PROCESSING
            plan.save(update_fields=["generation_status"])

            generate_plan_from_documents(plan)
        except Exception as exc:
            plan.generation_status = Plan.GenerationStatus.FAILED
            plan.save(update_fields=["generation_status"])
            return Response(
                {"detail": f"Generation failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        serializer = PlanDetailSerializer(plan)
        return Response(serializer.data, status=status.HTTP_200_OK)

