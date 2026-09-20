import os
from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from shop.models.garage import KnownShop

# Per-file upload ceiling for unified attachments (500 MB), large enough for
# long phone-recorded mechanic videos.
ATTACHMENT_MAX_UPLOAD_BYTES = 500 * 1024 * 1024
# Upper bound of files accepted in a single form submission.
ATTACHMENT_MAX_FILES = 10

# File signatures (magic bytes) mapped to the attachment extensions that may
# carry them. Uploads are sniffed so a renamed executable cannot masquerade as
# an image, video, or document.
FILE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    '.jpg': (b'\xff\xd8\xff',),
    '.jpeg': (b'\xff\xd8\xff',),
    '.png': (b'\x89PNG\r\n\x1a\n',),
    '.gif': (b'GIF87a', b'GIF89a'),
    '.webp': (b'RIFF',),
    '.mp4': (b'ftyp',),
    '.mov': (b'ftyp',),
    '.webm': (b'\x1a\x45\xdf\xa3',),
    '.pdf': (b'%PDF-',),
    '.doc': (b'\xd0\xcf\x11\xe0',),
    '.docx': (b'PK\x03\x04',),
}
# Offsets checked in addition to the file start (extension -> (offset, needle)).
FILE_SIGNATURE_OFFSETS: dict[str, tuple[tuple[int, bytes], ...]] = {
    '.webp': ((8, b'WEBP'),),
    '.mp4': ((4, b'ftyp'),),
    '.mov': ((4, b'ftyp'),),
}


class LineListFieldMixin:
    def _clean_line_list_field(self, field_name: str) -> list[str]:
        raw = self.cleaned_data.get(field_name, '')
        return [item.strip() for item in raw.splitlines() if item.strip()]


class AssignedToShopFormMixin:
    def __init__(self, *args: Any, user: Any = None, garage: Any = None, **kwargs: Any) -> None:
        # Store before super().__init__ so StagedAttachmentsMixin (further
        # down the MRO) can read it without receiving the kwarg itself.
        self.user = user
        super().__init__(*args, **kwargs)
        self.configure_assigned_fields(user=user, garage=garage)

    def configure_assigned_fields(self, *, user: Any = None, garage: Any = None) -> None:
        mechanics = get_user_model().objects.filter(is_mechanic=True)
        if garage is not None:
            mechanics = mechanics.filter(
                garage_memberships__garage=garage,
                garage_memberships__role__in=['owner', 'admin', 'mechanic'],
            ).distinct()
        self.fields['assigned_to'].queryset = mechanics
        self.fields['assigned_to'].help_text = _('Only users converted to mechanics can be selected.')
        shops = KnownShop.objects.all()
        if user is not None:
            shops = shops.filter(Q(created_by__isnull=True) | Q(created_by=user))
        self.fields['assigned_shop'].queryset = shops.order_by('name')
        self.fields['assigned_shop'].help_text = _('Assign to a known shop instead of a mechanic user.')

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        if cleaned_data.get('assigned_to') and cleaned_data.get('assigned_shop'):
            raise ValidationError(_('Assign either a mechanic user or a known shop, not both.'))
        return cleaned_data


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True

    def __init__(self, attrs: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(attrs=attrs, **kwargs)
        self.attrs['multiple'] = True


def validate_uploaded_file(cleaned_file: Any) -> None:
    """OWASP upload checks for one cleaned file: size, extension,
    declared content type, and magic bytes.

    Shared by ``AttachmentField`` (classic form posts) and the AJAX
    staging endpoint so both paths enforce identical rules. Limits come
    from ``AttachmentField`` class attributes so tests can patch them in
    one place.
    """
    if cleaned_file.size > AttachmentField.max_upload_bytes:
        raise forms.ValidationError(
            _('Uploaded attachments must be no larger than %(limit)s MB.') % {'limit': AttachmentField.max_upload_bytes // (1024 * 1024)}
        )
    extension = os.path.splitext(os.path.basename(cleaned_file.name))[1].lower()
    if extension not in AttachmentField.allowed_extensions:
        raise forms.ValidationError(_('Unsupported attachment file type.'))
    if cleaned_file.content_type not in AttachmentField.allowed_content_types:
        raise forms.ValidationError(_('Unsupported attachment file type.'))
    if not file_matches_signature(extension, cleaned_file):
        raise forms.ValidationError(_('Attachment contents do not match its file type.'))


def file_matches_signature(extension: str, cleaned_file: Any) -> bool:
    expected_starts = FILE_SIGNATURES.get(extension)
    if expected_starts is None:
        return False
    try:
        cleaned_file.seek(0)
        head = cleaned_file.read(16)
        cleaned_file.seek(0)
    except (OSError, ValueError):
        return False
    offset_checks = FILE_SIGNATURE_OFFSETS.get(extension)
    if offset_checks:
        for offset, needle in offset_checks:
            if len(head) < offset + len(needle) or head[offset:offset + len(needle)] != needle:
                return False
        return True
    return any(head.startswith(expected) for expected in expected_starts)


class AttachmentField(forms.FileField):
    """OWASP-hardened multi-file upload field for unified attachments.

    Every uploaded file is checked against a size cap, an extension
    allow-list, a declared content-type allow-list, and its magic bytes so
    disguised executables or scripts are rejected before storage.
    """

    widget = MultipleFileInput
    max_upload_bytes = ATTACHMENT_MAX_UPLOAD_BYTES
    max_files = ATTACHMENT_MAX_FILES
    allowed_content_types = {
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'video/mp4',
        'video/webm',
        'video/quicktime',
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }
    allowed_extensions = {
        '.jpg', '.jpeg', '.png', '.gif', '.webp',
        '.mp4', '.webm', '.mov',
        '.pdf', '.doc', '.docx',
    }

    def clean(self, data: Any, initial: Any = None) -> list[Any]:
        if not data:
            return []

        candidates = list(data) if isinstance(data, (list, tuple)) else [data]
        cleaned_files: list[Any] = []
        for item in candidates:
            if item:
                cleaned_files.append(self._clean_upload(item, initial))
        if len(cleaned_files) > self.max_files:
            raise forms.ValidationError(_('No more than %(limit)s attachments may be uploaded at once.') % {'limit': self.max_files})
        return cleaned_files

    def _clean_upload(self, data: Any, initial: Any = None) -> Any:
        cleaned_file = super().clean(data, initial)
        if cleaned_file is None:
            return None
        validate_uploaded_file(cleaned_file)
        return cleaned_file


class StagedAttachmentsMixin(forms.Form):
    """Hidden field carrying IDs of files uploaded through the AJAX staging
    endpoint before the parent form is submitted.

    Only attachments that are still staged (no parent) *and* owned by the
    submitting user are accepted, so one member cannot claim another
    member's staged uploads. Requires the form constructor to receive
    ``user=request.user``.
    """

    staged_attachments = forms.CharField(required=False, widget=forms.HiddenInput)
    user: Any = None

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        if user is not None:
            self.user = user
        super().__init__(*args, **kwargs)

    def clean_staged_attachments(self) -> list[Any]:
        from shop.models.attachment import Attachment

        raw = self.cleaned_data.get('staged_attachments') or ''
        unique_ids = list(dict.fromkeys(int(part) for part in str(raw).split(',') if part.strip().isdigit()))
        if not unique_ids:
            return []
        user = self.user
        if user is None or not getattr(user, 'is_authenticated', False):
            raise forms.ValidationError(_('Uploaded files could not be matched to your session. Upload them again.'))
        staged_by_pk = {
            attachment.pk: attachment
            for attachment in Attachment.objects.filter(pk__in=unique_ids, object_id='', uploaded_by=user)
        }
        if len(staged_by_pk) != len(unique_ids):
            raise forms.ValidationError(_('Some uploaded files are no longer available. Remove them and upload again.'))
        staged = [staged_by_pk[pk] for pk in unique_ids]
        direct_uploads = self.files.getlist('attachments')
        total = len(staged) + len(direct_uploads)
        if total > AttachmentField.max_files:
            raise forms.ValidationError(_('No more than %(limit)s attachments may be uploaded at once.') % {'limit': AttachmentField.max_files})
        return staged
