from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from shop.models.garage import Garage, GarageMembership


class FleetCreateForm(forms.ModelForm):
    class Meta:
        model = Garage
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input', 'placeholder': _('Fleet name')}),
            'description': forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': _('Optional description')})
        }


class FleetInviteForm(forms.Form):
    invited_email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'input', 'placeholder': 'member@example.com'}),
        help_text=_('We will email this person a fleet invitation link.'),
    )
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': _('Optional message')}),
    )
    expires_in_days = forms.IntegerField(
        min_value=1,
        max_value=90,
        initial=14,
        widget=forms.NumberInput(attrs={'class': 'input'}),
        help_text=_('Invitation expiry in days (1-90).'),
    )
    role = forms.ChoiceField(
        choices=GarageMembership.ROLE_CHOICES,
        initial=GarageMembership.ROLE_VIEWER,
        required=False,
        widget=forms.Select(attrs={'class': 'input'}),
        help_text=_('Role the invited user will receive after accepting.'),
    )

    def __init__(self, *args: object, allowed_roles: set[str] | None = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.allowed_roles = allowed_roles or {GarageMembership.ROLE_VIEWER}
        self.fields['role'].choices = [
            (value, label)
            for value, label in GarageMembership.ROLE_CHOICES
            if value in self.allowed_roles
        ]

    def clean_invited_email(self) -> str:
        return self.cleaned_data['invited_email'].strip().lower()

    def clean_role(self) -> str:
        role = self.cleaned_data.get('role')
        if role in (None, ''):
            return GarageMembership.ROLE_VIEWER
        if role not in self.allowed_roles:
            raise ValidationError(_('You cannot assign this role.'))
        return role


class GarageMembershipRoleForm(forms.Form):
    role = forms.ChoiceField(
        choices=GarageMembership.ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'input'}),
    )

    def __init__(self, *args: object, allowed_roles: set[str] | None = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.allowed_roles = allowed_roles or set()
        self.fields['role'].choices = [
            (value, label)
            for value, label in GarageMembership.ROLE_CHOICES
            if value in self.allowed_roles
        ]

    def clean_role(self) -> str:
        role = self.cleaned_data.get('role')
        if role not in self.allowed_roles:
            raise ValidationError(_('You cannot assign this role.'))
        return role


# Backward-compatible aliases used across existing views/tests.
GarageCreateForm = FleetCreateForm
GarageInviteForm = FleetInviteForm
