from django.db import migrations, models


def copy_car_doc_files(apps, schema_editor):
    """Copy every CarDoc PDF into a unified Attachment row before the field is dropped."""
    CarDoc = apps.get_model('car_docs', 'CarDoc')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Attachment = apps.get_model('shop', 'Attachment')

    doc_type = ContentType.objects.get(app_label='car_docs', model='cardoc')
    for doc in CarDoc.objects.filter(file__isnull=False).exclude(file='').iterator():
        name = doc.file.name
        attachment = Attachment.objects.create(
            content_type=doc_type,
            object_id=str(doc.pk),
            source_type='upload',
            kind='document',
            file=name,
            display_name=name.rsplit('/', 1)[-1],
            mime_type='application/pdf',
        )
        Attachment.objects.filter(pk=attachment.pk).update(created_at=doc.created_at)


def uncopy_car_doc_files(apps, schema_editor):
    Attachment = apps.get_model('shop', 'Attachment')
    doc_type = ContentType.objects.get(app_label='car_docs', model='cardoc')
    Attachment.objects.filter(content_type=doc_type).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('car_docs', '0002_cardoc_file'),
        ('shop', '0015_create_attachment'),
    ]

    operations = [
        migrations.RunPython(copy_car_doc_files, uncopy_car_doc_files),
        migrations.RemoveField(model_name='cardoc', name='file'),
    ]
