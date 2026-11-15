import tempfile
import uuid
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from shop.exporters import export_fleet_to_excel
from shop.importers import CSVImporter, ImportContext
from shop.models.attachment import Attachment
from shop.models.car import Car
from shop.models.fleet import Fleet, FleetMembership, KnownShop
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.models.user import ShopUser


class FleetExportServiceTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username="export-owner",
            email="export-owner@example.com",
            password="pass1234",
            is_mechanic=True,
        )
        self.fleet = Fleet.objects.create(name="Primary Fleet", created_by=self.owner)
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )

        self.other_fleet = Fleet.objects.create(name="Other Fleet", created_by=self.owner)
        FleetMembership.objects.create(
            fleet=self.other_fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )

        self.primary_car = Car.objects.create(
            fleet=self.fleet,
            usual_name="Daily Driver",
            make="Toyota",
            model="Corolla",
            vin="2T1BURHE5JC512345",
        )
        self.other_car = Car.objects.create(
            fleet=self.other_fleet,
            usual_name="Spare Car",
            make="Honda",
            model="Civic",
            vin="2HGFG12698H512345",
        )

        WorkJob.objects.create(
            car=self.primary_car,
            title="Oil Change",
            assigned_to=self.owner,
            required_items=["Oil", "Filter"],
            status="pending",
            urgency="soon",
        )
        WorkJob.objects.create(
            car=self.other_car,
            title="Do Not Export",
        )

        brake_report = Report.objects.create(
            car=self.primary_car,
            mileage=120000,
            job_name="Brake Service",
            assigned_to=self.owner,
            date_done=timezone.now().date(),
        )
        ContentType.objects.get_for_model(brake_report)
        Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(brake_report),
            object_id=str(brake_report.pk),
            source_type=Attachment.SOURCE_UPLOAD,
            file=SimpleUploadedFile("invoice.pdf", b"%PDF-1.4 invoice", content_type="application/pdf"),
            display_name="invoice.pdf",
            mime_type="application/pdf",
            kind="document",
        )
        Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(brake_report),
            object_id=str(brake_report.pk),
            source_type=Attachment.SOURCE_EXTERNAL,
            url="https://example.com/before.jpg",
            display_name="before.jpg",
            kind="link",
        )
        Report.objects.create(
            car=self.other_car,
            job_name="Skip Report",
            date_done=timezone.now().date(),
        )

    def test_export_fleet_to_excel_includes_expected_sheets_and_rows(self):
        workbook_file = export_fleet_to_excel(self.fleet)
        workbook = load_workbook(filename=BytesIO(workbook_file.content))

        self.assertIn("meta", workbook.sheetnames)
        self.assertIn("fleet", workbook.sheetnames)
        self.assertIn("memberships", workbook.sheetnames)
        self.assertIn("cars_import", workbook.sheetnames)
        self.assertIn("workjobs_import", workbook.sheetnames)
        self.assertIn("reports_import", workbook.sheetnames)

        cars = _sheet_to_dicts(workbook["cars_import"])
        self.assertEqual(len(cars), 1)
        self.assertEqual(cars[0]["make"], "Toyota")
        self.assertNotIn("2HGFG12698H512345", [row["vin"] for row in cars])

        jobs = _sheet_to_dicts(workbook["workjobs_import"])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Oil Change")
        self.assertEqual(jobs[0]["required_items"], "Oil\nFilter")

        reports = _sheet_to_dicts(workbook["reports_import"])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["job_name"], "Brake Service")
        self.assertEqual(reports[0]["documents"], "https://example.com/before.jpg")
        self.assertEqual(reports[0]["photos"], "")
        self.assertEqual(reports[0]["uploaded_attachments"], "invoice.pdf")


class FleetExportViewTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username="export-view-owner",
            email="export-view-owner@example.com",
            password="pass1234",
            is_mechanic=True,
        )
        self.manager = ShopUser.objects.create_user(
            username="export-view-manager",
            email="export-view-manager@example.com",
            password="pass1234",
        )
        self.member = ShopUser.objects.create_user(
            username="export-view-member",
            email="export-view-member@example.com",
            password="pass1234",
        )

        self.fleet = Fleet.objects.create(name="Export View Fleet", created_by=self.owner)
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.manager,
            role=FleetMembership.ROLE_MANAGER,
        )
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.member,
            role=FleetMembership.ROLE_MEMBER,
        )

        self.primary_car = Car.objects.create(
            fleet=self.fleet,
            usual_name="Exportable",
            make="Ford",
            model="Focus",
            vin="1FAHP3F28CL512345",
        )

        self.other_fleet = Fleet.objects.create(name="External Fleet", created_by=self.owner)
        FleetMembership.objects.create(
            fleet=self.other_fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )
        Car.objects.create(
            fleet=self.other_fleet,
            usual_name="Hidden",
            make="Tesla",
            model="Model 3",
            vin="5YJ3E1EA7LF512345",
        )

    def test_unauthenticated_user_is_redirected_from_fleet_export(self):
        response = self.client.get(reverse("shop-fleet-export", args=[self.fleet.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(f"{reverse('shop-login')}?next="))

    def test_non_manager_is_redirected_from_fleet_export(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("shop-fleet-export", args=[self.fleet.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("shop-fleet-detail", args=[self.fleet.pk]))

    def test_manager_can_download_fleet_export_workbook(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("shop-fleet-export", args=[self.fleet.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn('attachment; filename="fleet_export-view-fleet_', response["Content-Disposition"])

        workbook = load_workbook(filename=BytesIO(response.content))
        cars_rows = _sheet_to_dicts(workbook["cars_import"])
        vins = [row["vin"] for row in cars_rows]
        self.assertIn("1FAHP3F28CL512345", vins)
        self.assertNotIn("5YJ3E1EA7LF512345", vins)


class ExportFleetCommandTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username="command-owner",
            email="command-owner@example.com",
            password="pass1234",
        )
        self.fleet = Fleet.objects.create(name="Command Fleet", created_by=self.user)
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.user,
            role=FleetMembership.ROLE_OWNER,
        )

    def test_export_fleet_command_writes_excel_file(self):
        Car.objects.create(
            fleet=self.fleet,
            usual_name="Command Export Car",
            make="Mazda",
            model="3",
            vin="JM1BK323171512345",
        )
        output = StringIO()

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
            output_path = Path(handle.name)
        output_path.unlink(missing_ok=True)

        try:
            call_command(
                "export_fleet",
                str(self.fleet.pk),
                "--output",
                str(output_path),
                stdout=output,
            )
            self.assertTrue(output_path.exists())
            workbook = load_workbook(filename=str(output_path))
            self.assertIn("cars_import", workbook.sheetnames)
            cars = _sheet_to_dicts(workbook["cars_import"])
            self.assertEqual(len(cars), 1)
            self.assertEqual(cars[0]["make"], "Mazda")
        finally:
            output_path.unlink(missing_ok=True)

    def test_export_fleet_command_errors_for_unknown_fleet(self):
        with self.assertRaises(CommandError):
            call_command("export_fleet", str(uuid.uuid4()))

    def test_export_fleet_command_rejects_invalid_fleet_uuid(self):
        with self.assertRaises(CommandError):
            call_command("export_fleet", "not-a-uuid")


class FleetExportRoundTripTests(TestCase):
    """Verify exported *_import sheets can be imported back into a fleet."""

    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username="roundtrip-owner",
            email="roundtrip-owner@example.com",
            password="pass1234",
            is_mechanic=True,
        )
        self.source_fleet = Fleet.objects.create(name="Source Fleet", created_by=self.owner)
        FleetMembership.objects.create(fleet=self.source_fleet, user=self.owner, role=FleetMembership.ROLE_OWNER)

        self.target_fleet = Fleet.objects.create(name="Target Fleet", created_by=self.owner)
        FleetMembership.objects.create(fleet=self.target_fleet, user=self.owner, role=FleetMembership.ROLE_OWNER)

        self.shop = KnownShop.objects.create(name="Roundtrip Shop", email="shop@example.com")

    def test_round_trip_imports_cars_workjobs_and_reports(self):
        car = Car.objects.create(
            fleet=self.source_fleet,
            usual_name="Daily Driver",
            make="Toyota",
            model="Corolla",
            year=2018,
            mileage=92_450,
            vin="2T1BURHE5JC512345",
            license_plate="ABC 123",
        )
        WorkJob.objects.create(
            car=car,
            title="Oil Change",
            maintenance_type="Routine",
            assigned_to=self.owner,
            planned_date="2026-08-15",
            is_done=False,
            required_items=["5W-30 oil", "Oil filter"],
            urgency="soon",
            status="pending",
            notes="Use OEM filter.",
        )
        report = Report.objects.create(
            car=car,
            mileage=93_120,
            job_name="Brake Service",
            assigned_shop=self.shop,
            date_done="2026-08-03",
            note="Pads and rotors replaced.",
            additional_information="Rear brakes still at 60%.",
        )
        ContentType.objects.get_for_model(report)
        Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report),
            object_id=str(report.pk),
            source_type=Attachment.SOURCE_EXTERNAL,
            url="https://example.com/invoice.pdf",
            display_name="invoice.pdf",
            kind="document",
        )

        exporter_file = export_fleet_to_excel(self.source_fleet)
        workbook = load_workbook(filename=BytesIO(exporter_file.content))
        importer = CSVImporter()

        # Free up globally-unique VINs so the round trip can recreate the cars.
        Car.objects.filter(fleet=self.source_fleet).delete()

        # Dry-run first to serve as an import preview.
        car_records = _sheet_to_dicts(workbook["cars_import"])
        dry_run = importer.import_records(
            Car,
            car_records,
            context=ImportContext(fleet=self.target_fleet, user=self.owner),
            dry_run=True,
        )
        self.assertFalse(dry_run.has_errors)
        self.assertEqual(dry_run.created_count, 1)
        self.assertEqual(Car.objects.filter(fleet=self.target_fleet).count(), 0)

        # Import cars into the target fleet.
        car_result = importer.import_records(
            Car,
            car_records,
            context=ImportContext(fleet=self.target_fleet, user=self.owner),
        )
        self.assertFalse(car_result.has_errors)
        self.assertEqual(car_result.created_count, 1)
        imported_car = Car.objects.get(fleet=self.target_fleet, vin="2T1BURHE5JC512345")
        self.assertEqual(imported_car.make, "Toyota")
        self.assertEqual(imported_car.mileage, 92_450)

        # Import work jobs, scoped to the target fleet.
        job_records = _sheet_to_dicts(workbook["workjobs_import"])
        job_result = importer.import_records(
            WorkJob,
            job_records,
            context=ImportContext(fleet=self.target_fleet, user=self.owner),
        )
        self.assertFalse(job_result.has_errors)
        self.assertEqual(job_result.created_count, 1)
        imported_job = WorkJob.objects.get(car__fleet=self.target_fleet, title="Oil Change")
        self.assertEqual(imported_job.assigned_to, self.owner)
        self.assertEqual(imported_job.required_items, ["5W-30 oil", "Oil filter"])

        # Import reports, scoped to the target fleet.
        report_records = _sheet_to_dicts(workbook["reports_import"])
        report_result = importer.import_records(
            Report,
            report_records,
            context=ImportContext(fleet=self.target_fleet, user=self.owner),
        )
        self.assertFalse(report_result.has_errors)
        self.assertEqual(report_result.created_count, 1)
        imported_report = Report.objects.get(car__fleet=self.target_fleet, job_name="Brake Service")
        self.assertEqual(imported_report.assigned_shop, self.shop)
        self.assertEqual(imported_report.additional_information, "Rear brakes still at 60%.")
        self.assertEqual(imported_report.attachments.count(), 1)
        self.assertEqual(imported_report.attachments.first().url, "https://example.com/invoice.pdf")

    def test_round_trip_warns_about_uploaded_file_attachments(self):
        car = Car.objects.create(
            fleet=self.source_fleet,
            make="Honda",
            model="Civic",
            vin="2HGFG12698H512345",
        )
        report = Report.objects.create(
            car=car,
            job_name="Transmission Service",
            date_done="2026-09-01",
        )
        ContentType.objects.get_for_model(report)
        Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report),
            object_id=str(report.pk),
            source_type=Attachment.SOURCE_UPLOAD,
            file=SimpleUploadedFile("receipt.pdf", b"%PDF-1.4 receipt", content_type="application/pdf"),
            display_name="receipt.pdf",
            mime_type="application/pdf",
            kind="document",
        )

        exporter_file = export_fleet_to_excel(self.source_fleet)
        workbook = load_workbook(filename=BytesIO(exporter_file.content))
        importer = CSVImporter()

        Car.objects.filter(fleet=self.source_fleet).delete()

        importer.import_records(
            Car,
            _sheet_to_dicts(workbook["cars_import"]),
            context=ImportContext(fleet=self.target_fleet, user=self.owner),
        )
        report_result = importer.import_records(
            Report,
            _sheet_to_dicts(workbook["reports_import"]),
            context=ImportContext(fleet=self.target_fleet, user=self.owner),
        )

        self.assertFalse(report_result.has_errors)
        self.assertTrue(any("uploaded_attachments" in warning.message for warning in report_result.warnings))


class FleetExportMultiCarRoundTripTests(TestCase):
    """Round-trip a multi-car fleet export and verify car references are preserved."""

    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username="mc-roundtrip-owner",
            email="mc-roundtrip-owner@example.com",
            password="pass1234",
            is_mechanic=True,
        )
        self.source_fleet = Fleet.objects.create(name="Source Fleet", created_by=self.owner)
        FleetMembership.objects.create(fleet=self.source_fleet, user=self.owner, role=FleetMembership.ROLE_OWNER)

        self.target_fleet = Fleet.objects.create(name="Target Fleet", created_by=self.owner)
        FleetMembership.objects.create(fleet=self.target_fleet, user=self.owner, role=FleetMembership.ROLE_OWNER)

        self.shop = KnownShop.objects.create(name="Roundtrip Shop", email="shop@example.com")

    def test_multi_car_round_trip_preserves_car_references(self):
        car_a = Car.objects.create(
            fleet=self.source_fleet,
            usual_name="Car A",
            make="Toyota",
            model="Corolla",
            year=2018,
            mileage=92_450,
            vin="2T1BURHE5JC512345",
            license_plate="AAA 111",
        )
        car_b = Car.objects.create(
            fleet=self.source_fleet,
            usual_name="Car B",
            make="Honda",
            model="Civic",
            year=2020,
            mileage=45_000,
            vin="2HGFG12698H512345",
            license_plate="BBB 222",
        )

        WorkJob.objects.create(
            car=car_a,
            title="Oil Change A",
            assigned_to=self.owner,
            required_items=["Oil", "Filter"],
            status="pending",
            urgency="soon",
        )
        WorkJob.objects.create(
            car=car_b,
            title="Brake Job B",
            required_items=["Pads"],
            status="pending",
            urgency="ahead",
        )

        report_a = Report.objects.create(
            car=car_a,
            mileage=93_120,
            job_name="Brake Service A",
            assigned_shop=self.shop,
            date_done="2026-08-03",
            note="Pads replaced on A.",
        )
        Report.objects.create(
            car=car_b,
            mileage=46_000,
            job_name="Battery B",
            date_done="2026-09-01",
            note="Battery replaced on B.",
        )
        from django.contrib.contenttypes.models import ContentType

        ContentType.objects.get_for_model(report_a)
        Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report_a),
            object_id=str(report_a.pk),
            source_type=Attachment.SOURCE_EXTERNAL,
            url="https://example.com/a.pdf",
            display_name="a.pdf",
            kind="document",
        )

        exporter_file = export_fleet_to_excel(self.source_fleet)
        workbook = load_workbook(filename=BytesIO(exporter_file.content))
        importer = CSVImporter()

        # Free up globally-unique VINs so the round trip can recreate the cars.
        Car.objects.filter(fleet=self.source_fleet).delete()

        # Cars
        car_records = _sheet_to_dicts(workbook["cars_import"])
        self.assertEqual(len(car_records), 2)
        car_result = importer.import_records(
            Car,
            car_records,
            context=ImportContext(fleet=self.target_fleet, user=self.owner),
        )
        self.assertFalse(car_result.has_errors)
        self.assertEqual(car_result.created_count, 2)
        imported_a = Car.objects.get(fleet=self.target_fleet, vin="2T1BURHE5JC512345")
        imported_b = Car.objects.get(fleet=self.target_fleet, vin="2HGFG12698H512345")

        # Work jobs must land on the correct cars.
        job_records = _sheet_to_dicts(workbook["workjobs_import"])
        self.assertEqual(len(job_records), 2)
        job_result = importer.import_records(
            WorkJob,
            job_records,
            context=ImportContext(fleet=self.target_fleet, user=self.owner),
        )
        self.assertFalse(job_result.has_errors, job_result.errors)
        self.assertEqual(job_result.created_count, 2)
        self.assertTrue(WorkJob.objects.filter(car=imported_a, title="Oil Change A").exists())
        self.assertTrue(WorkJob.objects.filter(car=imported_b, title="Brake Job B").exists())
        imported_job_a = WorkJob.objects.get(car=imported_a, title="Oil Change A")
        self.assertEqual(imported_job_a.assigned_to, self.owner)
        self.assertEqual(imported_job_a.required_items, ["Oil", "Filter"])

        # Reports must land on the correct cars with attachments.
        report_records = _sheet_to_dicts(workbook["reports_import"])
        self.assertEqual(len(report_records), 2)
        report_result = importer.import_records(
            Report,
            report_records,
            context=ImportContext(fleet=self.target_fleet, user=self.owner),
        )
        self.assertFalse(report_result.has_errors, report_result.errors)
        self.assertEqual(report_result.created_count, 2)
        imported_report_a = Report.objects.get(car=imported_a, job_name="Brake Service A")
        imported_report_b = Report.objects.get(car=imported_b, job_name="Battery B")
        self.assertEqual(imported_report_a.assigned_shop, self.shop)
        self.assertEqual(imported_report_a.attachments.count(), 1)
        self.assertEqual(imported_report_a.attachments.first().url, "https://example.com/a.pdf")
        self.assertEqual(imported_report_b.mileage, 46_000)

    def test_car_scoped_import_rejects_mismatched_car_reference(self):
        car = Car.objects.create(
            fleet=self.source_fleet,
            usual_name="Car A",
            make="Toyota",
            model="Corolla",
            vin="2T1BURHE5JC512345",
        )
        other_car = Car.objects.create(
            fleet=self.source_fleet,
            usual_name="Car B",
            make="Honda",
            model="Civic",
            vin="2HGFG12698H512345",
        )
        importer = CSVImporter()
        result = importer.import_records(
            WorkJob,
            [{"car": other_car.vin, "title": "Cross-car job"}],
            context=ImportContext(fleet=self.source_fleet, car=car, user=self.owner),
            dry_run=True,
        )
        self.assertTrue(result.has_errors)
        self.assertIn("does not match the selected car", result.errors[0].message)


def _sheet_to_dicts(sheet) -> list[dict[str, Any]]:
    """Return an openpyxl sheet as a list of row dicts keyed by header cell."""
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(cell) if cell is not None else "" for cell in rows[0]]
    return [{key: ("" if value is None else value) for key, value in zip(header, row)} for row in rows[1:]]
