import re
from datetime import date
from typing import Any

from django import forms
from django.core.exceptions import ValidationError

from shop.models.car import Car


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


CarCreateForm = CarBaseForm
CarUpdateForm = CarBaseForm
