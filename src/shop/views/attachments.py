import mimetypes
import os
from typing import Any

from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from car_docs.models import CarDoc
from shop.forms.base import validate_uploaded_file
from shop.middleware import hanko_login_required
from shop.models.attachment import Attachment
from shop.models.fleet import KnownShopProof
from shop.models.report import Report
from shop.services.attachments import (
    ATTACHMENT_USER_STAGED_QUOTA_BYTES,
    INLINE_SAFE_ATTACHMENT_TYPES,
    purge_stale_staged_attachments,
)
from shop.view_helpers import (
    user_cars_queryset,
    user_known_shops_queryset,
)


@hanko_login_required
@require_POST
@ratelimit(key="user", rate="30/m", method="POST")
def attachment_upload(request: HttpRequest) -> JsonResponse:
    """Stage one uploaded file for the submitting user; returns its attachment ID.

    The file is validated with the exact same rules as the classic form
    path (size, extension, content type, magic bytes). It becomes a real
    attachment only when the parent form claims it by ID.
    """
    purge_stale_staged_attachments()
    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"error": _("No file was uploaded.")}, status=400)
    try:
        validate_uploaded_file(upload)
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)

    staged_bytes = sum(
        attachment.file.size
        for attachment in Attachment.objects.filter(
            uploaded_by=request.user,
            content_type__isnull=True,
        ).iterator()
        if attachment.file
    )
    if staged_bytes + upload.size > ATTACHMENT_USER_STAGED_QUOTA_BYTES:
        return JsonResponse(
            {"error": _("Upload quota exceeded. Delete unused staged files or wait for them to expire.")},
            status=413,
        )

    attachment = Attachment(
        source_type=Attachment.SOURCE_UPLOAD,
        uploaded_by=request.user,
        file=upload,
        display_name=os.path.basename(upload.name),
        mime_type=getattr(upload, "content_type", "") or "",
    )
    attachment.save()
    return JsonResponse(
        {
            "id": attachment.pk,
            "name": attachment.display_name,
            "kind": attachment.kind,
            "size": upload.size,
        },
        status=201,
    )


@hanko_login_required
@require_POST
def attachment_delete(request: HttpRequest, pk: int) -> JsonResponse:
    """Delete a staged upload owned by the requesting user (file removed client-side)."""
    attachment = get_object_or_404(Attachment, pk=pk)
    if attachment.content_type_id is not None or attachment.uploaded_by_id != request.user.pk:
        raise Http404(_("Attachment not found."))
    attachment.delete()
    return JsonResponse({"ok": True})


def _user_can_view_attachment(user: Any, attachment: Attachment) -> bool:
    """Authorize attachment downloads through their parent object's permissions."""
    parent = attachment.parent
    if parent is None:
        return False
    if isinstance(parent, Report):
        return user_cars_queryset(user).filter(pk=parent.car_id).exists()
    if isinstance(parent, CarDoc):
        from shop.view_helpers import user_car_docs_queryset

        return user_car_docs_queryset(user).filter(pk=parent.pk).exists()
    if isinstance(parent, KnownShopProof):
        return user_known_shops_queryset(user).filter(pk=parent.shop_id).exists()
    return False


@hanko_login_required
@require_GET
def attachment_file(request: HttpRequest, pk: int) -> FileResponse:
    attachment = get_object_or_404(Attachment.objects.select_related("content_type"), pk=pk)
    if not _user_can_view_attachment(request.user, attachment):
        raise Http404(_("Attachment not found."))
    if not attachment.file:
        raise Http404(_("Attachment has no file."))
    content_type = mimetypes.guess_type(attachment.file.name)[0] or "application/octet-stream"
    response = FileResponse(attachment.file.open("rb"), content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    if content_type not in INLINE_SAFE_ATTACHMENT_TYPES:
        download_name = os.path.basename(attachment.file.name).replace('"', "")
        response["Content-Disposition"] = f'attachment; filename="{download_name}"'
    return response
