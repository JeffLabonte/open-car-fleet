from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from shop.exporters import export_fleet_to_excel
from shop.models.fleet import Fleet


class Command(BaseCommand):
    help = "Export one fleet backup workbook as an Excel (.xlsx) file."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("fleet_id", help="Fleet UUID to export.")
        parser.add_argument(
            "--output",
            help="Optional output file path. Defaults to an auto-generated filename in the current directory.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        fleet = self._resolve_fleet(options["fleet_id"])
        workbook = export_fleet_to_excel(fleet)

        output_value = options.get("output") or workbook.filename
        output_path = Path(output_value)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(workbook.content)

        self.stdout.write(self.style.SUCCESS(f"Exported fleet '{fleet.name}' ({fleet.pk}) to {output_path}"))

    def _resolve_fleet(self, raw_value: str) -> Fleet:
        try:
            return Fleet.objects.get(pk=raw_value)
        except (Fleet.DoesNotExist, ValidationError, ValueError) as exc:
            raise CommandError(f"Fleet not found for id '{raw_value}'.") from exc
