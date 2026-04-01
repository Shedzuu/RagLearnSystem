from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0008_document_extracted_topics"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="extracted_outline",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
