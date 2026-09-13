from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


class Attachment(models.Model):
    """A unified file upload or external link attached to any parent object.

    Parents (reports, car documents, known shop proofs, ...) declare a
    ``GenericRelation`` to this model; the file or link lives here.
    """

    SOURCE_UPLOAD = 'upload'
    SOURCE_EXTERNAL = 'external'

    KIND_IMAGE = 'image'
    KIND_VIDEO = 'video'
    KIND_DOCUMENT = 'document'
    KIND_LINK = 'link'

    SOURCE_CHOICES = [
        (SOURCE_UPLOAD, 'Uploaded file'),
        (SOURCE_EXTERNAL, 'External link'),
    ]
    KIND_CHOICES = [
        (KIND_IMAGE, 'Image'),
        (KIND_VIDEO, 'Video'),
        (KIND_DOCUMENT, 'Document'),
        (KIND_LINK, 'Link'),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64, db_index=True)
    parent = GenericForeignKey('content_type', 'object_id')

    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_UPLOAD)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_DOCUMENT)
    file = models.FileField(upload_to='attachments/%Y/%m/%d', blank=True, null=True)
    url = models.URLField(blank=True, default='')
    display_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'created_at']
        indexes = [models.Index(fields=['content_type', 'object_id'], name='attachment_parent_idx')]

    def save(self, *args, **kwargs) -> None:
        if self.source_type == self.SOURCE_UPLOAD and self.file and not self.display_name:
            self.display_name = self.file.name.rsplit('/', 1)[-1]
        if self.source_type == self.SOURCE_EXTERNAL and not self.kind:
            self.kind = self.KIND_LINK
        if self.source_type == self.SOURCE_UPLOAD and self.file and not self.mime_type:
            self.mime_type = getattr(self.file, 'content_type', '') or ''
        if self.source_type == self.SOURCE_UPLOAD and self.file:
            if self.mime_type.startswith('image/'):
                self.kind = self.KIND_IMAGE
            elif self.mime_type.startswith('video/'):
                self.kind = self.KIND_VIDEO
            else:
                self.kind = self.KIND_DOCUMENT
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.display_name or self.url or str(self.pk)


@receiver(post_delete, sender=Attachment)
def delete_attachment_file(sender: type[Attachment], instance: Attachment, **kwargs: object) -> None:
    if instance.file:
        instance.file.delete(save=False)
