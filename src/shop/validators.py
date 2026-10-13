import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


VIN_BAD_CHARS = set("IOQ")


def validate_vin(value: str | None) -> str | None:
    """Normalize and validate a Vehicle Identification Number.

    Returns the normalized VIN (uppercase, no whitespace) or ``None`` when
    the input is empty. Raises ``ValidationError`` for invalid characters or
    length.
    """
    if value is None:
        return None

    vin = str(value).strip().upper()
    vin = re.sub(r"\s+", "", vin)
    if not vin:
        return None

    if any(ch in VIN_BAD_CHARS for ch in vin):
        raise ValidationError(_("VIN contains invalid characters (I, O, Q are not allowed)."))

    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{11,17}", vin):
        raise ValidationError(_("VIN must be 11-17 alphanumeric characters (no I/O/Q)."))

    return vin


def validate_license_plate(value: str | None) -> str:
    """Normalize and validate a license plate.

    Returns the normalized plate (uppercase, stripped) or an empty string when
    the input is empty. Raises ``ValidationError`` for invalid characters or
    excessive length.
    """
    if value is None:
        return ""

    plate = str(value).strip().upper()
    if not plate:
        return ""

    if len(plate) > 20:
        raise ValidationError(_("License plate must be 20 characters or fewer."))

    if not re.fullmatch(r"[A-Z0-9 \-]+", plate):
        raise ValidationError(_("License plate contains invalid characters."))

    return plate
