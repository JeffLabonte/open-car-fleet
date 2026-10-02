from django.test import TestCase
from django.urls import reverse

from shop.models.garage import Garage, GarageMembership
from shop.models.user import ShopUser


class GarageUpdateTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='pass1234',
        )
        self.admin = ShopUser.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='pass1234',
        )
        self.mechanic = ShopUser.objects.create_user(
            username='mechanic',
            email='mechanic@example.com',
            password='pass1234',
        )
        self.viewer = ShopUser.objects.create_user(
            username='viewer',
            email='viewer@example.com',
            password='pass1234',
        )
        self.stranger = ShopUser.objects.create_user(
            username='stranger',
            email='stranger@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Alpha Garage', description='Original desc.', created_by=self.owner)
        GarageMembership.objects.create(garage=self.garage, user=self.owner, role=GarageMembership.ROLE_OWNER)
        GarageMembership.objects.create(garage=self.garage, user=self.admin, role=GarageMembership.ROLE_ADMIN)
        GarageMembership.objects.create(garage=self.garage, user=self.mechanic, role=GarageMembership.ROLE_MECHANIC)
        GarageMembership.objects.create(garage=self.garage, user=self.viewer, role=GarageMembership.ROLE_VIEWER)

    def test_owner_can_update_garage(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-garage-update', args=[self.garage.pk]),
            data={'name': 'Renamed Garage', 'description': 'Updated description.'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-garage-detail', args=[self.garage.pk]))
        self.garage.refresh_from_db()
        self.assertEqual(self.garage.name, 'Renamed Garage')
        self.assertEqual(self.garage.description, 'Updated description.')

    def test_admin_can_update_garage(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('shop-garage-update', args=[self.garage.pk]),
            data={'name': 'Admin Renamed Garage', 'description': 'Admin update.'},
        )

        self.assertEqual(response.status_code, 302)
        self.garage.refresh_from_db()
        self.assertEqual(self.garage.name, 'Admin Renamed Garage')
        self.assertEqual(self.garage.description, 'Admin update.')

    def test_viewer_cannot_update_garage(self):
        self.client.force_login(self.viewer)
        original_name = self.garage.name

        response = self.client.post(
            reverse('shop-garage-update', args=[self.garage.pk]),
            data={'name': 'Hacked Garage', 'description': 'Hacked.'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-garage-detail', args=[self.garage.pk]))
        self.garage.refresh_from_db()
        self.assertEqual(self.garage.name, original_name)

    def test_mechanic_cannot_update_garage(self):
        self.client.force_login(self.mechanic)
        original_name = self.garage.name

        response = self.client.post(
            reverse('shop-garage-update', args=[self.garage.pk]),
            data={'name': 'Hacked Garage', 'description': 'Hacked.'},
        )

        self.assertEqual(response.status_code, 302)
        self.garage.refresh_from_db()
        self.assertEqual(self.garage.name, original_name)

    def test_stranger_gets_404_for_update(self):
        self.client.force_login(self.stranger)

        response = self.client.post(
            reverse('shop-garage-update', args=[self.garage.pk]),
            data={'name': 'Hacked Garage', 'description': 'Hacked.'},
        )

        self.assertEqual(response.status_code, 404)

    def test_empty_name_shows_validation_error(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-garage-update', args=[self.garage.pk]),
            data={'name': '', 'description': 'Still invalid.'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('name', response.context['form'].errors)

    def test_name_too_long_shows_validation_error(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-garage-update', args=[self.garage.pk]),
            data={'name': 'x' * 201, 'description': 'Still invalid.'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('name', response.context['form'].errors)

    def test_get_request_renders_detail_with_form(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('shop-garage-update', args=[self.garage.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)
        self.assertEqual(response.context['form'].instance, self.garage)
        self.assertContains(response, 'Edit fleet')
        self.assertContains(response, self.garage.name)

    def test_detail_page_renders_edit_form_in_modal(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('shop-garage-detail', args=[self.garage.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="fleet-edit-dialog"')
        self.assertContains(response, 'name="name"')
        self.assertContains(response, 'value="Alpha Garage"')
        self.assertContains(response, 'name="description"')

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get(reverse('shop-garage-update', args=[self.garage.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(reverse('shop-login')))
