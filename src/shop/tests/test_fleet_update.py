from django.test import TestCase
from django.urls import reverse

from shop.models.fleet import Fleet, FleetMembership
from shop.models.user import ShopUser


class FleetUpdateTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="pass1234",
        )
        self.admin = ShopUser.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="pass1234",
        )
        self.mechanic = ShopUser.objects.create_user(
            username="mechanic",
            email="mechanic@example.com",
            password="pass1234",
        )
        self.viewer = ShopUser.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="pass1234",
        )
        self.stranger = ShopUser.objects.create_user(
            username="stranger",
            email="stranger@example.com",
            password="pass1234",
        )
        self.fleet = Fleet.objects.create(name="Alpha Fleet", description="Original desc.", created_by=self.owner)
        FleetMembership.objects.create(fleet=self.fleet, user=self.owner, role=FleetMembership.ROLE_OWNER)
        FleetMembership.objects.create(fleet=self.fleet, user=self.admin, role=FleetMembership.ROLE_ADMIN)
        FleetMembership.objects.create(fleet=self.fleet, user=self.mechanic, role=FleetMembership.ROLE_MECHANIC)
        FleetMembership.objects.create(fleet=self.fleet, user=self.viewer, role=FleetMembership.ROLE_VIEWER)

    def test_owner_can_update_fleet(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("shop-fleet-update", args=[self.fleet.pk]),
            data={"name": "Renamed Fleet", "description": "Updated description."},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("shop-fleet-detail", args=[self.fleet.pk]))
        self.fleet.refresh_from_db()
        self.assertEqual(self.fleet.name, "Renamed Fleet")
        self.assertEqual(self.fleet.description, "Updated description.")

    def test_admin_can_update_fleet(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("shop-fleet-update", args=[self.fleet.pk]),
            data={"name": "Admin Renamed Fleet", "description": "Admin update."},
        )

        self.assertEqual(response.status_code, 302)
        self.fleet.refresh_from_db()
        self.assertEqual(self.fleet.name, "Admin Renamed Fleet")
        self.assertEqual(self.fleet.description, "Admin update.")

    def test_viewer_cannot_update_fleet(self):
        self.client.force_login(self.viewer)
        original_name = self.fleet.name

        response = self.client.post(
            reverse("shop-fleet-update", args=[self.fleet.pk]),
            data={"name": "Hacked Fleet", "description": "Hacked."},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("shop-fleet-detail", args=[self.fleet.pk]))
        self.fleet.refresh_from_db()
        self.assertEqual(self.fleet.name, original_name)

    def test_mechanic_cannot_update_fleet(self):
        self.client.force_login(self.mechanic)
        original_name = self.fleet.name

        response = self.client.post(
            reverse("shop-fleet-update", args=[self.fleet.pk]),
            data={"name": "Hacked Fleet", "description": "Hacked."},
        )

        self.assertEqual(response.status_code, 302)
        self.fleet.refresh_from_db()
        self.assertEqual(self.fleet.name, original_name)

    def test_stranger_gets_404_for_update(self):
        self.client.force_login(self.stranger)

        response = self.client.post(
            reverse("shop-fleet-update", args=[self.fleet.pk]),
            data={"name": "Hacked Fleet", "description": "Hacked."},
        )

        self.assertEqual(response.status_code, 404)

    def test_empty_name_shows_validation_error(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("shop-fleet-update", args=[self.fleet.pk]),
            data={"name": "", "description": "Still invalid."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("form", response.context)
        self.assertFalse(response.context["form"].is_valid())
        self.assertIn("name", response.context["form"].errors)

    def test_name_too_long_shows_validation_error(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("shop-fleet-update", args=[self.fleet.pk]),
            data={"name": "x" * 201, "description": "Still invalid."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertIn("name", response.context["form"].errors)

    def test_get_request_renders_detail_with_form(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("shop-fleet-update", args=[self.fleet.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn("form", response.context)
        self.assertEqual(response.context["form"].instance, self.fleet)
        self.assertContains(response, "Edit fleet")
        self.assertContains(response, self.fleet.name)

    def test_detail_page_renders_edit_form_in_modal(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("shop-fleet-detail", args=[self.fleet.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="fleet-edit-dialog"')
        self.assertContains(response, "dialog--fleet-edit")
        self.assertContains(response, '<form method="post"')
        self.assertContains(
            response,
            'action="%s"' % reverse("shop-fleet-update", args=[self.fleet.pk]),
        )
        self.assertContains(response, 'name="name"')
        self.assertContains(response, 'value="Alpha Fleet"')
        self.assertContains(response, 'name="description"')

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get(reverse("shop-fleet-update", args=[self.fleet.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("shop-login")))
