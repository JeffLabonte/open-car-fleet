import os
from datetime import timedelta
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from shop.models.attachment import Attachment

# Per-user quota for staged (unclaimed) uploads (1 GB). Claimed attachments
# are counted against the parent object, not this transient quota.
ATTACHMENT_USER_STAGED_QUOTA_BYTES = 1024 * 1024 * 1024


# MIME types that may be displayed inline by the attachment file view.
INLINE_SAFE_ATTACHMENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "application/pdf",
}


# Staged uploads are deleted after this retention window if no parent form
# claims them.
STAGED_ATTACHMENT_MAX_AGE = timedelta(hours=12)


def purge_stale_staged_attachments() -> int:
    """Delete staged uploads no parent form claimed within the retention window."""
    cutoff = timezone.now() - STAGED_ATTACHMENT_MAX_AGE
    stale = Attachment.objects.filter(content_type__isnull=True, created_at__lt=cutoff)
    count = stale.count()
    stale.delete()
    return count


def save_attachments(
    parent: Any,
    uploaded_files: list[Any],
    external_links: list[str],
    staged: list[Any] | None = None,
) -> None:
    """Persist unified attachments (uploads and external links) for any parent model.

    ``staged`` holds Attachment rows created earlier by the AJAX upload
    endpoint for this user (validated in the form); they are re-parented
    onto ``parent`` here.
    """
    content_type = ContentType.objects.get_for_model(parent)
    for index, uploaded_file in enumerate(uploaded_files):
        Attachment.objects.create(
            content_type=content_type,
            object_id=str(parent.pk),
            source_type=Attachment.SOURCE_UPLOAD,
            file=uploaded_file,
            display_name=os.path.basename(getattr(uploaded_file, "name", "") or f"attachment-{index + 1}"),
            mime_type=getattr(uploaded_file, "content_type", ""),
        )

    for index, attachment in enumerate(staged or []):
        attachment.content_type = content_type
        attachment.object_id = str(parent.pk)
        attachment.order = len(uploaded_files) + index
        attachment.save()

    for index, external_link in enumerate(external_links):
        Attachment.objects.create(
            content_type=content_type,
            object_id=str(parent.pk),
            source_type=Attachment.SOURCE_EXTERNAL,
            url=external_link,
            display_name=external_link.rstrip("/").rsplit("/", 1)[-1] or f"link-{index + 1}",
            kind=Attachment.KIND_LINK,
        )
