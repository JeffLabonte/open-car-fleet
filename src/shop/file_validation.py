from __future__ import annotations

from typing import TypeVar

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile


TUploadedFile = TypeVar('TUploadedFile', bound=UploadedFile)
MAX_PDF_UPLOAD_BYTES = 10 * 1024 * 1024


def validate_pdf_upload(
    uploaded_file: TUploadedFile | object | None,
    *,
    message: str,
) -> TUploadedFile | object | None:
    """Validate PDF extension, declared type, size, and magic bytes."""
    if uploaded_file is None or not isinstance(uploaded_file, UploadedFile):
        return uploaded_file

    if uploaded_file.size > MAX_PDF_UPLOAD_BYTES:
        raise ValidationError(f'{message} Files must be no larger than 10 MB.')
    if uploaded_file.content_type != 'application/pdf' or not uploaded_file.name.lower().endswith('.pdf'):
        raise ValidationError(message)

    uploaded_file.seek(0)
    header = uploaded_file.read(5)
    uploaded_file.seek(0)
    if header != b'%PDF-':
        raise ValidationError(message)
    return uploaded_file
