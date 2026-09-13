import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('shop', '0014_garage_sharing_roles_and_audit'),
    ]

    operations = [
        migrations.CreateModel(
            name='Attachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_id', models.CharField(db_index=True, max_length=64)),
                ('source_type', models.CharField(choices=[('upload', 'Uploaded file'), ('external', 'External link')], default='upload', max_length=20)),
                ('kind', models.CharField(choices=[('image', 'Image'), ('video', 'Video'), ('document', 'Document'), ('link', 'Link')], default='document', max_length=20)),
                ('file', models.FileField(blank=True, null=True, upload_to='attachments/%Y/%m/%d')),
                ('url', models.URLField(blank=True, default='')),
                ('display_name', models.CharField(blank=True, max_length=255)),
                ('mime_type', models.CharField(blank=True, max_length=100)),
                ('order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('content_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype')),
            ],
            options={
                'ordering': ['order', 'created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='attachment',
            index=models.Index(fields=['content_type', 'object_id'], name='attachment_parent_idx'),
        ),
    ]
