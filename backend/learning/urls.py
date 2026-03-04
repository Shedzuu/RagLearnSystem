from django.urls import path

from . import views


urlpatterns = [
    path("plans/", views.PlanListCreateView.as_view(), name="plan-list-create"),
    path("plans/<int:pk>/", views.PlanDetailView.as_view(), name="plan-detail"),
    path("units/<int:pk>/", views.UnitDetailView.as_view(), name="unit-detail"),
    path("attempts/start/", views.StartAttemptView.as_view(), name="attempt-start"),
    path("answers/submit/", views.SubmitAnswerView.as_view(), name="answer-submit"),
]

