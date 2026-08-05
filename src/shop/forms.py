import re
from datetime import date

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from .models.car import Car
from .models.job import WorkJob
from .models.report import Report


VIN_BAD_CHARS = set('IOQ')


class CarBaseForm(forms.ModelForm):
    class Meta:
        model = Car
        fields = ['usual_name', 'make', 'year', 'vin', 'license_plate']
        widgets = {
            'usual_name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Optional nickname'}),
            'make': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Make'}),
            'year': forms.NumberInput(attrs={'class': 'input', 'placeholder': 'Year'}),
            'vin': forms.TextInput(attrs={'class': 'input', 'placeholder': 'VIN'}),
            'license_plate': forms.TextInput(attrs={'class': 'input', 'placeholder': 'License plate'}),
        }

    def clean_year(self):
        year = self.cleaned_data.get('year')
        if year is None:
            return year
        current = date.today().year
        if year < 1886 or year > current + 1:
            raise ValidationError('Enter a realistic year between 1886 and %(max)d.', params={'max': current + 1})
        return year

    def clean_vin(self):
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

    def clean_license_plate(self):
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
            'planned_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'done_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'input'}),
            'urgency': forms.Select(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': 'Additional notes'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = get_user_model().objects.all()
        if self.instance and self.instance.pk:
            self.fields['required_items'].initial = '\n'.join(self.instance.required_items or [])

    def clean_required_items(self):
        raw = self.cleaned_data.get('required_items', '')
        items = [item.strip() for item in raw.splitlines() if item.strip()]
        return items

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
            'date_done',
            'documents',
            'photos',
            'note',
        ]
        widgets = {
            'mileage': forms.NumberInput(attrs={'class': 'input', 'placeholder': 'Mileage at completion'}),
            'job_name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Work performed'}),
            'date_done': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'note': forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': 'Notes about the work done'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['documents'].initial = '\n'.join(self.instance.documents or [])
            self.fields['photos'].initial = '\n'.join(self.instance.photos or [])

    def clean_documents(self):
        raw = self.cleaned_data.get('documents', '')
        return [item.strip() for item in raw.splitlines() if item.strip()]

    def clean_photos(self):
        raw = self.cleaned_data.get('photos', '')
        return [item.strip() for item in raw.splitlines() if item.strip()]
