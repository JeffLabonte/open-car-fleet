import os
from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from shop.models.garage import KnownShop

# Per-file upload ceiling for unified attachments (25 MB).
ATTACHMENT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
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
        if cleaned_file.size > self.max_upload_bytes:
            raise forms.ValidationError(
                _('Uploaded attachments must be no larger than %(limit)s MB.') % {'limit': self.max_upload_bytes // (1024 * 1024)}
            )
        extension = os.path.splitext(os.path.basename(cleaned_file.name))[1].lower()
        if extension not in self.allowed_extensions:
            raise forms.ValidationError(_('Unsupported attachment file type.'))
        if cleaned_file.content_type not in self.allowed_content_types:
            raise forms.ValidationError(_('Unsupported attachment file type.'))
        if not self._matches_file_signature(extension, cleaned_file):
            raise forms.ValidationError(_('Attachment contents do not match its file type.'))
        return cleaned_file

    def _matches_file_signature(self, extension: str, cleaned_file: Any) -> bool:
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
