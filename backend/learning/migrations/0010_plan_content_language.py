from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0009_document_extracted_outline"),
    ]

    operations = [
        migrations.AddField(
            model_name="plan",
            name="content_language",
            field=models.CharField(
                choices=[("auto", "Auto"), ("ru", "Russian"), ("en", "English")],
                default="auto",
                max_length=10,
            ),
        ),
    ]
