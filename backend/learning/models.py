from django.conf import settings
from django.db import models


User = settings.AUTH_USER_MODEL


class Plan(models.Model):
    class GenerationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="plans")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    generation_status = models.CharField(
        max_length=20,
        choices=GenerationStatus.choices,
        default=GenerationStatus.PENDING,
    )
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.title


class Document(models.Model):
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="documents",
        null=True,
        blank=True,
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.CASCADE,
        related_name="documents",
        null=True,
        blank=True,
    )
    file_path = models.CharField(max_length=500)
    original_name = models.CharField(max_length=255)
    file_size = models.IntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.original_name


class Section(models.Model):
    class GenerationStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=255)
    order = models.IntegerField()
    generation_status = models.CharField(
        max_length=20,
        choices=GenerationStatus.choices,
        default=GenerationStatus.DRAFT,
    )

    class Meta:
        unique_together = ("plan", "order")
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.plan.title}: {self.title}"


class Unit(models.Model):
    class GenerationStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="units")
    title = models.CharField(max_length=255)
    order = models.IntegerField()
    theory = models.TextField()
    generation_status = models.CharField(
        max_length=20,
        choices=GenerationStatus.choices,
        default=GenerationStatus.DRAFT,
    )

    class Meta:
        unique_together = ("section", "order")
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.section.title}: {self.title}"


class Question(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE_CHOICE = "single_choice", "Single choice"
        MULTIPLE_CHOICE = "multiple_choice", "Multiple choice"
        OPEN_TEXT = "open_text", "Open text"
        CODE = "code", "Code"

    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    type = models.CharField(max_length=30, choices=QuestionType.choices)
    difficulty = models.PositiveSmallIntegerField(default=1)
    order = models.IntegerField()
    points = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ("unit", "order")
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.text[:80]


class Choice(models.Model):
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="choices"
    )
    text = models.TextField()
    is_correct = models.BooleanField(default=False)
    order = models.IntegerField()

    class Meta:
        unique_together = ("question", "order")
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.text[:80]


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        DROPPED = "dropped", "Dropped"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="enrollments")
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="enrollments")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "plan")

    def __str__(self) -> str:
        return f"{self.user} -> {self.plan} ({self.status})"


class Attempt(models.Model):
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="attempts"
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Attempt {self.id} for {self.enrollment}"


class Answer(models.Model):
    attempt = models.ForeignKey(
        Attempt, on_delete=models.CASCADE, related_name="answers"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="answers"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_correct = models.BooleanField(null=True, blank=True)
    earned_points = models.FloatField(null=True, blank=True)
    feedback_text = models.TextField(blank=True)
    text_answer = models.TextField(blank=True)
    code_answer = models.TextField(blank=True)

    class Meta:
        unique_together = ("attempt", "question")

    def __str__(self) -> str:
        return f"Answer {self.id} for Q{self.question_id}"


class AnswerChoice(models.Model):
    answer = models.ForeignKey(
        Answer, on_delete=models.CASCADE, related_name="selected_choices"
    )
    choice = models.ForeignKey(
        Choice, on_delete=models.CASCADE, related_name="answers_selected"
    )

    class Meta:
        unique_together = ("answer", "choice")

    def __str__(self) -> str:
        return f"{self.answer_id} -> {self.choice_id}"


class UnitProgress(models.Model):
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="unit_progress"
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="progress_records"
    )
    progress_percent = models.FloatField(default=0.0)
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ("enrollment", "unit")

    def __str__(self) -> str:
        return f"{self.enrollment} - {self.unit} ({self.progress_percent}%)"


class SectionProgress(models.Model):
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="section_progress"
    )
    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name="progress_records"
    )
    progress_percent = models.FloatField(default=0.0)
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ("enrollment", "section")

    def __str__(self) -> str:
        return f"{self.enrollment} - {self.section} ({self.progress_percent}%)"


class QuestionStats(models.Model):
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="question_stats"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="stats"
    )
    attempts_count = models.IntegerField(default=0)
    correct_count = models.IntegerField(default=0)
    success_rate = models.FloatField(default=0.0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("enrollment", "question")

    def __str__(self) -> str:
        return f"Stats for {self.question_id} ({self.success_rate}%)"


class CourseFeedback(models.Model):
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="feedback"
    )
    rating = models.IntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Feedback {self.rating} for {self.enrollment}"


class AiChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ai_messages"
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.CASCADE, null=True, blank=True, related_name="ai_messages"
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ai_messages",
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ai_messages",
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ai_messages",
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:50]}"

