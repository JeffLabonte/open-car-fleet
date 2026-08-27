import re
from datetime import date
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from shop.models.car import Car, CarPart


VIN_BAD_CHARS = set('IOQ')


class CarPartForm(forms.ModelForm):
    class Meta:
        model = CarPart
        fields = ['name', 'status', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input', 'placeholder': _('Part or component name')}),
            'status': forms.Select(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': _('Notes about this part, including inspection or replacement details')}),
        }

    def clean_name(self) -> str:
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise ValidationError(_('Part name is required.'))
        return name


class CarBaseForm(forms.ModelForm):
    class Meta:
        model = Car
        fields = ['garage', 'usual_name', 'make', 'model', 'colour', 'year', 'mileage', 'vin', 'license_plate']
        widgets = {
            'garage': forms.Select(attrs={'class': 'input'}),
            'usual_name': forms.TextInput(attrs={'class': 'input', 'placeholder': _('Optional nickname')}),
            'make': forms.TextInput(attrs={'class': 'input', 'placeholder': _('Make')}),
            'model': forms.TextInput(attrs={'class': 'input', 'placeholder': _('Model')}),
            'colour': forms.TextInput(attrs={'class': 'input', 'placeholder': _('Colour')}),
            'year': forms.NumberInput(attrs={'class': 'input', 'placeholder': _('Year')}),
            'mileage': forms.NumberInput(attrs={'class': 'input', 'placeholder': _('Mileage')}),
            'vin': forms.TextInput(attrs={'class': 'input', 'placeholder': _('VIN')}),
            'license_plate': forms.TextInput(attrs={'class': 'input', 'placeholder': _('License plate')}),
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
            raise ValidationError(_('You can only select a garage you are a member of.'))
        return garage

    def clean_year(self) -> int | None:
        year = self.cleaned_data.get('year')
        if year is None:
            return year
        current = date.today().year
        if year < 1886 or year > current + 1:
            raise ValidationError(_('Enter a realistic year between 1886 and %(max)d.'), params={'max': current + 1})
        return year

    def clean_vin(self) -> str | None:
        vin = self.cleaned_data.get('vin')
        if not vin:
            return vin
        vin = re.sub(r"\s+", "", vin).upper()
        if any(ch in VIN_BAD_CHARS for ch in vin):
            raise ValidationError(_('VIN contains invalid characters (I, O, Q are not allowed).'))
        if not re.match(r'^[A-HJ-NPR-Z0-9]{11,17}$', vin):
            raise ValidationError(_('VIN must be 11-17 alphanumeric characters (no I/O/Q).'))
        qs = Car.objects.filter(vin=vin)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(_('A car with this VIN already exists.'))
        return vin

    def clean_license_plate(self) -> str:
        plate = self.cleaned_data.get('license_plate', '')
        plate = plate.strip().upper()
        if plate == '':
            return ''
        if len(plate) > 20:
            raise ValidationError(_('License plate must be 20 characters or fewer.'))
        if not re.match(r'^[A-Z0-9 \-]+$', plate):
            raise ValidationError(_('License plate contains invalid characters.'))
        return plate


CarCreateForm = CarBaseForm
CarUpdateForm = CarBaseForm
