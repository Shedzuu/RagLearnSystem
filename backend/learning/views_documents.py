from rest_framework import generics, permissions

from .models import Document
from .serializers import DocumentSerializer


class DocumentListView(generics.ListAPIView):
    """List documents of the current user (for material selection)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DocumentSerializer

    def get_queryset(self):
        return Document.objects.filter(owner=self.request.user).order_by("-uploaded_at")

