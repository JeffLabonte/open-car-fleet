import json
from datetime import date
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction


class Command(BaseCommand):
    help = (
        "Import JSON objects into a Django model. "
        "Provide the model name and the JSON file path."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "model_name",
            help="Model name to import into, e.g. Car",
        )
        parser.add_argument(
            "json_file",
            help="Path to the JSON file containing a list of object dictionaries.",
        )
        parser.add_argument(
            "--app",
            default="shop",
            help="App label containing the model. Defaults to 'shop'.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Batch size for bulk_create. Defaults to 100.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the JSON data without saving any objects.",
        )

    def parse_date_value(self, value):
        if value is None:
            return None

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None

            try:
                return date.fromisoformat(value)
            except ValueError:
                parts = value.split("-")
                if len(parts) == 2:
                    return date(int(parts[0]), int(parts[1]), 1)
                if len(parts) == 1:
                    return date(int(parts[0]), 1, 1)

        raise CommandError(f"Unsupported date format: {value!r}")

    def resolve_car(self, car_value):
        if not car_value:
            raise CommandError("Car reference cannot be empty.")

        car_model = apps.get_model("shop", "Car")
        if isinstance(car_value, str):
            car_value = car_value.strip()

        for lookup in ("usual_name", "license_plate"):
            try:
                return car_model.objects.get(**{lookup: car_value})
            except car_model.DoesNotExist:
                continue

        raise CommandError(
            f"Car not found for reference '{car_value}'. Use Car usual_name or license_plate."
        )

    def prepare_workjob_record(self, record):
        data = {}
        notes = []
        used_keys = set()

        if "description" in record:
            data["title"] = record["description"]
            used_keys.add("description")

        if "date" in record:
            data["planned_date"] = self.parse_date_value(record["date"])
            used_keys.add("date")

        if "car" in record:
            data["car"] = self.resolve_car(record["car"])
            used_keys.add("car")

        if "technician" in record:
            technician = str(record["technician"]).strip()
            used_keys.add("technician")
            if technician:
                notes.append(f"Technician: {technician}")

        if notes:
            data["notes"] = "\n".join(notes)

        return data, used_keys

    def handle(self, *args, **options):
        app_label = options["app"]
        model_name = options["model_name"]
        json_file = Path(options["json_file"])

        if not json_file.exists():
            raise CommandError(f"JSON file not found: {json_file}")

        try:
            model = apps.get_model(app_label, model_name)
        except LookupError as exc:
            raise CommandError(
                f"Model '{model_name}' not found in app '{app_label}'."
            ) from exc

        try:
            raw_data = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON file: {exc}") from exc

        if isinstance(raw_data, dict):
            records = [raw_data]
        elif isinstance(raw_data, list):
            records = raw_data
        else:
            raise CommandError("JSON must be an object or an array of objects.")

        if not records:
            self.stdout.write(self.style.WARNING("No records found in JSON file."))
            return

        concrete_fields = {
            field.name
            for field in model._meta.get_fields()
            if getattr(field, "concrete", False) and not field.auto_created
        }

        objects = []
        skipped = 0
        warnings = []

        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise CommandError(
                    f"Record {index} is not an object: {record!r}"
                )

            if model._meta.model_name == "workjob":
                instance_data, used_keys = self.prepare_workjob_record(record)
            else:
                instance_data = {
                    key: value
                    for key, value in record.items()
                    if key in concrete_fields
                }
                used_keys = set(instance_data.keys())

            excluded_keys = set(record.keys()) - used_keys
            if excluded_keys:
                warnings.append(
                    f"Record {index} ignored fields: {sorted(excluded_keys)}"
                )

            if not instance_data:
                skipped += 1
                continue

            objects.append(model(**instance_data))

        for warning in warnings:
            self.stdout.write(self.style.WARNING(warning))

        if not objects:
            self.stdout.write(self.style.WARNING("No valid records to import."))
            return

        self.stdout.write(
            f"Preparing to import {len(objects)} objects into {app_label}.{model_name}"
        )

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry run complete. No objects were saved."))
            return

        try:
            with transaction.atomic():
                model.objects.bulk_create(objects, batch_size=options["batch_size"])
        except IntegrityError as exc:
            raise CommandError(f"Database error while importing data: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(
            f"Imported {len(objects)} objects into {app_label}.{model_name}"
        ))
