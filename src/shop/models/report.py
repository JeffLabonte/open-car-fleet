from django.db import models
from django.conf import settings

from .car import Car
from .garage import KnownShop


class Report(models.Model):
    """A historical report for work done on a car.

    - `job_name`: the name/title of the work performed
    - `date_done`: date when the work was completed
    - `documents`: list of URLs or paths to documents (stored as JSON)
    - `photos`: list of URLs or paths to photos (stored as JSON)
    - `note`: freeform note about the work
    """

    car = models.ForeignKey(Car, related_name="reports", on_delete=models.CASCADE)
    mileage = models.PositiveIntegerField(null=True, blank=True) 
    job_name = models.CharField(max_length=200)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_reports",
    )
    assigned_shop = models.ForeignKey(
        KnownShop,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports",
    )
    date_done = models.DateField()
    documents = models.JSONField(default=list, blank=True)
    photos = models.JSONField(default=list, blank=True)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~(models.Q(assigned_to__isnull=False) & models.Q(assigned_shop__isnull=False)),
                name="report_single_assignment_target",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.assigned_to and not getattr(self.assigned_to, "is_mechanic", False):
            from django.core.exceptions import ValidationError

            raise ValidationError({"assigned_to": "Assigned user must be a mechanic."})

    def __str__(self) -> str:
        return f"{self.job_name} on {self.date_done} for {self.car}"
