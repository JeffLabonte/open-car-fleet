from django import forms

from shop.models.garage import Garage


class GarageCreateForm(forms.ModelForm):
    class Meta:
        model = Garage
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Fleet name'}),
            'description': forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': 'Optional description'}),
        }


class GarageInviteForm(forms.Form):
    invited_email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'input', 'placeholder': 'member@example.com'}),
        help_text='We will email this person an invitation link.',
    )
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': 'Optional message'}),
    )
    expires_in_days = forms.IntegerField(
        min_value=1,
        max_value=90,
        initial=14,
        widget=forms.NumberInput(attrs={'class': 'input'}),
        help_text='Invitation expiry in days (1-90).',
    )

    def clean_invited_email(self) -> str:
        return self.cleaned_data['invited_email'].strip().lower()
