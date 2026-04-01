from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0006_add_documentchunk"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="index_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="document",
            name="index_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("ready", "Ready"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="topics_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="document",
            name="topics_status",
            field=models.CharField(
                choices=[
                    ("idle", "Idle"),
                    ("processing", "Processing"),
                    ("ready", "Ready"),
                    ("failed", "Failed"),
                ],
                default="idle",
                max_length=20,
            ),
        ),
    ]
