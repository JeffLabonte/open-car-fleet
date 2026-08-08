import json
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from typing import cast
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.core.management import call_command
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from shop import views
from shop.forms import CarCreateForm, CarUpdateForm, GarageCreateForm, ReportForm, WorkJobForm
from shop.importers import ImportContext, JSONImporter
from shop.middleware import HankoAuthenticationMiddleware
from shop.models.car import Car
from shop.models.garage import Garage, GarageInvitation, GarageMembership
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.models.user import ShopUser


class HankoAuthenticationIntegrationTests(TestCase):
    def test_logged_off_users_are_redirected_to_login_from_app_routes(self):
        response = self.client.get(reverse('shop-index'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(f"{reverse('shop-login')}?next="))

        login_response = self.client.get(reverse('shop-login'))
        self.assertEqual(login_response.status_code, 200)

    def test_hanko_callback_and_middleware_rehydrate_django_user(self):
        payload = {
            "user": {
                "id": "hanko-user-123",
                "email": "driver@example.com",
                "name": "Test Driver",
                "display_name": "Test Driver",
                "avatar_url": "https://example.com/avatar.png",
                "provider": "hanko",
            }
        }

        response = self.client.post(
            reverse('shop-hanko-callback'),
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])

        user = ShopUser.objects.get(email='driver@example.com')
        self.assertEqual(user.hanko_id, 'hanko-user-123')
        self.assertEqual(user.display_name, 'Test Driver')
        self.assertTrue(user.is_active)

        self.client.logout()
        self.client.session['hanko_session_token'] = 'session-token-123'
        self.client.session.save()

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, str]:
                return {
                    'id': 'hanko-user-123',
                    'email': 'driver@example.com',
                    'name': 'Test Driver',
                    'display_name': 'Test Driver',
                    'avatar_url': 'https://example.com/avatar.png',
                    'provider': 'hanko',
                }

        with patch('shop.middleware.requests.get', return_value=FakeResponse()):
            self.client.get(reverse('shop-index'))

        factory = RequestFactory()
        request = factory.get(reverse('shop-index'))

        def next_response(_request: HttpRequest) -> HttpResponse:
            return HttpResponse()

        SessionMiddleware(next_response).process_request(request)
        request.session['hanko_session_token'] = 'session-token-123'
        request.session.save()
        AuthenticationMiddleware(next_response).process_request(request)

        with patch('shop.middleware.requests.get', return_value=FakeResponse()):
            HankoAuthenticationMiddleware(next_response).process_request(request)

        self.assertTrue(request.user.is_authenticated)
        authenticated_user = cast(ShopUser, request.user)
        self.assertEqual(authenticated_user.email, 'driver@example.com')
        self.assertEqual(request.session.get('hanko_user_id'), 'hanko-user-123')
        self.assertEqual(request.session.get('hanko_email'), 'driver@example.com')

        refreshed_user = get_user_model().objects.get(pk=user.pk)
        self.assertEqual(refreshed_user.email, 'driver@example.com')

    def test_logout_clears_hanko_session_and_redirects(self):
        user = ShopUser.objects.create_user(username='logout-user', email='logout@example.com', password='pass1234')
        self.client.force_login(user)
        self.client.session['hanko_session_token'] = 'session-token-123'
        self.client.session['hanko_user_id'] = 'hanko-user-123'
        self.client.session.save()

        response = self.client.post(reverse('shop-logout'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f"{reverse('shop-login')}?logged_out=1")
        self.assertNotIn('hanko_session_token', self.client.session)
        self.assertNotIn('hanko_user_id', self.client.session)

    @override_settings(HANKO_API_URL='https://hanko.example.com')
    def test_car_list_uses_hanko_session_token_to_authenticate(self):
        factory = RequestFactory()
        request = factory.get(reverse('shop-car-list'))

        def next_response(_request: HttpRequest) -> HttpResponse:
            return HttpResponse()

        SessionMiddleware(next_response).process_request(request)
        request.session['hanko_session_token'] = 'session-token-123'
        request.session.save()
        AuthenticationMiddleware(next_response).process_request(request)

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, str]:
                return {
                    'id': 'hanko-user-123',
                    'email': 'driver@example.com',
                    'name': 'Test Driver',
                    'display_name': 'Test Driver',
                    'avatar_url': 'https://example.com/avatar.png',
                    'provider': 'hanko',
                }

        with patch('shop.middleware.requests.get', return_value=FakeResponse()):
            response = views.car_list(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Cars', response.content)


class GarageSharingTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='pass1234',
        )
        self.member = ShopUser.objects.create_user(
            username='member',
            email='member@example.com',
            password='pass1234',
        )
        self.stranger = ShopUser.objects.create_user(
            username='stranger',
            email='stranger@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Alpha Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )

    def test_create_garage_adds_owner_membership(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-garage-create'),
            data={'name': 'Second Garage', 'description': 'Family vehicles'},
        )

        self.assertEqual(response.status_code, 302)
        created = Garage.objects.get(name='Second Garage')
        self.assertTrue(
            GarageMembership.objects.filter(
                garage=created,
                user=self.owner,
                role=GarageMembership.ROLE_OWNER,
            ).exists()
        )

    @patch('shop.models.garage.send_mail', return_value=1)
    def test_share_garage_creates_pending_invitation(self, _mock_send_mail: object):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-garage-share', args=[self.garage.pk]),
            data={
                'invited_email': 'member@example.com',
                'message': 'Join this garage.',
                'expires_in_days': 14,
            },
        )

        self.assertEqual(response.status_code, 302)
        invitation = GarageInvitation.objects.get(garage=self.garage, invited_email='member@example.com')
        self.assertEqual(invitation.status, GarageInvitation.STATUS_PENDING)
        self.assertEqual(invitation.invited_by, self.owner)
        self.assertIsNotNone(invitation.expires_at)

    @patch('shop.models.garage.send_mail', return_value=1)
    def test_duplicate_pending_invitation_is_not_created(self, _mock_send_mail: object):
        self.client.force_login(self.owner)
        GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='member@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            expires_at=timezone.now() + timedelta(days=14),
        )

        response = self.client.post(
            reverse('shop-garage-share', args=[self.garage.pk]),
            data={
                'invited_email': 'member@example.com',
                'message': 'Second invite',
                'expires_in_days': 14,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            GarageInvitation.objects.filter(
                garage=self.garage,
                invited_email='member@example.com',
                status=GarageInvitation.STATUS_PENDING,
            ).count(),
            1,
        )

    @patch('shop.models.garage.send_mail', return_value=1)
    def test_accept_invitation_adds_membership(self, _mock_send_mail: object):
        invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='member@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            expires_at=timezone.now() + timedelta(days=14),
        )
        self.client.force_login(self.member)

        response = self.client.get(reverse('shop-garage-invitation-accept', args=[invitation.token]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            GarageMembership.objects.filter(
                garage=self.garage,
                user=self.member,
            ).exists()
        )
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, GarageInvitation.STATUS_ACCEPTED)
        self.assertEqual(invitation.accepted_by, self.member)

    def test_accept_invitation_requires_matching_email(self):
        invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='member@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            expires_at=timezone.now() + timedelta(days=14),
        )
        self.client.force_login(self.stranger)

        response = self.client.get(reverse('shop-garage-invitation-accept', args=[invitation.token]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            GarageMembership.objects.filter(
                garage=self.garage,
                user=self.stranger,
            ).exists()
        )
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, GarageInvitation.STATUS_PENDING)

    def test_non_manager_cannot_share_garage(self):
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.member,
            role=GarageMembership.ROLE_MEMBER,
        )
        self.client.force_login(self.member)

        response = self.client.get(reverse('shop-garage-share', args=[self.garage.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-garage-detail', args=[self.garage.pk]))


class FormEditableFieldsCoverageTests(TestCase):
    def _editable_model_field_names(self, model: type[models.Model], *, exclude: set[str] | None = None) -> set[str]:
        excluded = exclude or set()
        return {
            field.name
            for field in model._meta.fields
            if field.editable and not field.auto_created and field.name not in excluded
        }

    def test_car_create_form_covers_editable_car_fields(self):
        expected = self._editable_model_field_names(Car)
        self.assertSetEqual(set(CarCreateForm.base_fields.keys()), expected)

    def test_car_update_form_covers_editable_car_fields(self):
        expected = self._editable_model_field_names(Car)
        self.assertSetEqual(set(CarUpdateForm.base_fields.keys()), expected)

    def test_garage_create_form_covers_user_editable_garage_fields(self):
        expected = self._editable_model_field_names(Garage, exclude={'created_by'})
        self.assertSetEqual(set(GarageCreateForm.base_fields.keys()), expected)

    def test_workjob_form_covers_user_editable_workjob_fields(self):
        expected = self._editable_model_field_names(WorkJob, exclude={'car'})
        self.assertSetEqual(set(WorkJobForm.base_fields.keys()), expected)

    def test_report_form_covers_user_editable_report_fields(self):
        expected = self._editable_model_field_names(Report, exclude={'car'})
        self.assertSetEqual(set(ReportForm.base_fields.keys()), expected)


class JSONImporterTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='import-owner',
            email='import-owner@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Import Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )
        self.importer = JSONImporter()

    def test_car_dry_run_requires_target_garage_and_does_not_persist(self):
        result = self.importer.import_records(
            Car,
            [{'make': 'Toyota', 'model': 'Yaris', 'vin': 'JTDKB20U793512345'}],
            context=ImportContext(garage=self.garage),
            dry_run=True,
        )

        self.assertFalse(result.has_errors)
        self.assertEqual(result.created_count, 1)
        self.assertEqual(Car.objects.count(), 0)

    def test_report_import_parses_lists_and_persists(self):
        car = Car.objects.create(garage=self.garage, make='Honda', model='Civic', vin='2HGFG12698H512345')

        result = self.importer.import_records(
            Report,
            [{
                'car': str(car.pk),
                'job_name': 'Brake service',
                'date_done': '2026-08-01',
                'documents': 'invoice.pdf\nchecklist.pdf',
                'photos': ['before.jpg', 'after.jpg'],
                'mileage': '12345',
            }],
            context=ImportContext(garage=self.garage),
        )

        self.assertFalse(result.has_errors)
        self.assertEqual(result.created_count, 1)
        report_data = Report.objects.filter(job_name='Brake service').values('documents', 'photos', 'mileage').get()
        self.assertEqual(report_data['documents'], ['invoice.pdf', 'checklist.pdf'])
        self.assertEqual(report_data['photos'], ['before.jpg', 'after.jpg'])
        self.assertEqual(report_data['mileage'], 12345)

    def test_workjob_import_rejects_unknown_car(self):
        result = self.importer.import_records(
            WorkJob,
            [{'car': 'missing-car', 'title': 'Oil change'}],
            context=ImportContext(garage=self.garage),
            dry_run=True,
        )

        self.assertTrue(result.has_errors)
        self.assertIn('Car not found', result.errors[0].message)


class ImportJsonCommandTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='command-owner',
            email='command-owner@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Command Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )

    def test_car_import_command_dry_run_validates_without_persisting(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            json.dump([{'make': 'Mazda', 'model': '3', 'vin': 'JM1BK323171512345'}], handle)
            temp_path = handle.name

        output = StringIO()
        try:
            call_command(
                'import_json',
                'Car',
                temp_path,
                '--garage',
                str(self.garage.pk),
                '--dry-run',
                stdout=output,
            )
        finally:
            Path(temp_path).unlink(missing_ok=True)

        self.assertIn('Dry run complete', output.getvalue())
        self.assertEqual(Car.objects.count(), 0)


class GarageImportViewTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='garage-owner',
            email='garage-owner@example.com',
            password='pass1234',
        )
        self.member = ShopUser.objects.create_user(
            username='garage-member',
            email='garage-member@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Upload Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.member,
            role=GarageMembership.ROLE_MEMBER,
        )

    def test_non_manager_is_redirected_from_garage_import(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse('shop-garage-import', args=[self.garage.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-garage-detail', args=[self.garage.pk]))

    def test_manager_can_dry_run_car_import_from_upload(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile(
            'cars.json',
            json.dumps([{'make': 'Subaru', 'model': 'Outback', 'vin': '4S4BSENC0J3351234'}]).encode('utf-8'),
            content_type='application/json',
        )

        response = self.client.post(
            reverse('shop-garage-import', args=[self.garage.pk]),
            data={
                'import_file': upload,
                'dry_run': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        messages = list(response.context['messages'])
        self.assertTrue(any('Dry run complete' in str(message) for message in messages))
        self.assertEqual(Car.objects.count(), 0)

    def test_manager_can_import_cars_into_selected_garage(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile(
            'cars.json',
            json.dumps([{'make': 'Ford', 'model': 'Focus', 'vin': '1FAHP3F28CL512345'}]).encode('utf-8'),
            content_type='application/json',
        )

        response = self.client.post(
            reverse('shop-garage-import', args=[self.garage.pk]),
            data={
                'import_file': upload,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        car = Car.objects.get(vin='1FAHP3F28CL512345')
        self.assertEqual(car.garage, self.garage)


class CarImportViewTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='car-owner',
            email='car-owner@example.com',
            password='pass1234',
        )
        self.member = ShopUser.objects.create_user(
            username='car-member',
            email='car-member@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Car Import Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.member,
            role=GarageMembership.ROLE_MEMBER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            usual_name='Daily Driver',
            make='Toyota',
            model='Corolla',
            vin='2T1BURHE5JC512345',
        )

    def test_non_manager_is_redirected_from_car_import(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse('shop-car-import', args=[self.car.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-car-detail', args=[self.car.pk]))

    def test_manager_can_dry_run_workjob_import_for_selected_car(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile(
            'workjobs.json',
            json.dumps([{'title': 'Oil change', 'planned_date': '2026-08-02'}]).encode('utf-8'),
            content_type='application/json',
        )

        response = self.client.post(
            reverse('shop-car-import', args=[self.car.pk]),
            data={
                'import_type': 'workjob',
                'import_file': upload,
                'dry_run': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        messages = list(response.context['messages'])
        self.assertTrue(any('Dry run complete' in str(message) for message in messages))
        self.assertEqual(WorkJob.objects.count(), 0)

    def test_manager_can_import_report_for_selected_car_without_car_field(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile(
            'reports.json',
            json.dumps([{'job_name': 'Brake service', 'date_done': '2026-08-03', 'note': 'Pads replaced'}]).encode('utf-8'),
            content_type='application/json',
        )

        response = self.client.post(
            reverse('shop-car-import', args=[self.car.pk]),
            data={
                'import_type': 'report',
                'import_file': upload,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        report = Report.objects.get(job_name='Brake service')
        self.assertEqual(report.car, self.car)
