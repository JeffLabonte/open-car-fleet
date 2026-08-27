import uuid
from django.core.validators import MinLengthValidator
from django.db import models

from shop.models.garage import Garage


class CarPart(models.Model):
    """A tracked part or component on a car with a current status."""

    STATUS_NEW = "new"
    STATUS_ORDERED = "ordered"
    STATUS_PENDING = "pending"
    STATUS_REPAIRED = "repaired"
    STATUS_REPLACED = "replaced"
    STATUS_AVAILABLE = "available"

    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_ORDERED, "Ordered"),
        (STATUS_PENDING, "Pending"),
        (STATUS_REPAIRED, "Repaired"),
        (STATUS_REPLACED, "Replaced"),
        (STATUS_AVAILABLE, "Available"),
    ]

    car = models.ForeignKey("Car", related_name="parts", on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_NEW)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "created_at"]

    def save(self, *args, **kwargs):
        auto_history = kwargs.pop("auto_history", True)
        previous_status = ""
        if self.pk:
            previous_status = CarPart.objects.filter(pk=self.pk).values_list("status", flat=True).first() or ""
        super().save(*args, **kwargs)
        if auto_history and (self.pk is None or previous_status != self.status):
            CarPartStatusHistory.objects.create(
                part=self,
                previous_status=previous_status,
                new_status=self.status,
            )

    def update_status(self, status: str, note: str = "", *, save: bool = True) -> "CarPartStatusHistory":
        previous_status = self.status
        self.status = status
        if note:
            self.notes = note if not self.notes else f"{self.notes.strip()}\n{note.strip()}"
        if save:
            self.save(auto_history=False)
        history = CarPartStatusHistory.objects.create(
            part=self,
            previous_status=previous_status,
            new_status=self.status,
            note=note,
        )
        return history

    def __str__(self) -> str:
        return f"{self.name} ({self.get_status_display()}) for {self.car}"


class CarPartStatusHistory(models.Model):
    """Audit trail of every status change for a car part."""

    part = models.ForeignKey(CarPart, related_name="status_history", on_delete=models.CASCADE)
    previous_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30)
    note = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.part.name}: {self.previous_status or 'initial'} -> {self.new_status}"


class Car(models.Model):
    """A vehicle tracked by the shop.

    Fields:
    - id: UUID primary key
    - usual_name: short human-friendly name (e.g. "Daily Driver")
    - make: manufacturer / model name
    - colour: required paint colour
    - year: production year
    - vin: vehicle identification number
    - license_plate: registration plate
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    garage = models.ForeignKey(
        Garage,
        on_delete=models.CASCADE,
        related_name="cars",
    )
    mileage = models.PositiveIntegerField(null=True, blank=True)
    usual_name = models.CharField(max_length=200, blank=True)
    make = models.CharField(max_length=100)
    colour = models.CharField(max_length=50, blank=True, validators=[MinLengthValidator(1)])
    model = models.CharField(max_length=100)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    vin = models.CharField(max_length=50, unique=True, null=True, blank=True)
    license_plate = models.CharField(max_length=20, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.usual_name or self.make} ({self.license_plate or self.vin or self.id})"
