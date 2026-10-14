from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext as _

from shop.importers import CSVImporter, ImportContext, ImportValidationError
from shop.models.fleet import Fleet


class Command(BaseCommand):
    help = (
        "Import normalized CSV objects into Car, WorkJob, or Report. All command-line imports require a target fleet."
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
            "--fleet",
            help="Required for every command-line import. Fleet UUID used to scope records.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        importer = CSVImporter()

        try:
            model = importer.resolve_model(options["model_name"])
            records = importer.parse_csv_file(options["csv_file"])
            fleet = self._resolve_fleet(options.get("fleet"))
            if fleet is None:
                raise ImportValidationError("A target fleet is required for command-line imports.")
            context = ImportContext(fleet=fleet, user=fleet.created_by)
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

        self.stdout.write(self.style.SUCCESS(f"Imported {result.created_count} objects into {result.model_label}"))

    def _resolve_fleet(self, raw_value: str | None) -> Fleet | None:
        if raw_value in (None, ""):
            return None
        try:
            return Fleet.objects.get(pk=raw_value)
        except (Fleet.DoesNotExist, ValidationError, ValueError) as exc:
            raise ImportValidationError(_("Fleet not found for id '%(value)s'.") % {"value": raw_value}) from exc
