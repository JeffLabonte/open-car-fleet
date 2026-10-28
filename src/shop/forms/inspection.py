from typing import Any
from urllib.parse import urlparse

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from shop.forms.base import AttachmentField, MultipleFileInput, StagedAttachmentsMixin
from shop.models.inspection import Inspection


class InspectionForm(StagedAttachmentsMixin, forms.ModelForm):
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
        fields = ["inspected_at", "mileage", "notes"]
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
        self.order_fields(
            [name for name in self.fields if name not in ("external_links", "attachments")]
            + [name for name in ("external_links", "attachments") if name in self.fields]
        )

    def clean_external_links(self) -> list[str]:
        raw = self.cleaned_data.get("external_links", "")
        links = [item.strip() for item in raw.splitlines() if item.strip()]
        for link in links:
            parsed = urlparse(link)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise forms.ValidationError(_("External links must use HTTP or HTTPS."))
        return links
