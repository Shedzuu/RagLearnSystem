from django.contrib import admin

from .models import (
    AiChatMessage,
    Answer,
    AnswerChoice,
    Attempt,
    Choice,
    CourseFeedback,
    Document,
    Enrollment,
    Plan,
    Question,
    QuestionStats,
    Section,
    SectionProgress,
    Unit,
    UnitProgress,
)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "owner", "generation_status", "created_at")
    list_filter = ("generation_status", "is_public")
    search_fields = ("title", "owner__email")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("id", "plan", "title", "order", "generation_status")
    list_filter = ("generation_status", "plan")


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("id", "section", "title", "order", "generation_status")
    list_filter = ("generation_status", "section__plan")


admin.site.register(Document)
admin.site.register(Question)
admin.site.register(Choice)
admin.site.register(Enrollment)
admin.site.register(Attempt)
admin.site.register(Answer)
admin.site.register(AnswerChoice)
admin.site.register(UnitProgress)
admin.site.register(SectionProgress)
admin.site.register(QuestionStats)
admin.site.register(CourseFeedback)
admin.site.register(AiChatMessage)

