from django.db import models
from django.conf import settings
from .car import Car
from .garage import KnownShop


class WorkJob(models.Model):
    """A planned maintenance or repair job for a car.

    Tracks planning, assignment, required items and completion status.
    """

    URGENCY_CHOICES = [
        ("soon", "Planned Very Soon"),
        ("ahead", "Planned Ahead"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("done", "Done"),
        ("cancelled", "Cancelled"),
    ]

    car = models.ForeignKey(Car, related_name="work_jobs", on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    maintenance_type = models.CharField(max_length=50, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_work_jobs",
    )
    assigned_shop = models.ForeignKey(
        KnownShop,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_jobs",
    )
    planned_date = models.DateField(null=True, blank=True)
    is_done = models.BooleanField(default=False)
    done_date = models.DateField(null=True, blank=True)
    required_items = models.JSONField(default=list, blank=True)
    urgency = models.CharField(max_length=10, choices=URGENCY_CHOICES, default="ahead")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~(models.Q(assigned_to__isnull=False) & models.Q(assigned_shop__isnull=False)),
                name="workjob_single_assignment_target",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.assigned_to and not getattr(self.assigned_to, "is_mechanic", False):
            from django.core.exceptions import ValidationError

            raise ValidationError({"assigned_to": "Assigned user must be a mechanic."})

    def mark_done(self) -> None:
        """Convenience helper to mark job done and set done_date/status."""
        if not self.is_done:
            self.is_done = True
            from django.utils import timezone

            self.done_date = timezone.now().date()
            self.status = "done"
            self.save()

    def __str__(self) -> str:
        return f"{self.title} [{self.get_urgency_display()}] for {self.car}"
