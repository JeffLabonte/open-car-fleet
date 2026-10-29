from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone

from shop.forms import InspectionForm, WorkJobForm
from shop.inspection_checklist import flatten_checklist
from shop.models import Attachment, Inspection, WorkJob
from shop.models.fleet import FleetMembership
from shop.models.inspection_point import InspectionPoint
from shop.tests.helpers import PNG_SIGNATURE, ShopTestCase


class InspectionModelAndFormTests(ShopTestCase):
    def test_latest_inspection_is_ordered_by_inspection_time(self):
        car = self.create_car()
        older = Inspection.objects.create(
            car=car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 1, 9, 0)),
            notes="Older findings",
        )
        latest = Inspection.objects.create(
            car=car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 20, 14, 30)),
            notes="Latest findings",
        )

        self.assertEqual(Inspection.objects.latest_for_car(car), latest)
        self.assertEqual(list(Inspection.objects.filter(car=car)), [latest, older])

    def test_inspection_form_parses_exact_timezone_aware_datetime(self):
        form = InspectionForm(
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Brake wear observed.",
                "external_links": "",
            },
            user=self.owner,
        )

        self.assertTrue(form.is_valid(), form.errors)
        inspected_at = form.cleaned_data["inspected_at"]
        self.assertTrue(timezone.is_aware(inspected_at))
        self.assertEqual(inspected_at, timezone.make_aware(datetime(2026, 10, 20, 14, 30)))

    def test_work_job_form_only_lists_inspections_for_current_car(self):
        car = self.create_car()
        other_car = self.create_car(vin="2HGFG12698H512346")
        inspection = Inspection.objects.create(car=car)
        other_inspection = Inspection.objects.create(car=other_car)

        form = WorkJobForm(user=self.owner, fleet=self.fleet, car=car)

        self.assertIn(inspection, form.fields["inspection"].queryset)
        self.assertNotIn(other_inspection, form.fields["inspection"].queryset)

    def test_inspection_form_rejects_invalid_external_link(self):
        form = InspectionForm(
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Notes",
                "external_links": "not-a-valid-link",
            },
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("external_links", form.errors)

    def test_unsaved_inspection_has_empty_status_counts(self):
        inspection = Inspection(car=self.create_car())
        self.assertEqual(
            inspection.point_status_counts(),
            {
                InspectionPoint.STATUS_PASS: 0,
                InspectionPoint.STATUS_ATTENTION: 0,
                InspectionPoint.STATUS_REPAIR: 0,
                InspectionPoint.STATUS_NA: 0,
            },
        )

    def test_inspection_point_str(self):
        inspection = Inspection.objects.create(car=self.create_car())
        point = InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brake system",
            code="brake_wear",
            label="Brake wear",
            status=InspectionPoint.STATUS_PASS,
            position=0,
        )
        self.assertIn("Brake wear", str(point))
        self.assertIn("OK / Pass", str(point))

    def test_work_job_rejects_inspection_from_another_car(self):
        car = self.create_car()
        other_car = self.create_car(vin="2HGFG12698H512346")
        inspection = Inspection.objects.create(car=other_car)
        work_job = WorkJob(car=car, inspection=inspection, title="Incorrect association")

        with self.assertRaises(ValidationError):
            work_job.full_clean()

    def test_inspection_history_cannot_be_deleted(self):
        inspection = Inspection.objects.create(car=self.create_car())

        with self.assertRaises(ProtectedError):
            inspection.delete()
        with self.assertRaises(ProtectedError):
            Inspection.objects.filter(pk=inspection.pk).delete()
        with self.assertRaises(ProtectedError):
            inspection.car.delete()


class InspectionViewIntegrationTests(ShopTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.car = self.create_car()
        self.client.force_login(self.owner)

    def test_create_inspection_with_photo_document_and_external_link(self):
        response = self.client.post(
            reverse("shop-inspection-create", args=[self.car.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Brake wear observed.",
                "external_links": "https://example.com/inspection.pdf",
                "attachments": SimpleUploadedFile(
                    "brakes.png",
                    PNG_SIGNATURE,
                    content_type="image/png",
                ),
            },
        )

        self.assertRedirects(response, reverse("shop-car-detail", args=[self.car.pk]))
        inspection = Inspection.objects.get(car=self.car)
        self.assertEqual(inspection.inspected_at, timezone.make_aware(datetime(2026, 10, 20, 14, 30)))
        self.assertEqual(inspection.created_by, self.owner)
        self.assertEqual(inspection.attachments.count(), 2)
        self.assertEqual(inspection.attachments.filter(source_type=Attachment.SOURCE_UPLOAD).count(), 1)
        self.assertEqual(inspection.attachments.filter(source_type=Attachment.SOURCE_EXTERNAL).count(), 1)

    def test_vehicle_detail_shows_only_latest_inspection_and_recommended_work(self):
        Inspection.objects.create(
            car=self.car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 1, 9, 0)),
            notes="OLDER_UNIQUE_FINDINGS",
        )
        latest = Inspection.objects.create(
            car=self.car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 20, 14, 30)),
            notes="LATEST_UNIQUE_FINDINGS",
        )
        WorkJob.objects.create(
            car=self.car,
            inspection=latest,
            title="Replace brake pads",
            planned_date=datetime(2026, 11, 1).date(),
        )

        response = self.client.get(reverse("shop-car-detail", args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["latest_inspection"], latest)
        self.assertEqual(response.context["inspection_count"], 2)
        self.assertContains(response, "LATEST_UNIQUE_FINDINGS")
        self.assertContains(response, "Replace brake pads")
        self.assertNotContains(response, "OLDER_UNIQUE_FINDINGS")
        self.assertContains(response, "View inspection history")

    def test_history_page_shows_all_inspections_and_recommendations(self):
        older = Inspection.objects.create(
            car=self.car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 1, 9, 0)),
            notes="OLDER_HISTORY_FINDINGS",
        )
        latest = Inspection.objects.create(
            car=self.car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 20, 14, 30)),
            notes="LATEST_HISTORY_FINDINGS",
        )
        WorkJob.objects.create(car=self.car, inspection=older, title="Older recommendation")
        WorkJob.objects.create(car=self.car, inspection=latest, title="Latest recommendation")

        response = self.client.get(reverse("shop-inspection-history", args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OLDER_HISTORY_FINDINGS")
        self.assertContains(response, "LATEST_HISTORY_FINDINGS")
        self.assertContains(response, "Older recommendation")
        self.assertContains(response, "Latest recommendation")
        self.assertEqual(response.context["inspections"].count(), 2)

    def test_add_recommended_work_prefills_and_persists_inspection(self):
        inspection = Inspection.objects.create(
            car=self.car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 20, 14, 30)),
        )

        form_response = self.client.get(
            reverse("shop-workjob-create", args=[self.car.pk]),
            {"inspection": inspection.pk},
        )
        self.assertEqual(form_response.status_code, 200)
        self.assertEqual(form_response.context["form"].initial["inspection"], inspection.pk)

        response = self.client.post(
            reverse("shop-workjob-create", args=[self.car.pk]),
            data={
                "title": "Replace tire",
                "inspection": inspection.pk,
                "planned_date": "2026-11-01",
                "status": WorkJob.STATUS_PENDING,
                "urgency": "soon",
                "required_items": "New tire",
            },
        )

        self.assertRedirects(response, reverse("shop-car-detail", args=[self.car.pk]))
        work_job = WorkJob.objects.get(title="Replace tire")
        self.assertEqual(work_job.inspection, inspection)

    def test_create_inspection_form_renders_with_initial_datetime(self):
        response = self.client.get(reverse("shop-inspection-create", args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Use structured checklist")
        self.assertIsNotNone(response.context["form"].fields["inspected_at"].initial)

    def test_viewer_can_read_history_but_cannot_create_inspection(self):
        viewer = self.create_user(username="inspection-viewer", email="inspection-viewer@example.com")
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=viewer,
            role=FleetMembership.ROLE_VIEWER,
        )
        self.client.force_login(viewer)

        history_response = self.client.get(reverse("shop-inspection-history", args=[self.car.pk]))
        create_response = self.client.get(reverse("shop-inspection-create", args=[self.car.pk]))

        self.assertEqual(history_response.status_code, 200)
        self.assertRedirects(create_response, reverse("shop-car-detail", args=[self.car.pk]))

    def test_viewer_cannot_edit_inspection(self):
        viewer = self.create_user(username="inspection-viewer", email="inspection-viewer@example.com")
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=viewer,
            role=FleetMembership.ROLE_VIEWER,
        )
        inspection = Inspection.objects.create(car=self.car)
        self.client.force_login(viewer)

        response = self.client.get(reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]))

        self.assertRedirects(response, reverse("shop-car-detail", args=[self.car.pk]))

    def test_stranger_cannot_retrieve_inspection_history(self):
        stranger = self.create_user(username="inspection-stranger", email="inspection-stranger@example.com")
        self.client.force_login(stranger)

        response = self.client.get(reverse("shop-inspection-history", args=[self.car.pk]))

        self.assertEqual(response.status_code, 404)

    def test_attachment_file_is_available_to_vehicle_member(self):
        inspection = Inspection.objects.create(car=self.car)
        self.client.post(
            reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "notes": "Photo evidence",
                "attachments": SimpleUploadedFile("inspection.png", PNG_SIGNATURE, content_type="image/png"),
            },
        )
        attachment = inspection.attachments.get()

        response = self.client.get(reverse("shop-attachment-file", args=[attachment.pk]))

        self.assertEqual(response.status_code, 200)

    def test_vehicle_delete_is_blocked_when_inspection_history_exists(self):
        Inspection.objects.create(car=self.car)

        response = self.client.post(reverse("shop-car-delete", args=[self.car.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Inspection.objects.filter(car=self.car).exists())
        self.assertTrue(response.context["car"].pk == self.car.pk)
        self.assertContains(response, "This car cannot be deleted because it has inspection history.")

    def test_structured_inspection_creates_all_checklist_points(self):
        response = self.client.post(
            reverse("shop-inspection-create", args=[self.car.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Structured inspection.",
                "use_structured_checklist": "on",
                "external_links": "",
            },
        )

        inspection = Inspection.objects.get(car=self.car)
        self.assertTrue(inspection.use_structured_checklist)
        self.assertEqual(inspection.points.count(), len(flatten_checklist()))
        self.assertRedirects(
            response,
            reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]),
        )

    def test_non_structured_inspection_creates_no_points(self):
        response = self.client.post(
            reverse("shop-inspection-create", args=[self.car.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Quick inspection.",
                "external_links": "",
            },
        )

        self.assertRedirects(response, reverse("shop-car-detail", args=[self.car.pk]))
        inspection = Inspection.objects.get(car=self.car)
        self.assertFalse(inspection.use_structured_checklist)
        self.assertEqual(inspection.points.count(), 0)

    def test_structured_checkbox_is_disabled_when_points_exist(self):
        inspection = Inspection.objects.create(
            car=self.car,
            use_structured_checklist=True,
        )
        InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brake system",
            code="brake_wear",
            label="Brake wear",
            position=0,
        )

        response = self.client.get(reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].fields["use_structured_checklist"].disabled)
        self.assertContains(response, "Brake system")
        self.assertContains(response, "Brake wear")

    def test_update_structured_inspection_persists_point_values(self):
        inspection = Inspection.objects.create(
            car=self.car,
            use_structured_checklist=True,
        )
        point = InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brake system",
            code="brake_wear",
            label="Brake wear",
            position=0,
        )

        response = self.client.post(
            reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Updated.",
                "points-TOTAL_FORMS": "1",
                "points-INITIAL_FORMS": "1",
                "points-MIN_NUM_FORMS": "0",
                "points-MAX_NUM_FORMS": "1000",
                "points-0-id": str(point.pk),
                "points-0-inspection": str(inspection.pk),
                "points-0-status": InspectionPoint.STATUS_REPAIR,
                "points-0-measurement": "2mm",
                "points-0-notes": "Needs replacement soon.",
            },
        )

        self.assertRedirects(response, reverse("shop-car-detail", args=[self.car.pk]))
        point.refresh_from_db()
        self.assertEqual(point.status, InspectionPoint.STATUS_REPAIR)
        self.assertEqual(point.measurement, "2mm")
        self.assertEqual(point.notes, "Needs replacement soon.")

    def test_car_detail_shows_structured_inspection_summary(self):
        inspection = Inspection.objects.create(
            car=self.car,
            use_structured_checklist=True,
            inspected_at=timezone.make_aware(datetime(2026, 10, 20, 14, 30)),
        )
        InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brake system",
            code="brake_wear",
            label="Brake wear",
            status=InspectionPoint.STATUS_REPAIR,
            position=0,
        )
        InspectionPoint.objects.create(
            inspection=inspection,
            category="tires_wheels",
            category_label="Tires & wheels",
            code="tire_wear",
            label="Is there any wear",
            status=InspectionPoint.STATUS_PASS,
            position=1,
        )

        response = self.client.get(reverse("shop-car-detail", args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Needs repair: 1")
        self.assertContains(response, "OK: 1")

    def test_history_page_shows_structured_inspection_points(self):
        inspection = Inspection.objects.create(
            car=self.car,
            use_structured_checklist=True,
            inspected_at=timezone.make_aware(datetime(2026, 10, 20, 14, 30)),
        )
        InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brake system",
            code="brake_wear",
            label="Brake wear",
            status=InspectionPoint.STATUS_REPAIR,
            measurement="2mm",
            position=0,
        )

        response = self.client.get(reverse("shop-inspection-history", args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brake system")
        self.assertContains(response, "Brake wear")
        self.assertContains(response, "Needs repair")
        self.assertContains(response, "2mm")
