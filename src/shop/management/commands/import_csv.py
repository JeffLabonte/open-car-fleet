from typing import Any

from django.core.management.base import BaseCommand, CommandError

from shop.importers import CSVImporter, ImportContext, ImportValidationError
from shop.models.garage import Garage


class Command(BaseCommand):
    help = (
        "Import normalized CSV objects into Car, WorkJob, or Report. "
        "Cars require a target garage."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "model_name",
            help="Model name to import into, e.g. Car, WorkJob, or Report.",
        )
        parser.add_argument(
            "csv_file",
            help="Path to the CSV file containing object rows.",
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
            help="Validate the CSV data without saving any objects.",
        )
        parser.add_argument(
            "--garage",
            help="Required for Car imports. Garage UUID to assign all imported records to.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        importer = CSVImporter()

        try:
            model = importer.resolve_model(options["model_name"])
            records = importer.parse_csv_file(options["csv_file"])
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
        except (Garage.DoesNotExist, ValidationError, ValueError) as exc:
            raise ImportValidationError(f"Garage not found for id '{raw_value}'.") from exc
