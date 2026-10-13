from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shop.models.report import Report


def update_car_odometer_from_report(report: Report) -> bool:
    """Update the associated car's odometer if the report mileage is higher.

    The car's ``mileage`` field is used as the authoritative odometer reading.
    It is only modified when a maintenance report records a strictly higher
    mileage value.

    Returns ``True`` when the car's odometer was updated.
    """
    car = report.car
    report_mileage = report.mileage

    if report_mileage is None:
        return False

    if car.mileage is None or report_mileage > car.mileage:
        car.mileage = report_mileage
        car.save(update_fields=["mileage", "updated_at"])
        return True

    return False
