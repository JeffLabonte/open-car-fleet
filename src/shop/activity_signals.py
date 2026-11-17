from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone

from car_docs.models import CarDoc
from shop.models.attachment import Attachment
from shop.models.car import Car, CarPart
from shop.models.inspection import Inspection
from shop.models.inspection_point import InspectionPoint
from shop.models.job import WorkJob
from shop.models.report import Report


def _touch_car(car_id: Any) -> None:
    if car_id is not None:
        Car.objects.filter(pk=car_id).update(updated_at=timezone.now())


def _touch_attachment_parent(attachment: Attachment) -> None:
    if attachment.content_type_id is None or not attachment.object_id:
        return

    parent_model = attachment.content_type.model_class()
    if parent_model is CarDoc:
        car_id = CarDoc.objects.filter(pk=attachment.object_id).values_list("car_id", flat=True).first()
    elif parent_model is Report:
        car_id = Report.objects.filter(pk=attachment.object_id).values_list("car_id", flat=True).first()
    elif parent_model is Inspection:
        car_id = Inspection.objects.filter(pk=attachment.object_id).values_list("car_id", flat=True).first()
    else:
        car_id = None
    _touch_car(car_id)


@receiver(post_save, sender=CarDoc)
def touch_car_for_document(sender: type[CarDoc], instance: CarDoc, **kwargs: object) -> None:
    _touch_car(instance.car_id)


@receiver(pre_delete, sender=CarDoc)
def touch_car_before_document_delete(sender: type[CarDoc], instance: CarDoc, **kwargs: object) -> None:
    _touch_car(instance.car_id)


@receiver(post_save, sender=WorkJob)
def touch_car_for_work_job(sender: type[WorkJob], instance: WorkJob, **kwargs: object) -> None:
    _touch_car(instance.car_id)


@receiver(pre_delete, sender=WorkJob)
def touch_car_before_work_job_delete(sender: type[WorkJob], instance: WorkJob, **kwargs: object) -> None:
    _touch_car(instance.car_id)


@receiver(post_save, sender=Report)
def touch_car_for_report(sender: type[Report], instance: Report, **kwargs: object) -> None:
    _touch_car(instance.car_id)


@receiver(pre_delete, sender=Report)
def touch_car_before_report_delete(sender: type[Report], instance: Report, **kwargs: object) -> None:
    _touch_car(instance.car_id)


@receiver(post_save, sender=Inspection)
def touch_car_for_inspection(sender: type[Inspection], instance: Inspection, **kwargs: object) -> None:
    _touch_car(instance.car_id)


@receiver(pre_delete, sender=Inspection)
def touch_car_before_inspection_delete(sender: type[Inspection], instance: Inspection, **kwargs: object) -> None:
    _touch_car(instance.car_id)


@receiver(post_save, sender=InspectionPoint)
def touch_car_for_inspection_point(sender: type[InspectionPoint], instance: InspectionPoint, **kwargs: object) -> None:
    car_id = Inspection.objects.filter(pk=instance.inspection_id).values_list("car_id", flat=True).first()
    _touch_car(car_id)


@receiver(pre_delete, sender=InspectionPoint)
def touch_car_before_inspection_point_delete(
    sender: type[InspectionPoint], instance: InspectionPoint, **kwargs: object
) -> None:
    car_id = Inspection.objects.filter(pk=instance.inspection_id).values_list("car_id", flat=True).first()
    _touch_car(car_id)


@receiver(post_save, sender=CarPart)
def touch_car_for_part(sender: type[CarPart], instance: CarPart, **kwargs: object) -> None:
    _touch_car(instance.car_id)


@receiver(pre_delete, sender=CarPart)
def touch_car_before_part_delete(sender: type[CarPart], instance: CarPart, **kwargs: object) -> None:
    _touch_car(instance.car_id)


@receiver(post_save, sender=Attachment)
def touch_car_for_attachment(sender: type[Attachment], instance: Attachment, **kwargs: object) -> None:
    _touch_attachment_parent(instance)


@receiver(pre_delete, sender=Attachment)
def touch_car_before_attachment_delete(sender: type[Attachment], instance: Attachment, **kwargs: object) -> None:
    _touch_attachment_parent(instance)
