from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone

from shop.forms import InspectionForm, WorkJobForm
from shop.models import Attachment, Inspection, WorkJob
from shop.models.fleet import FleetMembership
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
