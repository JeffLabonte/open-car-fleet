from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from shop.models.car import Car
from shop.models.garage import KnownShop


class WorkJob(models.Model):
    """A planned maintenance or repair job for a car.

    Tracks planning, assignment, required items and completion status.
    """

    URGENCY_CHOICES = [
        ("soon", _("Planned Very Soon")),
        ("ahead", _("Planned Ahead")),
    ]

    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE = "done"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, _("Pending")),
        (STATUS_IN_PROGRESS, _("In Progress")),
        (STATUS_DONE, _("Done")),
        (STATUS_CANCELLED, _("Cancelled")),
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

            raise ValidationError({"assigned_to": _("Assigned user must be a mechanic.")})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.title} [{self.get_urgency_display()}] for {self.car}"
