import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction

from shop.models.car import Car
from shop.models.garage import Garage, KnownShop
from shop.models.job import WorkJob
from shop.models.report import Report


VIN_BAD_CHARS = set("IOQ")


class ImportValidationError(Exception):
    pass


@dataclass(slots=True)
class ImportIssue:
    record_number: int
    message: str


@dataclass(slots=True)
class ImportResult:
    model_label: str
    requested_records: int
    created_count: int = 0
    skipped_count: int = 0
    warnings: list[ImportIssue] = field(default_factory=list)
    errors: list[ImportIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


@dataclass(slots=True)
class ImportContext:
    garage: Garage | None = None
    car: Car | None = None


class CSVImporter:
    model_map = {
        "car": Car,
        "workjob": WorkJob,
        "report": Report,
    }

    def parse_csv_file(self, csv_file: str | Path) -> list[dict[str, Any]]:
        path = Path(csv_file)
        if not path.exists():
            raise ImportValidationError(f"CSV file not found: {path}")

        try:
            raw_content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ImportValidationError(f"Unable to decode CSV file '{path.name}' as UTF-8.") from exc

        return self.parse_csv_content(raw_content, source_name=path.name)

    def parse_csv_content(self, raw_content: str, *, source_name: str = "CSV") -> list[dict[str, Any]]:
        if not raw_content or not raw_content.strip():
            return []

        dialect = self._detect_dialect(raw_content[:4096])
        try:
            reader = csv.DictReader(io.StringIO(raw_content), dialect=dialect)
            rows = list(reader)
        except csv.Error as exc:
            raise ImportValidationError(f"Invalid CSV format in {source_name}: {exc}") from exc

        if reader.fieldnames is None:
            return []

        records = [self._clean_csv_row(row) for row in rows]
        return [record for record in records if any(record.values())]

    @staticmethod
    def _detect_dialect(sample: str) -> type[csv.Dialect]:
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            return csv.excel

    @staticmethod
    def _clean_csv_row(row: dict[str | None, str | None]) -> dict[str, str | None]:
        return {
            key.strip(): value.strip() if value is not None else None
            for key, value in row.items()
            if key and key.strip()
        }

    def parse_csv_bytes(self, raw_bytes: bytes, *, source_name: str = "upload") -> list[dict[str, Any]]:
        try:
            raw_content = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ImportValidationError(f"Unable to decode {source_name} as UTF-8.") from exc

        return self.parse_csv_content(raw_content, source_name=source_name)

    def import_records(
        self,
        model: type[models.Model],
        records: list[dict[str, Any]],
        *,
        context: ImportContext | None = None,
        batch_size: int = 100,
        dry_run: bool = False,
    ) -> ImportResult:
        normalized_context = context or ImportContext()
        result = ImportResult(
            model_label=f"{model._meta.app_label}.{model.__name__}",
            requested_records=len(records),
        )

        objects: list[models.Model] = []
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                result.errors.append(ImportIssue(index, f"Record is not an object: {record!r}"))
                continue

            try:
                instance_data, warnings = self._prepare_record(model, record, normalized_context)
            except ImportValidationError as exc:
                result.errors.append(ImportIssue(index, str(exc)))
                continue

            for warning in warnings:
                result.warnings.append(ImportIssue(index, warning))

            if not instance_data:
                result.skipped_count += 1
                continue

            instance = model(**instance_data)
            try:
                instance.full_clean()
            except ValidationError as exc:
                result.errors.append(ImportIssue(index, self._format_validation_error(exc)))
                continue

            objects.append(instance)

        if result.has_errors:
            return result

        if dry_run:
            result.created_count = len(objects)
            return result

        try:
            with transaction.atomic():
                model.objects.bulk_create(objects, batch_size=batch_size)
        except IntegrityError as exc:
            raise ImportValidationError(f"Database error while importing data: {exc}") from exc

        result.created_count = len(objects)
        return result

    def resolve_model(self, model_name: str) -> type[models.Model]:
        model = self.model_map.get(model_name.lower())
        if model is None:
            raise ImportValidationError(
                f"Unsupported model '{model_name}'. Supported models: Car, WorkJob, Report."
            )
        return model

    def _prepare_record(
        self,
        model: type[models.Model],
        record: dict[str, Any],
        context: ImportContext,
    ) -> tuple[dict[str, Any], list[str]]:
        if model is Car:
            return self._prepare_car_record(record, context)
        if model is WorkJob:
            return self._prepare_workjob_record(record, context)
        if model is Report:
            return self._prepare_report_record(record, context)
        raise ImportValidationError(f"Unsupported model '{model.__name__}'.")

    def _prepare_car_record(
        self,
        record: dict[str, Any],
        context: ImportContext,
    ) -> tuple[dict[str, Any], list[str]]:
        garage = context.garage
        if garage is None:
            raise ImportValidationError("A target garage is required when importing cars.")

        data = {
            "garage": garage,
            "usual_name": self._clean_optional_text(record.get("usual_name")) or "",
            "make": self._require_text(record, "make"),
            "model": self._require_text(record, "model"),
            "colour": self._clean_optional_text(record.get("colour")) or "",
            "year": self._coerce_optional_int(record.get("year"), field_name="year"),
            "mileage": self._coerce_optional_int(record.get("mileage"), field_name="mileage"),
            "vin": self._normalize_vin(record.get("vin")),
            "license_plate": self._normalize_license_plate(record.get("license_plate")),
        }
        warnings = self._ignored_field_warnings(record, set(data.keys()) | {"garage"})
        return data, warnings

    def _prepare_workjob_record(
        self,
        record: dict[str, Any],
        context: ImportContext,
    ) -> tuple[dict[str, Any], list[str]]:
        data = {
            "car": self._resolve_car(record.get("car"), context),
            "title": self._require_text(record, "title"),
            "maintenance_type": self._clean_optional_text(record.get("maintenance_type")) or "",
            "assigned_to": self._resolve_mechanic(record.get("assigned_to")),
            "assigned_shop": self._resolve_shop(record.get("assigned_shop")),
            "planned_date": self._parse_date_value(record.get("planned_date")),
            "is_done": self._coerce_bool(record.get("is_done", False), field_name="is_done"),
            "done_date": self._parse_date_value(record.get("done_date")),
            "required_items": self._coerce_string_list(record.get("required_items"), field_name="required_items"),
            "urgency": self._clean_optional_text(record.get("urgency")) or "ahead",
            "status": self._clean_optional_text(record.get("status")) or "pending",
            "notes": self._clean_optional_text(record.get("notes")) or "",
        }
        self._validate_assignment_target(data["assigned_to"], data["assigned_shop"])
        warnings = self._ignored_field_warnings(record, set(data.keys()))
        return data, warnings

    def _prepare_report_record(
        self,
        record: dict[str, Any],
        context: ImportContext,
    ) -> tuple[dict[str, Any], list[str]]:
        job_name = self._clean_optional_text(record.get("job_name")) or self._clean_optional_text(record.get("description"))
        if not job_name:
            raise ImportValidationError("Field 'job_name' is required.")

        date_done = self._parse_date_value(record.get("date_done")) or self._parse_date_value(record.get("date"))
        if date_done is None:
            raise ImportValidationError("Field 'date_done' is required.")

        data = {
            "car": self._resolve_car(record.get("car"), context),
            "mileage": self._coerce_optional_int(record.get("mileage"), field_name="mileage"),
            "job_name": job_name,
            "assigned_to": self._resolve_mechanic(record.get("assigned_to")),
            "assigned_shop": self._resolve_shop(record.get("assigned_shop")),
            "date_done": date_done,
            "documents": self._coerce_string_list(record.get("documents"), field_name="documents"),
            "photos": self._coerce_string_list(record.get("photos"), field_name="photos"),
            "note": self._clean_optional_text(record.get("note")) or "",
            "additional_information": (
                self._clean_optional_text(record.get("additional_information"))
                or self._clean_optional_text(record.get("extra_information"))
                or self._clean_optional_text(record.get("details"))
                or ""
            ),
        }
        self._validate_assignment_target(data["assigned_to"], data["assigned_shop"])
        used_keys = set(data.keys()) | {"description", "date", "details", "extra_information", "related_date", "completed"}
        warnings = self._ignored_field_warnings(record, used_keys)
        return data, warnings

    def _resolve_car(self, raw_value: Any, context: ImportContext) -> Car:
        if context.car is not None:
            if raw_value in (None, ""):
                return context.car
            queryset = Car.objects.filter(pk=context.car.pk)
        else:
            queryset = Car.objects.all()
            if context.garage is not None:
                queryset = queryset.filter(garage=context.garage)

        if raw_value in (None, ""):
            raise ImportValidationError("Car reference is required.")

        if isinstance(raw_value, str):
            value = raw_value.strip()
            if not value:
                raise ImportValidationError("Car reference cannot be empty.")
            if self._looks_like_uuid(value):
                try:
                    return queryset.get(pk=value)
                except Car.DoesNotExist as exc:
                    raise ImportValidationError(f"Car not found for id '{value}'.") from exc

            lookup_fields = ("vin", "license_plate", "usual_name")
            for field_name in lookup_fields:
                try:
                    return queryset.get(**{field_name: value})
                except Car.DoesNotExist:
                    continue

            raise ImportValidationError(
                f"Car not found for reference '{value}'. Use car id, VIN, license plate, or usual name."
            )

        try:
            return queryset.get(pk=raw_value)
        except Car.DoesNotExist as exc:
            raise ImportValidationError(f"Car not found for id '{raw_value}'.") from exc

    def _resolve_mechanic(self, raw_value: Any):
        if raw_value in (None, ""):
            return None

        user_model = get_user_model()
        queryset = user_model.objects.filter(is_mechanic=True)
        if isinstance(raw_value, str):
            value = raw_value.strip()
            if not value:
                return None
            try:
                return queryset.get(models.Q(email__iexact=value) | models.Q(username__iexact=value))
            except user_model.DoesNotExist as exc:
                raise ImportValidationError(
                    f"Mechanic not found for reference '{value}'. Use username or email for an existing mechanic."
                ) from exc

        try:
            return queryset.get(pk=raw_value)
        except user_model.DoesNotExist as exc:
            raise ImportValidationError(f"Mechanic not found for id '{raw_value}'.") from exc

    def _resolve_shop(self, raw_value: Any):
        if raw_value in (None, ""):
            return None

        queryset = KnownShop.objects.all()
        if isinstance(raw_value, str):
            value = raw_value.strip()
            if not value:
                return None
            try:
                return queryset.get(models.Q(name__iexact=value) | models.Q(email__iexact=value))
            except KnownShop.DoesNotExist as exc:
                raise ImportValidationError(
                    f"Known shop not found for reference '{value}'. Use an existing shop name or email."
                ) from exc

        try:
            return queryset.get(pk=raw_value)
        except KnownShop.DoesNotExist as exc:
            raise ImportValidationError(f"Known shop not found for id '{raw_value}'.") from exc

    def _validate_assignment_target(self, assigned_to: Any, assigned_shop: Any) -> None:
        if assigned_to is not None and assigned_shop is not None:
            raise ImportValidationError("Assign either a mechanic user or a known shop, not both.")

    def _require_text(self, record: dict[str, Any], field_name: str) -> str:
        value = self._clean_optional_text(record.get(field_name))
        if not value:
            raise ImportValidationError(f"Field '{field_name}' is required.")
        return value

    def _clean_optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _coerce_optional_int(self, value: Any, *, field_name: str) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ImportValidationError(f"Field '{field_name}' must be an integer.") from exc

    def _coerce_bool(self, value: Any, *, field_name: str) -> bool:
        if isinstance(value, bool):
            return value
        if value in (None, ""):
            return False
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "y"}:
            return True
        if normalized in {"0", "false", "no", "n"}:
            return False
        raise ImportValidationError(f"Field '{field_name}' must be a boolean.")

    def _parse_date_value(self, value: Any) -> date | None:
        if value is None:
            return None

        if isinstance(value, date):
            return value

        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None

            try:
                return date.fromisoformat(cleaned)
            except ValueError:
                parts = cleaned.split("-")
                try:
                    if len(parts) == 2:
                        return date(int(parts[0]), int(parts[1]), 1)
                    if len(parts) == 1:
                        return date(int(parts[0]), 1, 1)
                except ValueError as exc:
                    raise ImportValidationError(f"Unsupported date format: {value!r}") from exc

        raise ImportValidationError(f"Unsupported date format: {value!r}")

    def _require_date(self, record: dict[str, Any], field_name: str) -> date:
        parsed = self._parse_date_value(record.get(field_name))
        if parsed is None:
            raise ImportValidationError(f"Field '{field_name}' is required.")
        return parsed

    def _coerce_string_list(self, value: Any, *, field_name: str) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            items = []
            for item in value:
                cleaned = self._clean_optional_text(item)
                if cleaned:
                    items.append(cleaned)
            return items
        if isinstance(value, str):
            return [item.strip() for item in value.splitlines() if item.strip()]
        raise ImportValidationError(f"Field '{field_name}' must be a list or newline-delimited string.")

    def _normalize_vin(self, value: Any) -> str | None:
        cleaned = self._clean_optional_text(value)
        if not cleaned:
            return None
        vin = re.sub(r"\s+", "", cleaned).upper()
        if any(ch in VIN_BAD_CHARS for ch in vin):
            raise ImportValidationError("VIN contains invalid characters (I, O, Q are not allowed).")
        if not re.match(r"^[A-HJ-NPR-Z0-9]{11,17}$", vin):
            raise ImportValidationError("VIN must be 11-17 alphanumeric characters (no I/O/Q).")
        return vin

    def _normalize_license_plate(self, value: Any) -> str:
        cleaned = self._clean_optional_text(value)
        if not cleaned:
            return ""
        plate = cleaned.upper()
        if len(plate) > 20:
            raise ImportValidationError("License plate must be 20 characters or fewer.")
        if not re.match(r"^[A-Z0-9 \-]+$", plate):
            raise ImportValidationError("License plate contains invalid characters.")
        return plate

    def _ignored_field_warnings(self, record: dict[str, Any], used_keys: set[str]) -> list[str]:
        excluded_keys = set(record.keys()) - used_keys
        if not excluded_keys:
            return []
        return [f"Ignored fields: {sorted(excluded_keys)}"]

    def _looks_like_uuid(self, value: str) -> bool:
        return bool(re.match(r"^[0-9a-fA-F\-]{32,36}$", value))

    def _format_validation_error(self, exc: ValidationError) -> str:
        if hasattr(exc, "message_dict"):
            return "; ".join(
                f"{field}: {', '.join(messages)}"
                for field, messages in exc.message_dict.items()
            )
        return "; ".join(exc.messages)