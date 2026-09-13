from django.db import migrations, models


def copy_report_attachments(apps, schema_editor):
    """Copy every ReportAttachment row into the unified Attachment model."""
    ReportAttachment = apps.get_model('shop', 'ReportAttachment')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Attachment = apps.get_model('shop', 'Attachment')

    report_type = ContentType.objects.get_or_create(app_label='shop', model='report')[0]
    for source in ReportAttachment.objects.all().order_by('pk').iterator():
        display_name = source.display_name
        if not display_name and source.file:
            display_name = source.file.name.rsplit('/', 1)[-1]
        attachment = Attachment.objects.create(
            content_type=report_type,
            object_id=str(source.report_id),
            source_type=source.source_type,
            kind=source.kind,
            file=source.file.name if source.file else '',
            url=source.url,
            display_name=display_name,
            mime_type=source.mime_type,
            order=source.order,
        )
        Attachment.objects.filter(pk=attachment.pk).update(created_at=source.created_at)


def copy_known_shop_proof_files(apps, schema_editor):
    """Copy every KnownShopProof PDF into a unified Attachment row before the field is dropped."""
    KnownShopProof = apps.get_model('shop', 'KnownShopProof')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Attachment = apps.get_model('shop', 'Attachment')

    proof_type = ContentType.objects.get_or_create(app_label='shop', model='knownshopproof')[0]
    for proof in KnownShopProof.objects.filter(file__isnull=False).exclude(file='').iterator():
        name = proof.file.name
        attachment = Attachment.objects.create(
            content_type=proof_type,
            object_id=str(proof.pk),
            source_type='upload',
            kind='document',
            file=name,
            display_name=name.rsplit('/', 1)[-1],
            mime_type='application/pdf',
        )
        Attachment.objects.filter(pk=attachment.pk).update(created_at=proof.created_at)


def uncopy(apps, schema_editor):
    Attachment = apps.get_model('shop', 'Attachment')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    report_type = ContentType.objects.get_or_create(app_label='shop', model='report')[0]
    proof_type = ContentType.objects.get_or_create(app_label='shop', model='knownshopproof')[0]
    Attachment.objects.filter(content_type__in=[report_type, proof_type]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('car_docs', '0003_cardoc_file_to_attachment'),
        ('shop', '0015_create_attachment'),
    ]

    operations = [
        migrations.RunPython(copy_report_attachments, uncopy),
        migrations.RunPython(copy_known_shop_proof_files, uncopy),
        migrations.RemoveField(model_name='report', name='documents'),
        migrations.RemoveField(model_name='report', name='photos'),
        migrations.RemoveField(model_name='knownshopproof', name='file'),
        migrations.DeleteModel(name='ReportAttachment'),
    ]
