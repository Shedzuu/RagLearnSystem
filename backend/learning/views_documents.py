from pathlib import Path

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Document, Plan
from .serializers import DocumentSerializer
from .tasks import index_document_task, extract_document_topics_task


class DocumentListView(generics.ListAPIView):
    """List documents of the current user (for material selection)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DocumentSerializer

    def get_queryset(self):
        qs = Document.objects.filter(owner=self.request.user).order_by("-uploaded_at")
        # Self-heal: if documents are stuck in pending, enqueue indexing task again.
        for doc in qs:
            if doc.index_status == Document.IndexStatus.PENDING:
                if not doc.doc_chunks.exists():
                    doc.index_status = Document.IndexStatus.PROCESSING
                    doc.index_error = ""
                    doc.save(update_fields=["index_status", "index_error"])
                    index_document_task.delay(doc.id)
                else:
                    # If chunks already exist, mark as ready.
                    doc.index_status = Document.IndexStatus.READY
                    doc.index_error = ""
                    doc.save(update_fields=["index_status", "index_error"])
            # Backfill for previously indexed docs: start topics extraction if not started yet.
            if (
                doc.index_status == Document.IndexStatus.READY
                and doc.topics_status == Document.TopicsStatus.IDLE
            ):
                doc.topics_status = Document.TopicsStatus.PROCESSING
                doc.topics_error = ""
                doc.save(update_fields=["topics_status", "topics_error"])
                extract_document_topics_task.delay(doc.id)
        return qs


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

        # Detach documents already bound to OTHER plans before re-attaching.
        docs.update(plan=plan)
        # Remove duplicate file_path records attached to this plan (keep lowest id).
        from django.db.models import Min
        dupes_qs = (
            Document.objects.filter(plan=plan)
            .values("file_path")
            .annotate(min_id=Min("id"))
            .filter(file_path__in=Document.objects.filter(plan=plan).values("file_path"))
        )
        keep_ids = [row["min_id"] for row in dupes_qs]
        Document.objects.filter(plan=plan).exclude(id__in=keep_ids).delete()

        serialized = DocumentSerializer(docs, many=True)
        return Response(serialized.data, status=status.HTTP_200_OK)


class PlanDocumentDeleteView(APIView):
    """Remove a document from a plan: delete file, DB row, chunks and topic fields (CASCADE)."""

    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, plan_id, document_id, *args, **kwargs):
        plan = get_object_or_404(Plan, id=plan_id, owner=request.user)
        doc = get_object_or_404(
            Document,
            id=document_id,
            plan=plan,
            owner=request.user,
        )
        base = Path(settings.BASE_DIR).resolve()
        rel = Path(doc.file_path)
        if not rel.is_absolute():
            target = (base / rel).resolve()
        else:
            target = rel.resolve()
        try:
            if target.is_file() and (base == target or base in target.parents):
                target.unlink()
        except OSError:
            pass
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DocumentDeleteView(APIView):
    """Delete a user's document from the materials library."""

    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, document_id, *args, **kwargs):
        doc = get_object_or_404(
            Document,
            id=document_id,
            owner=request.user,
        )
        base = Path(settings.BASE_DIR).resolve()
        rel = Path(doc.file_path)
        if not rel.is_absolute():
            target = (base / rel).resolve()
        else:
            target = rel.resolve()
        try:
            if target.is_file() and (base == target or base in target.parents):
                target.unlink()
        except OSError:
            pass
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


