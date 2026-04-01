from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0007_document_processing_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="extracted_topics",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
