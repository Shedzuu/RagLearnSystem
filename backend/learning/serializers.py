from rest_framework import serializers

from .models import Choice, Plan, Question, Section, Unit, Attempt, Answer, AnswerChoice, Document


class ChoiceSerializer(serializers.ModelSerializer):
  class Meta:
      model = Choice
      fields = ("id", "text", "is_correct")
      read_only_fields = ("id", "is_correct")


class QuestionSerializer(serializers.ModelSerializer):
  choices = ChoiceSerializer(many=True, read_only=True)

  class Meta:
      model = Question
      fields = ("id", "text", "type", "difficulty", "order", "points", "choices")
      read_only_fields = ("id", "difficulty", "order", "points", "choices")


class UnitSerializer(serializers.ModelSerializer):
  class Meta:
      model = Unit
      fields = ("id", "title", "order", "generation_status")
      read_only_fields = ("id", "generation_status")


class SectionSerializer(serializers.ModelSerializer):
  units = UnitSerializer(many=True, read_only=True)

  class Meta:
      model = Section
      fields = ("id", "title", "order", "generation_status", "units")
      read_only_fields = ("id", "generation_status", "units")


class PlanListSerializer(serializers.ModelSerializer):
  class Meta:
      model = Plan
      fields = ("id", "title", "description", "goals", "generation_status", "created_at")
      read_only_fields = ("id", "generation_status", "created_at")


class PlanDetailSerializer(serializers.ModelSerializer):
  sections = SectionSerializer(many=True, read_only=True)

  class Meta:
      model = Plan
      fields = ("id", "title", "description", "goals", "generation_status", "created_at", "sections")
      read_only_fields = ("id", "generation_status", "created_at", "sections")


class UnitDetailSerializer(serializers.ModelSerializer):
  questions = QuestionSerializer(many=True, read_only=True)
  section_id = serializers.IntegerField(read_only=True)
  plan_id = serializers.IntegerField(source='section.plan_id', read_only=True)

  class Meta:
      model = Unit
      fields = ("id", "title", "order", "theory", "generation_status", "section_id", "plan_id", "questions")
      read_only_fields = ("id", "generation_status", "section_id", "plan_id", "questions")


class DocumentSerializer(serializers.ModelSerializer):
  class Meta:
      model = Document
      fields = ("id", "original_name", "file_path", "file_size", "plan_id", "uploaded_at")
      read_only_fields = ("id", "file_path", "file_size", "plan_id", "uploaded_at")


class AnswerChoiceCreateSerializer(serializers.Serializer):
  choice_id = serializers.IntegerField()


class AnswerCreateSerializer(serializers.Serializer):
  """Упрощённый сериализатор для отправки ответа на вопрос."""

  question_id = serializers.IntegerField()
  attempt_id = serializers.IntegerField()
  text_answer = serializers.CharField(required=False, allow_blank=True)
  code_answer = serializers.CharField(required=False, allow_blank=True)
  selected_choices = AnswerChoiceCreateSerializer(many=True, required=False)

  def validate(self, attrs):
      # Здесь позже можно добавить проверки на соответствие попытки пользователю и т.п.
      return attrs

