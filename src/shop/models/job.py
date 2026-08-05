from django.db import models
from django.conf import settings
from .car import Car


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
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    planned_date = models.DateField(null=True, blank=True)
    is_done = models.BooleanField(default=False)
    done_date = models.DateField(null=True, blank=True)
    required_items = models.JSONField(default=list, blank=True)
    urgency = models.CharField(max_length=10, choices=URGENCY_CHOICES, default="ahead")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def mark_done(self):
        """Convenience helper to mark job done and set done_date/status."""
        if not self.is_done:
            self.is_done = True
            from django.utils import timezone

            self.done_date = timezone.now().date()
            self.status = "done"
            self.save()

    def __str__(self):
        return f"{self.title} [{self.get_urgency_display()}] for {self.car}"
