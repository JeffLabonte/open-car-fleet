from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models.deletion import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from shop.models.attachment import Attachment
from shop.models.car import Car


class InspectionQuerySet(models.QuerySet):
    def latest_for_car(self, car: Car) -> "Inspection | None":
        return self.filter(car=car).order_by(*Inspection.LATEST_ORDERING).first()

    def delete(self):
        raise ProtectedError(_("Inspection history cannot be deleted."), set())


class Inspection(models.Model):
    """A timestamped inspection event for a vehicle.

    Inspections are historical records.  The vehicle detail page deliberately
    renders only the newest event, while the inspection history page renders
    every event for the vehicle.
    """

    LATEST_ORDERING = ("-inspected_at", "-created_at", "-pk")

    car = models.ForeignKey(
        Car,
        related_name="inspections",
        on_delete=models.PROTECT,
    )
    inspected_at = models.DateTimeField(default=timezone.now)
    mileage = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    enabled_categories = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Enabled checklist categories"),
        help_text=_("Categories the mechanic chose to fill for this inspection."),
    )
    is_draft = models.BooleanField(
        default=False,
        verbose_name=_("Draft"),
        help_text=_("Draft inspections can be edited and deleted until finalized."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_inspections",
    )
    attachments = GenericRelation(Attachment)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = InspectionQuerySet.as_manager()

    class Meta:
        ordering = ["-inspected_at", "-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["car", "-inspected_at", "-created_at", "-id"],
                name="inspection_latest_idx",
            )
        ]

    def __str__(self) -> str:
        return f"Inspection of {self.car} on {self.inspected_at}"

    def point_status_counts(self) -> dict[str, int]:
        """Return counts of each point status for structured inspections."""
        from shop.models.inspection_point import InspectionPoint

        counts = {status: 0 for status, _ in InspectionPoint.STATUS_CHOICES}
        if not self.pk:
            return counts
        for point in self.points.only("status"):
            counts[point.status] = counts.get(point.status, 0) + 1
        return counts

    def delete(self, *args, **kwargs):
        if not self.is_draft:
            raise ProtectedError(_("Inspection history cannot be deleted."), {self})
        super().delete(*args, **kwargs)


@receiver(pre_delete, sender=Inspection)
def prevent_inspection_delete(sender, instance: Inspection, **kwargs: object) -> None:
    """Protect queryset and cascading deletes as well as instance deletes.

    Drafts are allowed to be deleted before they are finalized.
    """
    if not instance.is_draft:
        raise ProtectedError(_("Inspection history cannot be deleted."), {instance})
