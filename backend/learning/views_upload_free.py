import os

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Document


class FreeDocumentUploadView(APIView):
    """Upload a source document not yet attached to a plan."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response(
                {"detail": "file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        documents_dir = os.path.join(settings.BASE_DIR, "media", "documents")
        os.makedirs(documents_dir, exist_ok=True)

        filename = uploaded_file.name
        unique_name = f"user{request.user.id}_{filename}"
        file_path = os.path.join(documents_dir, unique_name)

        with open(file_path, "wb+") as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        rel_path = os.path.relpath(file_path, settings.BASE_DIR)

        # Reuse existing document record if the same file was already uploaded.
        doc, _ = Document.objects.get_or_create(
            owner=request.user,
            file_path=rel_path,
            defaults={
                "original_name": filename,
                "file_size": uploaded_file.size,
            },
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

