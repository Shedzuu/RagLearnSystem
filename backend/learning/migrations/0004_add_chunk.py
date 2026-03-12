# Generated manually for Chunk model (RAG)

from django.db import migrations, models
import django.db.models.deletion
from pgvector.django import VectorField


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0003_plan_goals'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql="DROP EXTENSION IF EXISTS vector;",
        ),
        migrations.CreateModel(
            name='Chunk',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField()),
                ('page_number', models.IntegerField(blank=True, null=True)),
                ('chunk_index', models.IntegerField()),
                ('start_char', models.IntegerField(blank=True, null=True)),
                ('end_char', models.IntegerField(blank=True, null=True)),
                ('embedding', VectorField(blank=True, dimensions=1024, null=True)),
                ('document', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chunks', to='learning.document')),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chunks', to='learning.plan')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['plan', 'document', 'chunk_index'], name='learning_chunk_plan_doc_idx'),
                ],
            },
        ),
    ]
