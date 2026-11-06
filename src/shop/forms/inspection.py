import re
from typing import Any
from urllib.parse import urlparse

from django import forms
from django.forms.models import inlineformset_factory
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from shop.forms.base import AttachmentField, MultipleFileInput, StagedAttachmentsMixin
from shop.inspection_checklist import flatten_checklist, validation_rule_for_code
from shop.models.inspection import Inspection
from shop.models.inspection_point import InspectionPoint


class InspectionForm(StagedAttachmentsMixin, forms.ModelForm):
    enabled_categories = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )
    attachments = AttachmentField(
        required=False,
        widget=MultipleFileInput(
            attrs={
                "accept": "image/*,video/*,.pdf,.doc,.docx",
                "capture": "environment",
            }
        ),
        help_text=_("Upload inspection photos or documents."),
    )
    external_links = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "textarea",
                "rows": 3,
                "placeholder": _("One external document link per line"),
            }
        ),
        help_text=_("Add one external document link per line."),
    )

    class Meta:
        model = Inspection
        fields = ["inspected_at", "mileage", "notes", "enabled_categories"]
        widgets = {
            "inspected_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"class": "input", "type": "datetime-local"},
            ),
            "mileage": forms.NumberInput(attrs={"class": "input", "placeholder": _("Mileage at inspection")}),
            "notes": forms.Textarea(
                attrs={"class": "textarea", "rows": 7, "placeholder": _("Write the inspection findings here")}
            ),
        }
        labels = {
            "inspected_at": _("Inspection date and time (UTC)"),
            "mileage": _("Mileage"),
            "notes": _("Inspection findings"),
            "attachments": _("Photos and documents"),
            "external_links": _("External documents"),
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        self.user = user
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.instance.pk:
            self.fields["inspected_at"].initial = timezone.localtime(timezone.now()).replace(second=0, microsecond=0)
        # Persist enabled categories as JSON in a hidden input.
        # For inspections created before this feature, default to all categories
        # that already have points so we don't accidentally discard data.
        if not self.is_bound:
            if self.instance.pk and self.instance.points.exists() and not self.instance.enabled_categories:
                self.fields["enabled_categories"].initial = list(
                    dict.fromkeys(point.category for point in self.instance.points.all())
                )
            else:
                self.fields["enabled_categories"].initial = self.instance.enabled_categories or []
        self.order_fields(
            [name for name in self.fields if name not in ("external_links", "attachments", "enabled_categories")]
            + [name for name in ("external_links", "attachments", "enabled_categories") if name in self.fields]
        )

    def clean_enabled_categories(self) -> list[str]:
        raw = self.cleaned_data.get("enabled_categories", "")
        if not raw:
            return []
        try:
            import json

            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise forms.ValidationError(_("Enabled categories must be valid JSON.")) from exc
        if not isinstance(value, list):
            raise forms.ValidationError(_("Enabled categories must be a list."))
        return [str(item) for item in value]

    def clean_external_links(self) -> list[str]:
        raw = self.cleaned_data.get("external_links", "")
        links = [item.strip() for item in raw.splitlines() if item.strip()]
        for link in links:
            parsed = urlparse(link)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise forms.ValidationError(_("External links must use HTTP or HTTPS."))
        return links


class InspectionPointForm(forms.ModelForm):
    class Meta:
        model = InspectionPoint
        fields = ["status", "measurement", "notes"]
        widgets = {
            "status": forms.Select(attrs={"class": "input"}),
            "measurement": forms.TextInput(
                attrs={"class": "input", "placeholder": _("Size / pressure / spec / measurement")}
            ),
            "notes": forms.Textarea(attrs={"class": "textarea", "rows": 2, "placeholder": _("Notes for this item")}),
        }
        labels = {
            "status": _("Status"),
            "measurement": _("Measurement / spec"),
            "notes": _("Notes"),
        }

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        status = cleaned.get("status")
        measurement = cleaned.get("measurement", "")
        code = self.instance.code if self.instance else None
        rule = validation_rule_for_code(code) if code else None

        if not rule:
            return cleaned

        # N/A points do not require a measurement, but if one is provided it must be valid.
        if status == InspectionPoint.STATUS_NA and not measurement:
            return cleaned

        if status != InspectionPoint.STATUS_NA and not measurement:
            self.add_error(
                "measurement",
                _("A measurement is required when the status is not N/A."),
            )
            return cleaned

        error, normalized = _validate_measurement(measurement, rule)
        if error:
            self.add_error("measurement", error)
        else:
            cleaned["measurement"] = normalized

        return cleaned


def _validate_measurement(value: str, rule: str) -> tuple[str | None, str]:
    """Validate a measurement and return (error_message, normalized_value).

    The normalized value is the canonical form that should be stored.
    """
    value = value.strip()
    if not value:
        return None, value

    if rule.startswith("choice:"):
        groups = [group.strip() for group in rule.split(":", 1)[1].split(",")]
        canonical_map: dict[str, str] = {}
        display_choices: list[str] = []
        for group in groups:
            aliases = [alias.strip() for alias in group.split("|")]
            canonical = aliases[0]
            display_choices.append(canonical)
            for alias in aliases:
                canonical_map[alias.lower()] = canonical

        lowered = value.lower()
        if lowered not in canonical_map:
            return (
                _("Must be one of: %(choices)s") % {"choices": ", ".join(display_choices)},
                value,
            )
        return None, canonical_map[lowered]

    if rule == "tire_size":
        if not re.match(r"^\d{2,4}/\d{2,3}[A-Z]?\d{2}$", value):
            return _("Enter a tire size such as 225/45R17."), value
        return None, value.upper()

    if rule.startswith("numeric:"):
        unit = rule.split(":", 1)[1]
        error = _validate_numeric(value, unit)
        return error, value

    return None, value


def _validate_numeric(value: str, unit: str) -> str | None:
    """Validate a numeric measurement with an optional unit suffix."""
    patterns = {
        "mm": (r"^(\d+(\.\d+)?)\s*(mm)?$", _("Enter a value in millimetres, e.g. 5.5 or 5.5mm.")),
        "psi": (r"^(\d+(\.\d+)?)\s*(psi)?$", _("Enter a value in PSI, e.g. 32 or 32 psi.")),
        "32nds": (r"^(\d+(\.\d+)?)\s*(/32)?$", _("Enter a tread depth in 1/32, e.g. 6 or 6/32.")),
        "percent": (r"^(\d{1,3})\s*(%)?$", _("Enter a percentage between 0 and 100.")),
    }

    if unit not in patterns:
        return None

    pattern, error_message = patterns[unit]
    match = re.match(pattern, value, re.IGNORECASE)
    if not match:
        return error_message

    if unit == "percent":
        number = int(match.group(1))
        if not 0 <= number <= 100:
            return error_message

    return None


InspectionPointFormSet = inlineformset_factory(
    Inspection,
    InspectionPoint,
    form=InspectionPointForm,
    extra=0,
    can_delete=False,
    can_order=False,
)


def create_inspection_points(inspection: Inspection) -> None:
    """Create all checklist points for a newly-structured inspection."""
    points = [
        InspectionPoint(
            inspection=inspection,
            category=item["category"],
            category_label=item["category_label"],
            code=item["code"],
            label=item["label"],
            position=item["position"],
        )
        for item in flatten_checklist()
    ]
    InspectionPoint.objects.bulk_create(points)
