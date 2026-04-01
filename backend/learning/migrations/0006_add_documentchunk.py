# Generated manually for DocumentChunk model (doc-level RAG)

from django.db import migrations, models
import django.db.models.deletion
from pgvector.django import VectorField


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0005_rename_learning_chunk_plan_doc_idx_learning_ch_plan_id_cc7064_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentChunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("content", models.TextField()),
                ("page_number", models.IntegerField(blank=True, null=True)),
                ("chunk_index", models.IntegerField()),
                ("start_char", models.IntegerField(blank=True, null=True)),
                ("end_char", models.IntegerField(blank=True, null=True)),
                ("embedding", VectorField(blank=True, dimensions=1024, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="doc_chunks", to="learning.document")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["document", "chunk_index"], name="learning_do_document_8f97aa_idx"),
                ],
            },
        ),
    ]

