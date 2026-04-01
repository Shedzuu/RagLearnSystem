from django.urls import path

from . import views
from .views_documents import DocumentListView, AttachDocumentsToPlanView
from .views_upload_free import FreeDocumentUploadView
from .views_generation import PlanGenerateView


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
    path(
        "plans/<int:plan_id>/generate/",
        PlanGenerateView.as_view(),
        name="plan-generate",
    ),
    path("documents/", DocumentListView.as_view(), name="document-list"),
    path("documents/upload/", FreeDocumentUploadView.as_view(), name="document-upload"),
    path("units/<int:pk>/", views.UnitDetailView.as_view(), name="unit-detail"),
    path("units/<int:unit_id>/state/", views.UnitStateView.as_view(), name="unit-state"),
    path("attempts/start/", views.StartAttemptView.as_view(), name="attempt-start"),
    path("answers/submit/", views.SubmitAnswerView.as_view(), name="answer-submit"),
    path("attempts/finish/", views.FinishAttemptView.as_view(), name="attempt-finish"),
    path("plans/<int:plan_id>/progress/", views.PlanProgressView.as_view(), name="plan-progress"),
    path("ai/chat/", views.AiChatView.as_view(), name="ai-chat"),
    path("ai/landing-chat/", views.LandingChatView.as_view(), name="ai-landing-chat"),
    path("ai/preplan-chat/", views.PreplanChatView.as_view(), name="ai-preplan-chat"),
]

