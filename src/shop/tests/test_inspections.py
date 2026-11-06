import json
from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone

from shop.forms import InspectionForm, InspectionPointForm, WorkJobForm
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
            category_label="Brakes",
            code="brake_wear_general",
            label="Brake wear (general)",
            status=InspectionPoint.STATUS_PASS,
            position=0,
        )
        self.assertIn("Brake wear (general)", str(point))
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

        inspection = Inspection.objects.get(car=self.car)
        self.assertRedirects(
            response,
            reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]),
        )
        self.assertTrue(inspection.is_draft)
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

    def test_create_inspection_creates_all_checklist_points_by_default(self):
        response = self.client.post(
            reverse("shop-inspection-create", args=[self.car.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Detailed inspection.",
                "external_links": "",
            },
        )

        inspection = Inspection.objects.get(car=self.car)
        self.assertEqual(inspection.points.count(), len(flatten_checklist()))
        self.assertRedirects(
            response,
            reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]),
        )

    def test_update_form_renders_checklist_when_points_exist(self):
        inspection = Inspection.objects.create(
            car=self.car,
        )
        InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brakes",
            code="brake_wear_general",
            label="Brake wear (general)",
            position=0,
        )

        response = self.client.get(reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brakes")
        self.assertContains(response, "Brake wear (general)")

    def test_update_structured_inspection_persists_point_values(self):
        inspection = Inspection.objects.create(
            car=self.car,
        )
        point = InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brakes",
            code="brake_wear_general",
            label="Brake wear (general)",
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

    def test_update_structured_inspection_persists_enabled_categories(self):
        inspection = Inspection.objects.create(
            car=self.car,
        )
        point = InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brakes",
            code="brake_wear_general",
            label="Brake wear (general)",
            position=0,
        )

        response = self.client.post(
            reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Updated.",
                "enabled_categories": json.dumps(["brakes"]),
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
        inspection.refresh_from_db()
        self.assertEqual(inspection.enabled_categories, ["brakes"])

    def test_inspection_point_form_rejects_invalid_measurement(self):
        inspection = Inspection.objects.create(car=self.car)
        point = InspectionPoint.objects.create(
            inspection=inspection,
            category="tires",
            category_label="Tires",
            code="tread_depth_front_right",
            label="Tread depth - front right (1/32)",
            position=0,
        )

        form = InspectionPointForm(
            data={
                "points-status": InspectionPoint.STATUS_ATTENTION,
                "points-measurement": "not-a-number",
                "points-notes": "",
            },
            instance=point,
            prefix="points",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("measurement", form.errors)

    def test_inspection_point_form_accepts_valid_measurement(self):
        inspection = Inspection.objects.create(car=self.car)
        point = InspectionPoint.objects.create(
            inspection=inspection,
            category="tires",
            category_label="Tires",
            code="tread_depth_front_right",
            label="Tread depth - front right (1/32)",
            position=0,
        )

        form = InspectionPointForm(
            data={
                "points-status": InspectionPoint.STATUS_ATTENTION,
                "points-measurement": "6/32",
                "points-notes": "",
            },
            instance=point,
            prefix="points",
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["measurement"], "6/32")

    def test_inspection_point_form_accepts_french_choice_and_normalizes(self):
        inspection = Inspection.objects.create(car=self.car)
        point = InspectionPoint.objects.create(
            inspection=inspection,
            category="exterior_cabin",
            category_label="Exterior and cabin",
            code="brake_pedal_feel",
            label="Brake pedal feel",
            position=0,
        )

        form = InspectionPointForm(
            data={
                "points-status": InspectionPoint.STATUS_ATTENTION,
                "points-measurement": "molle",
                "points-notes": "",
            },
            instance=point,
            prefix="points",
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["measurement"], "spongy")

    def test_inspection_point_form_rejects_invalid_choice(self):
        inspection = Inspection.objects.create(car=self.car)
        point = InspectionPoint.objects.create(
            inspection=inspection,
            category="exterior_cabin",
            category_label="Exterior and cabin",
            code="brake_pedal_feel",
            label="Brake pedal feel",
            position=0,
        )

        form = InspectionPointForm(
            data={
                "points-status": InspectionPoint.STATUS_ATTENTION,
                "points-measurement": "not-valid",
                "points-notes": "",
            },
            instance=point,
            prefix="points",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("measurement", form.errors)

    def test_create_inspection_starts_as_draft(self):
        response = self.client.post(
            reverse("shop-inspection-create", args=[self.car.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Draft inspection.",
                "external_links": "",
            },
        )

        inspection = Inspection.objects.get(car=self.car)
        self.assertTrue(inspection.is_draft)
        self.assertRedirects(
            response,
            reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]),
        )

    def test_finalize_inspection_sets_is_draft_false(self):
        inspection = Inspection.objects.create(
            car=self.car,
            is_draft=True,
        )

        response = self.client.post(
            reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Finalized.",
                "action": "finalize",
            },
        )

        self.assertRedirects(response, reverse("shop-car-detail", args=[self.car.pk]))
        inspection.refresh_from_db()
        self.assertFalse(inspection.is_draft)

    def test_save_draft_keeps_is_draft_true(self):
        inspection = Inspection.objects.create(
            car=self.car,
            is_draft=True,
        )

        response = self.client.post(
            reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "12345",
                "notes": "Still a draft.",
                "action": "save_draft",
            },
        )

        self.assertRedirects(response, reverse("shop-car-detail", args=[self.car.pk]))
        inspection.refresh_from_db()
        self.assertTrue(inspection.is_draft)

    def test_draft_inspection_can_be_deleted(self):
        inspection = Inspection.objects.create(car=self.car, is_draft=True)

        response = self.client.post(
            reverse("shop-inspection-delete", args=[self.car.pk, inspection.pk]),
        )

        self.assertRedirects(response, reverse("shop-car-detail", args=[self.car.pk]))
        self.assertFalse(Inspection.objects.filter(pk=inspection.pk).exists())

    def test_finalized_inspection_cannot_be_deleted(self):
        inspection = Inspection.objects.create(car=self.car, is_draft=False)

        response = self.client.post(
            reverse("shop-inspection-delete", args=[self.car.pk, inspection.pk]),
        )

        self.assertRedirects(response, reverse("shop-inspection-history", args=[self.car.pk]))
        self.assertTrue(Inspection.objects.filter(pk=inspection.pk).exists())

    def test_autosave_endpoint_updates_draft(self):
        inspection = Inspection.objects.create(
            car=self.car,
            is_draft=True,
        )

        response = self.client.post(
            reverse("shop-inspection-autosave", args=[self.car.pk, inspection.pk]),
            data={
                "inspected_at": "2026-10-20T14:30",
                "mileage": "99999",
                "notes": "Autosaved notes.",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        inspection.refresh_from_db()
        self.assertEqual(inspection.mileage, 99999)
        self.assertEqual(inspection.notes, "Autosaved notes.")
        self.assertTrue(inspection.is_draft)

    def test_car_detail_excludes_drafts_from_latest_inspection(self):
        Inspection.objects.create(
            car=self.car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 20, 14, 30)),
            notes="DRAFT_NOTES",
            is_draft=True,
        )
        finalized = Inspection.objects.create(
            car=self.car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 21, 14, 30)),
            notes="FINAL_NOTES",
            is_draft=False,
        )

        response = self.client.get(reverse("shop-car-detail", args=[self.car.pk]))

        self.assertEqual(response.context["latest_inspection"], finalized)
        self.assertEqual(response.context["inspection_count"], 1)
        self.assertNotContains(response, "DRAFT_NOTES")
        self.assertContains(response, "FINAL_NOTES")

    def test_inspection_history_shows_draft_badge(self):
        Inspection.objects.create(
            car=self.car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 20, 14, 30)),
            is_draft=True,
        )

        response = self.client.get(reverse("shop-inspection-history", args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Draft")

    def test_rear_brake_type_choice_accepts_english_and_french(self):
        inspection = Inspection.objects.create(car=self.car)
        point = InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brakes",
            code="rear_brake_type",
            label="Rear brake type",
            position=0,
        )

        for value, expected in [("tambour", "drum"), ("disque", "disc")]:
            with self.subTest(value=value):
                form = InspectionPointForm(
                    data={
                        "points-status": InspectionPoint.STATUS_ATTENTION,
                        "points-measurement": value,
                        "points-notes": "",
                    },
                    instance=point,
                    prefix="points",
                )
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["measurement"], expected)

    def test_car_detail_shows_structured_inspection_summary(self):
        inspection = Inspection.objects.create(
            car=self.car,
            inspected_at=timezone.make_aware(datetime(2026, 10, 20, 14, 30)),
        )
        InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brakes",
            code="brake_wear_general",
            label="Brake wear (general)",
            status=InspectionPoint.STATUS_REPAIR,
            position=0,
        )
        InspectionPoint.objects.create(
            inspection=inspection,
            category="tires",
            category_label="Tires",
            code="visual_wear_front_right",
            label="Visual wear - front right",
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
            inspected_at=timezone.make_aware(datetime(2026, 10, 20, 14, 30)),
        )
        InspectionPoint.objects.create(
            inspection=inspection,
            category="brakes",
            category_label="Brakes",
            code="brake_wear_general",
            label="Brake wear (general)",
            status=InspectionPoint.STATUS_REPAIR,
            measurement="2mm",
            position=0,
        )

        response = self.client.get(reverse("shop-inspection-history", args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brakes")
        self.assertContains(response, "Brake wear (general)")
        self.assertContains(response, "Needs repair")
        self.assertContains(response, "2mm")

    def test_create_form_shows_create_inspection_button(self):
        response = self.client.get(reverse("shop-inspection-create", args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create inspection")
        self.assertNotContains(response, "Finalize inspection")

    def test_draft_update_form_shows_save_draft_and_finalize_buttons(self):
        inspection = Inspection.objects.create(car=self.car, is_draft=True)

        response = self.client.get(reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Save draft")
        self.assertContains(response, "Finalize inspection")

    def test_draft_update_form_has_single_finalize_button(self):
        inspection = Inspection.objects.create(car=self.car, is_draft=True)

        response = self.client.get(reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]))
        content = response.content.decode()

        self.assertEqual(content.count("Finalize inspection"), 1)

    def test_draft_update_form_delete_is_not_nested_in_main_form(self):
        inspection = Inspection.objects.create(car=self.car, is_draft=True)

        response = self.client.get(reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]))
        content = response.content.decode()

        main_form_close = content.find("</form>")
        delete_form_action = reverse("shop-inspection-delete", args=[self.car.pk, inspection.pk])
        delete_form_open = content.find(f'action="{delete_form_action}"')

        self.assertGreater(main_form_close, 0)
        self.assertGreater(delete_form_open, 0)
        self.assertGreater(delete_form_open, main_form_close)

    def test_finalized_update_form_shows_update_button(self):
        inspection = Inspection.objects.create(car=self.car, is_draft=False)

        response = self.client.get(reverse("shop-inspection-update", args=[self.car.pk, inspection.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Update")
        self.assertNotContains(response, "Save draft")
        self.assertNotContains(response, "Finalize inspection")
