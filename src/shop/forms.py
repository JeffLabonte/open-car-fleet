import re
from datetime import date

from django import forms
from django.core.exceptions import ValidationError

from .models.car import Car


VIN_BAD_CHARS = set('IOQ')


class CarBaseForm(forms.ModelForm):
    class Meta:
        model = Car
        fields = ['usual_name', 'make', 'year', 'vin', 'license_plate']

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
