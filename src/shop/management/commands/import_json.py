from typing import Any

from django.core.management.base import BaseCommand, CommandError

from shop.importers import ImportContext, ImportValidationError, JSONImporter
from shop.models.garage import Garage


class Command(BaseCommand):
    help = (
        "Import normalized JSON objects into Car, WorkJob, or Report. "
        "Cars require a target garage."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "model_name",
            help="Model name to import into, e.g. Car, WorkJob, or Report.",
        )
        parser.add_argument(
            "json_file",
            help="Path to the JSON file containing a list of object dictionaries.",
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
        parser.add_argument(
            "--garage",
            help="Required for Car imports. Garage UUID to assign all imported records to.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        importer = JSONImporter()

        try:
            model = importer.resolve_model(options["model_name"])
            records = importer.parse_json_file(options["json_file"])
            context = ImportContext(garage=self._resolve_garage(options.get("garage")))
            result = importer.import_records(
                model,
                records,
                context=context,
                batch_size=options["batch_size"],
                dry_run=options["dry_run"],
            )
        except ImportValidationError as exc:
            raise CommandError(str(exc)) from exc

        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f"Record {warning.record_number}: {warning.message}"))

        if result.has_errors:
            for error in result.errors:
                self.stdout.write(self.style.ERROR(f"Record {error.record_number}: {error.message}"))
            raise CommandError("Import failed validation. No objects were saved.")

        self.stdout.write(
            f"Prepared {result.created_count} of {result.requested_records} records for {result.model_label}"
        )

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry run complete. No objects were saved."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {result.created_count} objects into {result.model_label}"
            )
        )

    def _resolve_garage(self, raw_value: str | None) -> Garage | None:
        if raw_value in (None, ""):
            return None
        try:
            return Garage.objects.get(pk=raw_value)
        except Garage.DoesNotExist as exc:
            raise ImportValidationError(f"Garage not found for id '{raw_value}'.") from exc

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
