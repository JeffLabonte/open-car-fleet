from django.db import models
from django.utils.translation import gettext_lazy as _

from shop.models.inspection import Inspection


class InspectionPoint(models.Model):
    """One verification item inside a structured inspection."""

    STATUS_PASS = "pass"
    STATUS_ATTENTION = "attention"
    STATUS_REPAIR = "repair"
    STATUS_NA = "na"

    STATUS_CHOICES = [
        (STATUS_PASS, _("OK / Pass")),
        (STATUS_ATTENTION, _("Attention")),
        (STATUS_REPAIR, _("Needs repair")),
        (STATUS_NA, _("N/A")),
    ]

    inspection = models.ForeignKey(
        Inspection,
        related_name="points",
        on_delete=models.CASCADE,
    )
    category = models.CharField(max_length=50)
    category_label = models.CharField(max_length=200, blank=True)
    code = models.CharField(max_length=50)
    label = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NA,
    )
    measurement = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["inspection", "code"],
                name="inspection_point_unique_code",
            )
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.get_status_display()})"
