from datetime import date
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from shop.models.car import Car, CarPart
from shop.models.fleet import Fleet, FleetMembership
from shop.validators import validate_license_plate, validate_vin


class CarPartForm(forms.ModelForm):
    class Meta:
        model = CarPart
        fields = ["name", "status", "notes"]
        labels = {
            "name": _("Part name"),
            "status": _("Status"),
            "notes": _("Notes"),
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "input", "placeholder": _("Part or component name")}),
            "status": forms.Select(attrs={"class": "input"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "textarea",
                    "rows": 4,
                    "placeholder": _("Notes about this part, including inspection or replacement details"),
                }
            ),
        }

    def clean_name(self) -> str:
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise ValidationError(_("Part name is required."))
        return name


class CarForm(forms.ModelForm):
    class Meta:
        model = Car
        fields = ["fleet", "usual_name", "make", "model", "colour", "year", "vin", "license_plate", "mileage"]
        labels = {
            "fleet": _("Fleet"),
            "usual_name": _("Usual name"),
            "make": _("Make"),
            "model": _("Model"),
            "colour": _("Colour"),
            "year": _("Year"),
            "vin": _("VIN"),
            "license_plate": _("License plate"),
            "mileage": _("Odometer (km)"),
        }
        widgets = {
            "fleet": forms.Select(attrs={"class": "input"}),
            "usual_name": forms.TextInput(attrs={"class": "input", "placeholder": _("Optional nickname")}),
            "make": forms.TextInput(attrs={"class": "input", "placeholder": _("Make")}),
            "model": forms.TextInput(attrs={"class": "input", "placeholder": _("Model")}),
            "colour": forms.TextInput(attrs={"class": "input", "placeholder": _("Colour")}),
            "year": forms.NumberInput(attrs={"class": "input", "placeholder": _("Year")}),
            "vin": forms.TextInput(attrs={"class": "input", "placeholder": _("VIN")}),
            "license_plate": forms.TextInput(attrs={"class": "input", "placeholder": _("License plate")}),
            "mileage": forms.NumberInput(attrs={"class": "input", "placeholder": _("Odometer (km)")}),
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._user = user
        if user is not None:
            self.fields["fleet"].queryset = (
                Fleet.objects.filter(
                    memberships__user=user,
                    memberships__role__in=FleetMembership.WRITE_DATA_ROLES,
                )
                .distinct()
                .order_by("name")
            )

    def clean_fleet(self):
        fleet = self.cleaned_data.get("fleet")
        if fleet is None:
            return fleet

        if self._user is not None:
            writable = Fleet.objects.filter(
                memberships__user=self._user,
                memberships__role__in=FleetMembership.WRITE_DATA_ROLES,
                pk=fleet.pk,
            ).exists()
            if not writable:
                raise ValidationError(_("You can only select a fleet you can edit."))
        return fleet

    def clean_year(self) -> int | None:
        year = self.cleaned_data.get("year")
        if year is None:
            return year
        current = date.today().year
        if year < 1886 or year > current + 1:
            raise ValidationError(_("Enter a realistic year between 1886 and %(max)d."), params={"max": current + 1})
        return year

    def clean_vin(self) -> str | None:
        vin = validate_vin(self.cleaned_data.get("vin"))
        if not vin:
            return vin
        qs = Car.objects.filter(vin=vin)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(_("A car with this VIN already exists."))
        return vin

    def clean_license_plate(self) -> str:
        return validate_license_plate(self.cleaned_data.get("license_plate", ""))


# Backward-compatible aliases used across existing views/tests.
CarBaseForm = CarForm
CarCreateForm = CarForm
CarUpdateForm = CarForm
