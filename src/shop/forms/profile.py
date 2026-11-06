from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from shop.auth import _build_username


class ShopUserProfileForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = [
            "first_name",
            "last_name",
            "username",
            "email",
            "phone_number",
            "display_name",
            "is_mechanic",
        ]
        labels = {
            "first_name": _("First name"),
            "last_name": _("Last name"),
            "username": _("Username"),
            "email": _("Email"),
            "phone_number": _("Phone number"),
            "display_name": _("Display name"),
            "is_mechanic": _("Mechanic mode"),
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "input"}),
            "last_name": forms.TextInput(attrs={"class": "input"}),
            "username": forms.TextInput(attrs={"class": "input"}),
            "email": forms.EmailInput(attrs={"class": "input"}),
            "phone_number": forms.TextInput(attrs={"class": "input"}),
            "display_name": forms.TextInput(attrs={"class": "input"}),
            "is_mechanic": forms.CheckboxInput(attrs={"class": "checkbox"}),
        }
        help_texts = {
            "username": _("If left blank, your username will be set to your first and last name."),
            "phone_number": _("Optional."),
            "display_name": _("How your name appears in the app. If left blank, your username is used."),
            "is_mechanic": _("Enable mechanic mode to be assignable to work jobs and reports."),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["username"].required = False
        self.fields["email"].required = False
        self.fields["phone_number"].required = False
        self.fields["display_name"].required = False

    def clean_username(self) -> str:
        username = self.cleaned_data.get("username", "").strip()
        if username:
            # Check uniqueness excluding the current user.
            queryset = get_user_model().objects.filter(username=username)
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise forms.ValidationError(_("This username is already taken."))
        return username

    def clean_email(self) -> str:
        email = self.cleaned_data.get("email", "").strip().lower()
        if email:
            queryset = get_user_model().objects.filter(email__iexact=email)
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise forms.ValidationError(_("This email is already in use."))
        return email

    def clean(self) -> dict:
        cleaned_data = super().clean()
        first_name = (cleaned_data.get("first_name") or "").strip()
        last_name = (cleaned_data.get("last_name") or "").strip()
        username = (cleaned_data.get("username") or "").strip()

        if not username and not first_name and not last_name:
            self.add_error("first_name", _("Please enter your first or last name."))

        return cleaned_data

    def save(self, commit: bool = True):  # type: ignore[override]
        user = super().save(commit=False)

        first_name = (self.cleaned_data.get("first_name") or "").strip()
        last_name = (self.cleaned_data.get("last_name") or "").strip()
        username = (self.cleaned_data.get("username") or "").strip()

        if not username and (first_name or last_name):
            base = f"{first_name} {last_name}".strip()
            user.username = _build_username(base)

        was_mechanic = get_user_model().objects.filter(pk=user.pk, is_mechanic=True).exists() if user.pk else False
        if user.is_mechanic and not was_mechanic:
            user.mechanic_promoted_at = timezone.now()
        elif not user.is_mechanic:
            user.mechanic_promoted_at = None

        if commit:
            user.save()
        return user
