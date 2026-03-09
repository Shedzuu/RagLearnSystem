from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Document, Plan
from .serializers import DocumentSerializer


class DocumentListView(generics.ListAPIView):
    """List documents of the current user (for material selection)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DocumentSerializer

    def get_queryset(self):
        return Document.objects.filter(owner=self.request.user).order_by("-uploaded_at")


class AttachDocumentsToPlanView(APIView):
    """Attach existing user documents to a plan."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, plan_id, *args, **kwargs):
        document_ids = request.data.get("document_ids") or []
        if not isinstance(document_ids, list) or not document_ids:
            return Response(
                {"detail": "document_ids must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Ensure plan belongs to current user
        try:
            plan = Plan.objects.get(id=plan_id, owner=request.user)
        except Plan.DoesNotExist:
            return Response(
                {"detail": "Plan not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Select only documents owned by user and with ids from request
        docs = Document.objects.filter(
            owner=request.user,
            id__in=document_ids,
        )
        if not docs.exists():
            return Response(
                {"detail": "No matching documents found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs.update(plan=plan)

        serialized = DocumentSerializer(docs, many=True)
        return Response(serialized.data, status=status.HTTP_200_OK)


