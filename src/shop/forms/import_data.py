from typing import Any

from django import forms
from django.core.exceptions import ValidationError


class BaseImportForm(forms.Form):
    import_file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"class": "input", "accept": ".json,application/json"}),
        help_text="Upload a normalized UTF-8 JSON file. See the README for the exact schema and examples.",
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Validate the file without saving imported records.",
    )

    max_upload_size = 5 * 1024 * 1024

    def clean_import_file(self) -> Any:
        uploaded_file = self.cleaned_data["import_file"]
        file_name = getattr(uploaded_file, "name", "")
        if not file_name.lower().endswith(".json"):
            raise ValidationError("Upload a JSON file ending in .json.")
        if uploaded_file.size > self.max_upload_size:
            raise ValidationError("Upload a JSON file smaller than 5 MB.")
        return uploaded_file


class GarageImportForm(BaseImportForm):
    pass


class CarImportForm(BaseImportForm):
    IMPORT_CHOICES = [
        ("workjob", "Work jobs"),
        ("report", "Reports"),
    ]

    import_type = forms.ChoiceField(
        choices=IMPORT_CHOICES,
        widget=forms.Select(attrs={"class": "input"}),
        help_text="Choose whether this file contains work jobs or reports for this car. The selected car is applied automatically.",
    )