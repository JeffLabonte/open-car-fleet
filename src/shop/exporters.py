import json
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any

from django.utils import timezone
from openpyxl import Workbook

from shop.models.car import Car
from shop.models.fleet import Fleet
from shop.models.job import WorkJob
from shop.models.report import Report


@dataclass(slots=True)
class FleetExportWorkbook:
    filename: str
    content: bytes


def export_fleet_to_excel(fleet: Fleet) -> FleetExportWorkbook:
    exported_at = timezone.now()
    data = _gather_export_data(fleet)

    workbook = Workbook()
    _build_meta_sheet(workbook.active, fleet, exported_at, data)
    _build_fleet_sheet(workbook.create_sheet("fleet"), fleet)
    _build_memberships_sheet(workbook.create_sheet("memberships"), fleet, data["memberships"])
    _build_cars_sheet(workbook.create_sheet("cars_import"), fleet, data["cars"])
    _build_jobs_sheet(workbook.create_sheet("workjobs_import"), data["jobs"])
    _build_reports_sheet(workbook.create_sheet("reports_import"), data["reports"])

    content = _serialize_workbook(workbook)
    filename = _build_filename(fleet, exported_at)
    return FleetExportWorkbook(filename=filename, content=content)


def _gather_export_data(fleet: Fleet) -> dict[str, Any]:
    return {
        "cars": list(Car.objects.filter(fleet=fleet).order_by("created_at")),
        "jobs": list(
            WorkJob.objects.filter(car__fleet=fleet)
            .select_related("car", "assigned_to", "assigned_shop")
            .order_by("id")
        ),
        "reports": list(
            Report.objects.filter(car__fleet=fleet)
            .select_related("car", "assigned_to", "assigned_shop")
            .prefetch_related("attachments")
            .order_by("id")
        ),
        "memberships": list(fleet.memberships.select_related("user").order_by("created_at", "id")),
    }


def _build_meta_sheet(
    sheet: Any,
    fleet: Fleet,
    exported_at: datetime,
    data: dict[str, Any],
) -> None:
    sheet.title = "meta"
    _append_rows(
        sheet,
        ["key", "value"],
        [
            ["export_version", "1"],
            ["exported_at_utc", exported_at.isoformat()],
            ["fleet_id", str(fleet.pk)],
            ["fleet_name", fleet.name],
            [
                "row_counts_json",
                json.dumps(
                    {
                        "memberships": len(data["memberships"]),
                        "cars_import": len(data["cars"]),
                        "workjobs_import": len(data["jobs"]),
                        "reports_import": len(data["reports"]),
                    }
                ),
            ],
            [
                "restore_notes",
                (
                    "The *_import sheets are designed to be round-trippable through "
                    "import_csv. Records intentionally excluded from restore: "
                    "invitations, car parts/inspections/car documents, uploaded file "
                    "attachment contents (uploaded_attachments column is informational "
                    "only and will be ignored by the importer)."
                ),
            ],
        ],
    )


def _build_fleet_sheet(sheet: Any, fleet: Fleet) -> None:
    _append_rows(
        sheet,
        [
            "fleet_id",
            "name",
            "description",
            "created_by_user_id",
            "created_at",
            "updated_at",
        ],
        [
            [
                str(fleet.pk),
                fleet.name,
                fleet.description,
                _string_or_empty(fleet.created_by_id),
                _format_datetime(fleet.created_at),
                _format_datetime(fleet.updated_at),
            ]
        ],
    )


def _build_memberships_sheet(sheet: Any, fleet: Fleet, memberships: list[Any]) -> None:
    _append_rows(
        sheet,
        [
            "fleet_id",
            "user_id",
            "user_email",
            "username",
            "display_name",
            "role",
            "created_at",
        ],
        [
            [
                str(fleet.pk),
                _string_or_empty(membership.user_id),
                membership.user.email,
                membership.user.username,
                membership.user.display_name,
                membership.role,
                _format_datetime(membership.created_at),
            ]
            for membership in memberships
        ],
    )


def _build_cars_sheet(sheet: Any, fleet: Fleet, cars: list[Car]) -> None:
    # Headers match the Car CSV import schema so the sheet is round-trippable.
    _append_rows(
        sheet,
        [
            "usual_name",
            "make",
            "model",
            "colour",
            "year",
            "vin",
            "license_plate",
            "mileage",
        ],
        [
            [
                car.usual_name,
                car.make,
                car.model,
                car.colour,
                _string_or_empty(car.year),
                car.vin or "",
                car.license_plate,
                _string_or_empty(car.mileage),
            ]
            for car in cars
        ],
    )


def _build_jobs_sheet(sheet: Any, jobs: list[WorkJob]) -> None:
    # Headers match the WorkJob CSV import schema so the sheet is round-trippable.
    _append_rows(
        sheet,
        [
            "car",
            "title",
            "maintenance_type",
            "assigned_to",
            "assigned_shop",
            "planned_date",
            "is_done",
            "done_date",
            "required_items",
            "urgency",
            "status",
            "notes",
        ],
        [
            [
                _car_reference(job.car),
                job.title,
                job.maintenance_type,
                _assignment_reference(job.assigned_to),
                _shop_reference(job.assigned_shop),
                _format_date(job.planned_date),
                bool(job.is_done),
                _format_date(job.done_date),
                _join_list(job.required_items),
                job.urgency,
                job.status,
                job.notes,
            ]
            for job in jobs
        ],
    )


def _build_reports_sheet(sheet: Any, reports: list[Report]) -> None:
    # Headers match the Report CSV import schema so the sheet is round-trippable.
    # External-link attachments are split into documents/photos; uploaded file
    # attachments are listed separately because their file content is not embedded
    # in the workbook and cannot be restored automatically.
    _append_rows(
        sheet,
        [
            "car",
            "mileage",
            "job_name",
            "assigned_to",
            "assigned_shop",
            "date_done",
            "documents",
            "photos",
            "uploaded_attachments",
            "note",
            "additional_information",
        ],
        [
            [
                _car_reference(report.car),
                _string_or_empty(report.mileage),
                report.job_name,
                _assignment_reference(report.assigned_to),
                _shop_reference(report.assigned_shop),
                _format_date(report.date_done),
                *_split_attachment_columns(report.attachments.all()),
                report.note,
                report.additional_information,
            ]
            for report in reports
        ],
    )


def _append_rows(sheet: Any, header: list[str], rows: list[list[Any]]) -> None:
    sheet.append(header)
    for row in rows:
        sheet.append([_sanitize_cell(cell) for cell in row])


# Characters that spreadsheet applications interpret as formula prefixes.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value: Any) -> Any:
    """Prefix user-controlled strings with a single quote to block formula injection."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _serialize_workbook(workbook: Workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _string_or_empty(value: Any) -> str:
    return "" if value in (None, "") else str(value)


def _format_datetime(value: datetime | None) -> str:
    return "" if value is None else value.isoformat()


def _format_date(value: Any) -> str:
    return "" if value is None else value.isoformat()


def _join_list(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    if value in (None, ""):
        return ""
    return str(value)


def _car_reference(car: Car) -> str:
    return car.vin or car.license_plate or car.usual_name or str(car.pk)


def _assignment_reference(user) -> str:
    """Return an importable reference for a mechanic or shop user."""
    if user is None:
        return ""
    return user.email or user.username or str(user.pk)


def _shop_reference(shop) -> str:
    """Return an importable reference for a known shop."""
    if shop is None:
        return ""
    return shop.email or shop.name or str(shop.pk)


def _split_attachment_columns(attachments: Any) -> tuple[str, str, str]:
    """Split attachments into documents, photos, and uploaded file names.

    External links are mapped back to the importer's ``documents``/``photos``
    columns by kind. Uploaded files cannot be restored from the workbook, so
    their display names are isolated in ``uploaded_attachments``.
    """
    documents: list[str] = []
    photos: list[str] = []
    uploaded: list[str] = []
    for attachment in attachments:
        if attachment.source_type == "external":
            value = attachment.url or attachment.display_name or ""
            if attachment.kind in ("image", "video"):
                photos.append(value)
            else:
                documents.append(value)
        else:
            uploaded.append(attachment.display_name or attachment.file.name or "")
    return (
        "\n".join(documents),
        "\n".join(photos),
        "\n".join(uploaded),
    )


def _build_filename(fleet: Fleet, exported_at: datetime) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in fleet.name).strip("-")
    compact_slug = "-".join(part for part in slug.split("-") if part) or str(fleet.pk)
    timestamp = exported_at.strftime("%Y%m%d_%H%M%S")
    return f"fleet_{compact_slug}_{timestamp}.xlsx"
