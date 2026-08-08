import uuid
from django.db import models

from shop.models.garage import Garage


class Car(models.Model):
    """A vehicle tracked by the shop.

    Fields:
    - id: UUID primary key
    - usual_name: short human-friendly name (e.g. "Daily Driver")
    - make: manufacturer / model name
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
    model = models.CharField(max_length=100)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    vin = models.CharField(max_length=50, unique=True, null=True, blank=True)
    license_plate = models.CharField(max_length=20, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.usual_name or self.make} ({self.license_plate or self.vin or self.id})"
