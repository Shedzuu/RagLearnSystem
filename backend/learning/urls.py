from django.urls import path

from . import views
from .views_documents import DocumentListView, AttachDocumentsToPlanView
from .views_upload_free import FreeDocumentUploadView


urlpatterns = [
    path("plans/", views.PlanListCreateView.as_view(), name="plan-list-create"),
    path("plans/<int:pk>/", views.PlanDetailView.as_view(), name="plan-detail"),
    path(
        "plans/<int:plan_id>/documents/",
        views.PlanDocumentUploadView.as_view(),
        name="plan-document-upload",
    ),
    path(
        "plans/<int:plan_id>/attach-documents/",
        AttachDocumentsToPlanView.as_view(),
        name="plan-attach-documents",
    ),
    path("documents/", DocumentListView.as_view(), name="document-list"),
    path("documents/upload/", FreeDocumentUploadView.as_view(), name="document-upload"),
    path("units/<int:pk>/", views.UnitDetailView.as_view(), name="unit-detail"),
    path("attempts/start/", views.StartAttemptView.as_view(), name="attempt-start"),
    path("answers/submit/", views.SubmitAnswerView.as_view(), name="answer-submit"),
]

