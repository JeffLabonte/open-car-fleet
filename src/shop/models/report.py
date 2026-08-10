from django.conf import settings
from django.db import models

from shop.models.car import Car
from shop.models.garage import KnownShop


class Report(models.Model):
    """A historical report for work done on a car.

    - `job_name`: the name/title of the work performed
    - `date_done`: date when the work was completed
    - `documents`: list of URLs or paths to documents (stored as JSON)
    - `photos`: list of URLs or paths to photos (stored as JSON)
    - `note`: freeform note about the work
    """

    car = models.ForeignKey(Car, related_name="reports", on_delete=models.CASCADE)
    mileage = models.PositiveIntegerField(null=True, blank=True)
    job_name = models.CharField(max_length=200)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_reports",
    )
    assigned_shop = models.ForeignKey(
        KnownShop,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports",
    )
    date_done = models.DateField()
    documents = models.JSONField(default=list, blank=True)
    photos = models.JSONField(default=list, blank=True)
    note = models.TextField(blank=True)
    additional_information = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~(models.Q(assigned_to__isnull=False) & models.Q(assigned_shop__isnull=False)),
                name="report_single_assignment_target",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.assigned_to and not getattr(self.assigned_to, "is_mechanic", False):
            from django.core.exceptions import ValidationError

            raise ValidationError({"assigned_to": "Assigned user must be a mechanic."})

    def __str__(self) -> str:
        return f"{self.job_name} on {self.date_done} for {self.car}"


class ReportAttachment(models.Model):
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

    report = models.ForeignKey(Report, related_name='attachments', on_delete=models.CASCADE)
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_UPLOAD)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_DOCUMENT)
    file = models.FileField(upload_to='report_attachments/%Y/%m/%d', blank=True, null=True)
    url = models.URLField(blank=True, default='')
    display_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'created_at']

    def save(self, *args, **kwargs) -> None:
        if self.source_type == self.SOURCE_UPLOAD and self.file and not self.display_name:
            self.display_name = self.file.name
        if self.source_type == self.SOURCE_EXTERNAL and not self.kind:
            self.kind = self.KIND_LINK
        if self.source_type == self.SOURCE_UPLOAD and self.file and not self.mime_type:
            self.mime_type = self.file.content_type or ''
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
