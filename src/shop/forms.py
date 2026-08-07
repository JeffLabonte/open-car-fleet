import re
from datetime import date
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from .models.car import Car
from .models.garage import Garage, KnownShop
from .models.job import WorkJob
from .models.report import Report


VIN_BAD_CHARS = set('IOQ')


class CarBaseForm(forms.ModelForm):
    class Meta:
        model = Car
        fields = ['garage', 'usual_name', 'make', 'model', 'year', 'mileage', 'vin', 'license_plate']
        widgets = {
            'garage': forms.Select(attrs={'class': 'input'}),
            'usual_name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Optional nickname'}),
            'make': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Make'}),
            'model': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Model'}),
            'year': forms.NumberInput(attrs={'class': 'input', 'placeholder': 'Year'}),
            'mileage': forms.NumberInput(attrs={'class': 'input', 'placeholder': 'Mileage'}),
            'vin': forms.TextInput(attrs={'class': 'input', 'placeholder': 'VIN'}),
            'license_plate': forms.TextInput(attrs={'class': 'input', 'placeholder': 'License plate'}),
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._user = user
        if user is not None:
            self.fields['garage'].queryset = user.garages.order_by('name')

    def clean_garage(self):
        garage = self.cleaned_data.get('garage')
        if garage is None:
            return garage

        if self._user is not None and not self._user.garages.filter(pk=garage.pk).exists():
            raise ValidationError('You can only select a garage you are a member of.')
        return garage

    def clean_year(self) -> int | None:
        year = self.cleaned_data.get('year')
        if year is None:
            return year
        current = date.today().year
        if year < 1886 or year > current + 1:
            raise ValidationError('Enter a realistic year between 1886 and %(max)d.', params={'max': current + 1})
        return year

    def clean_vin(self) -> str | None:
        vin = self.cleaned_data.get('vin')
        if not vin:
            return vin
        vin = re.sub(r"\s+", "", vin).upper()
        if any(ch in VIN_BAD_CHARS for ch in vin):
            raise ValidationError('VIN contains invalid characters (I, O, Q are not allowed).')
        if not re.match(r'^[A-HJ-NPR-Z0-9]{11,17}$', vin):
            raise ValidationError('VIN must be 11–17 alphanumeric characters (no I/O/Q).')
        # Ensure uniqueness — exclude self when updating
        qs = Car.objects.filter(vin=vin)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('A car with this VIN already exists.')
        return vin

    def clean_license_plate(self) -> str:
        plate = self.cleaned_data.get('license_plate', '')
        plate = plate.strip().upper()
        if plate == '':
            return ''
        if len(plate) > 20:
            raise ValidationError('License plate must be 20 characters or fewer.')
        if not re.match(r'^[A-Z0-9 \-]+$', plate):
            raise ValidationError('License plate contains invalid characters.')
        return plate


class CarCreateForm(CarBaseForm):
    pass


class CarUpdateForm(CarBaseForm):
    pass


class GarageCreateForm(forms.ModelForm):
    class Meta:
        model = Garage
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Garage name'}),
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

class WorkJobForm(forms.ModelForm):
    required_items = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 3, 'placeholder': 'One item per line'}),
        help_text='Add one required item per line.',
    )

    class Meta:
        model = WorkJob
        fields = [
            'title',
            'maintenance_type',
            'assigned_to',
            'assigned_shop',
            'planned_date',
            'status',
            'is_done',
            'done_date',
            'urgency',
            'required_items',
            'notes',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Work title'}),
            'maintenance_type': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Maintenance type'}),
            'assigned_to': forms.Select(attrs={'class': 'input'}),
            'assigned_shop': forms.Select(attrs={'class': 'input'}),
            'planned_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'done_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'input'}),
            'urgency': forms.Select(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': 'Additional notes'}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = get_user_model().objects.filter(is_mechanic=True)
        self.fields['assigned_to'].help_text = 'Only users converted to mechanics can be selected.'
        self.fields['assigned_shop'].queryset = KnownShop.objects.order_by('name')
        self.fields['assigned_shop'].help_text = 'Assign to a known shop instead of a mechanic user.'
        if self.instance and self.instance.pk:
            self.fields['required_items'].initial = '\n'.join(self.instance.required_items or [])

    def clean_required_items(self) -> list[str]:
        raw = self.cleaned_data.get('required_items', '')
        items = [item.strip() for item in raw.splitlines() if item.strip()]
        return items

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        if cleaned_data.get('assigned_to') and cleaned_data.get('assigned_shop'):
            raise ValidationError('Assign either a mechanic user or a known shop, not both.')
        return cleaned_data

class ReportForm(forms.ModelForm):
    documents = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 3, 'placeholder': 'One document URL or path per line'}),
        help_text='Add one document URL or path per line.',
    )
    photos = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 3, 'placeholder': 'One photo URL or path per line'}),
        help_text='Add one photo URL or path per line.',
    )

    class Meta:
        model = Report
        fields = [
            'mileage',
            'job_name',
            'assigned_to',
            'assigned_shop',
            'date_done',
            'documents',
            'photos',
            'note',
        ]
        widgets = {
            'mileage': forms.NumberInput(attrs={'class': 'input', 'placeholder': 'Mileage at completion'}),
            'job_name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Work performed'}),
            'assigned_to': forms.Select(attrs={'class': 'input'}),
            'assigned_shop': forms.Select(attrs={'class': 'input'}),
            'date_done': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'note': forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': 'Notes about the work done'}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = get_user_model().objects.filter(is_mechanic=True)
        self.fields['assigned_to'].help_text = 'Only users converted to mechanics can be selected.'
        self.fields['assigned_shop'].queryset = KnownShop.objects.order_by('name')
        self.fields['assigned_shop'].help_text = 'Assign to a known shop instead of a mechanic user.'
        if self.instance and self.instance.pk:
            self.fields['documents'].initial = '\n'.join(self.instance.documents or [])
            self.fields['photos'].initial = '\n'.join(self.instance.photos or [])

    def clean_documents(self) -> list[str]:
        raw = self.cleaned_data.get('documents', '')
        return [item.strip() for item in raw.splitlines() if item.strip()]

    def clean_photos(self) -> list[str]:
        raw = self.cleaned_data.get('photos', '')
        return [item.strip() for item in raw.splitlines() if item.strip()]

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        if cleaned_data.get('assigned_to') and cleaned_data.get('assigned_shop'):
            raise ValidationError('Assign either a mechanic user or a known shop, not both.')
        return cleaned_data
