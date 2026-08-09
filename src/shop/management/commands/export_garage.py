from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from shop.exporters import export_garage_to_excel
from shop.models.garage import Garage


class Command(BaseCommand):
    help = "Export one garage backup workbook as an Excel (.xlsx) file."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("garage_id", help="Garage UUID to export.")
        parser.add_argument(
            "--output",
            help="Optional output file path. Defaults to an auto-generated filename in the current directory.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        garage = self._resolve_garage(options["garage_id"])
        workbook = export_garage_to_excel(garage)

        output_value = options.get("output") or workbook.filename
        output_path = Path(output_value)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(workbook.content)

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported garage '{garage.name}' ({garage.pk}) to {output_path}"
            )
        )

    def _resolve_garage(self, raw_value: str) -> Garage:
        try:
            return Garage.objects.get(pk=raw_value)
        except Garage.DoesNotExist as exc:
            raise CommandError(f"Garage not found for id '{raw_value}'.") from exc
