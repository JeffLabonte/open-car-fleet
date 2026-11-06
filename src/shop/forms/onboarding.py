from django import forms
from django.utils.translation import gettext_lazy as _

from shop.auth import _build_username


class OnboardingForm(forms.Form):
    first_name = forms.CharField(
        label=_("First name"),
        max_length=150,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    last_name = forms.CharField(
        label=_("Last name"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    is_mechanic = forms.BooleanField(
        label=_("I am a mechanic"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "checkbox"}),
        help_text=_(
            "Enable mechanic mode to be assignable to work jobs and reports. You can change this later in your profile."
        ),
    )

    def clean_first_name(self) -> str:
        return self.cleaned_data.get("first_name", "").strip()

    def clean_last_name(self) -> str:
        return self.cleaned_data.get("last_name", "").strip()

    def clean(self) -> dict:
        cleaned_data = super().clean()
        first_name = cleaned_data.get("first_name", "").strip()
        last_name = cleaned_data.get("last_name", "").strip()

        if not first_name and not last_name:
            self.add_error("first_name", _("Please enter your first or last name."))

        return cleaned_data

    def build_username(self) -> str:
        first_name = self.cleaned_data.get("first_name", "").strip()
        last_name = self.cleaned_data.get("last_name", "").strip()
        base = f"{first_name} {last_name}".strip()
        return _build_username(base)
