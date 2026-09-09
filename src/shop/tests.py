import json
import tempfile
import uuid
from datetime import date, timedelta
from io import BytesIO
from io import StringIO
from pathlib import Path
from typing import cast
from unittest.mock import patch

import csv
import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.mail import EmailMessage
from django.db import IntegrityError, models, transaction
from django.http import HttpRequest, HttpResponse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from shop import views
from shop.auth import (
    HankoAuthenticationError,
    _build_username,
    complete_hanko_login,
    fetch_hanko_userinfo,
    sync_hanko_user,
)
from shop.exporters import export_garage_to_excel
from shop.forms import (
    CarCreateForm,
    CarImportForm,
    CarUpdateForm,
    GarageCreateForm,
    GarageImportForm,
    KnownShopProofForm,
    ReportForm,
    WorkJobForm,
)
from shop.importers import CSVImporter, ImportContext, ImportValidationError
from shop.mailgun_backend import MailgunEmailBackend
from shop.middleware import HankoAuthenticationMiddleware, hanko_login_required
from shop.models.car import Car, CarPart, CarPartStatusHistory
from shop.models.garage import Garage, GarageInvitation, GarageMembership, KnownShop, KnownShopProof
from shop.models.job import WorkJob
from shop.models.report import Report, ReportAttachment
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
            },
            "session_token": "session-token-123",
        }

        with patch('shop.auth.requests.get', return_value=FakeHankoResponse({
            'id': 'hanko-user-123',
            'email': 'driver@example.com',
            'name': 'Test Driver',
            'display_name': 'Test Driver',
            'avatar_url': 'https://example.com/avatar.png',
            'provider': 'hanko',
        })):
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
        self.assertFalse(user.garages.exists())

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

        with patch('shop.auth.requests.get', return_value=FakeResponse()):
            self.client.get(reverse('shop-index'))

        factory = RequestFactory()
        request = factory.get(reverse('shop-index'))

        def next_response(_request: HttpRequest) -> HttpResponse:
            return HttpResponse()

        SessionMiddleware(next_response).process_request(request)
        request.session['hanko_session_token'] = 'session-token-123'
        request.session.save()
        AuthenticationMiddleware(next_response).process_request(request)

        with patch('shop.auth.requests.get', return_value=FakeResponse()):
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
        self.assertEqual(response['Location'], reverse('shop-login'))
        self.assertNotIn('hanko_session_token', self.client.session)
        self.assertNotIn('hanko_user_id', self.client.session)

    def test_logout_marker_is_one_time_in_login_context(self):
        user = ShopUser.objects.create_user(username='logout-user-2', email='logout2@example.com', password='pass1234')
        self.client.force_login(user)

        self.client.post(reverse('shop-logout'))

        first_login_page = self.client.get(reverse('shop-login'))
        second_login_page = self.client.get(reverse('shop-login'))

        self.assertEqual(first_login_page.context['logged_out'], True)
        self.assertEqual(second_login_page.context['logged_out'], False)

    @override_settings(
        ALLOWED_HOSTS=['xps-server.kanyu-bluegill.ts.net'],
        CSRF_TRUSTED_ORIGINS=['https://xps-server.kanyu-bluegill.ts.net'],
    )
    def test_logout_with_trusted_origin_succeeds(self):
        from django.test import Client
        from django.middleware.csrf import get_token
        client = Client(enforce_csrf_checks=True)
        user = ShopUser.objects.create_user(username='csrf-user', email='csrf@example.com', password='pass1234')
        client.force_login(user)

        # login_view doesn't render a {% csrf_token %} tag, so no CSRF cookie
        # is ever set by the response. Generate a token directly and seed it
        # on the client so both the cookie and the submitted form field agree.
        csrf_token = get_token(RequestFactory().get('/'))
        client.cookies['csrftoken'] = csrf_token

        # Untrusted origin fails CSRF check with 403
        untrusted_resp = client.post(
            reverse('shop-logout'),
            {'csrfmiddlewaretoken': csrf_token},
            HTTP_ORIGIN='https://untrusted-domain.com',
            HTTP_HOST='xps-server.kanyu-bluegill.ts.net',
        )
        self.assertEqual(untrusted_resp.status_code, 403)

        # Trusted origin succeeds with 302
        trusted_resp = client.post(
            reverse('shop-logout'),
            {'csrfmiddlewaretoken': csrf_token},
            HTTP_ORIGIN='https://xps-server.kanyu-bluegill.ts.net',
            HTTP_HOST='xps-server.kanyu-bluegill.ts.net',
        )
        self.assertEqual(trusted_resp.status_code, 302)

    def test_theme_preference_sets_cookie_and_redirects(self):
        response = self.client.get(
            reverse('shop-theme', kwargs={'theme': 'dark'}),
            {'next': reverse('shop-login')},
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-login'))
        self.assertEqual(response.cookies['theme'].value, 'dark')
        self.assertEqual(response.cookies['theme']['max-age'], '31536000')

    def test_login_page_renders_current_theme_attribute(self):
        response = self.client.get(reverse('shop-login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-theme="light"')

    def test_login_page_includes_mobile_viewport_and_theme_toggle(self):
        response = self.client.get(reverse('shop-login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<meta name="viewport"')
        self.assertContains(response, 'Light mode')
        self.assertContains(response, 'Dark mode')
        self.assertContains(response, 'beta')
        self.assertContains(response, 'theme-beta')

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

        with patch('shop.auth.requests.get', return_value=FakeResponse()):
            response = views.car_list(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Cars', response.content)


class HankoCallbackSecurityTests(TestCase):
    def test_callback_requires_a_session_token(self):
        response = self.client.post(
            reverse('shop-hanko-callback'),
            data=json.dumps({'user': {'id': 'forged-user', 'email': 'forged@example.com'}}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Missing session token')
        self.assertFalse(ShopUser.objects.exists())

    @override_settings(HANKO_API_URL='https://hanko.example.com')
    def test_callback_uses_verified_hanko_identity_instead_of_client_payload(self):
        payload = {
            'user': {
                'id': 'attacker-controlled-id',
                'email': 'victim@example.com',
                'name': 'Attacker supplied name',
            },
            'session_token': 'verified-session-token',
        }

        with patch('shop.auth.requests.get', return_value=FakeHankoResponse({
            'id': 'verified-hanko-id',
            'email': 'verified@example.com',
            'name': 'Verified User',
            'provider': 'hanko',
        })) as request:
            response = self.client.post(
                reverse('shop-hanko-callback'),
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['email'], 'verified@example.com')
        self.assertFalse(ShopUser.objects.filter(email='victim@example.com').exists())
        self.assertTrue(ShopUser.objects.filter(email='verified@example.com').exists())
        request.assert_called_once_with(
            'https://hanko.example.com/userinfo',
            headers={'Authorization': 'Bearer verified-session-token'},
            timeout=5,
        )

    def test_callback_fails_closed_when_hanko_rejects_the_token(self):
        with patch('shop.auth.requests.get', side_effect=requests.HTTPError('invalid token')):
            response = self.client.post(
                reverse('shop-hanko-callback'),
                data=json.dumps({
                    'user': {'id': 'forged-id', 'email': 'forged@example.com'},
                    'session_token': 'invalid-token',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'Invalid Hanko session')
        self.assertFalse(ShopUser.objects.exists())
        self.assertNotIn('hanko_session_token', self.client.session)

    def test_callback_requires_csrf_protection(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse('shop-hanko-callback'),
            data=json.dumps({'session_token': 'token'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)


class FakeHankoResponse:
    def __init__(self, payload: object):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class ShopUserIdentityTests(TestCase):
    def test_non_empty_emails_are_unique_case_insensitively(self):
        ShopUser.objects.create_user(
            username='identity-one',
            email='Identity@example.com',
            password='pass1234',
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShopUser.objects.create_user(
                    username='identity-two',
                    email='identity@example.com',
                    password='pass1234',
                )

    def test_hanko_email_is_normalized_before_account_creation(self):
        user = sync_hanko_user(
            hanko_id='normalized-hanko-id',
            email='  User@Example.COM ',
            username='Normalized User',
        )

        self.assertEqual(user.email, 'user@example.com')


class CarPartStatusTrackingTests(TestCase):
    def setUp(self) -> None:
        self.garage = Garage.objects.create(name='North Garage')
        self.car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Corolla',
            colour='Blue',
            year=2022,
            vin='1HGBH41JXMN109186',
            license_plate='ABC123',
        )

    def test_part_status_changes_are_recorded_with_timestamps(self):
        part = CarPart.objects.create(
            car=self.car,
            name='Brake pads',
            status=CarPart.STATUS_NEW,
            notes='Initial issue spotted on inspection.',
        )

        self.assertEqual(part.status, CarPart.STATUS_NEW)
        self.assertEqual(part.status_history.count(), 1)

        part.update_status(CarPart.STATUS_ORDERED, note='Ordered replacement set from supplier.')
        part.refresh_from_db()

        self.assertEqual(part.status, CarPart.STATUS_ORDERED)
        self.assertEqual(part.status_history.count(), 2)

        first_event = part.status_history.order_by('changed_at').first()
        second_event = part.status_history.order_by('changed_at').last()

        self.assertEqual(first_event.previous_status, '')
        self.assertEqual(first_event.new_status, CarPart.STATUS_NEW)
        self.assertIsNotNone(first_event.changed_at)

        self.assertEqual(second_event.previous_status, CarPart.STATUS_NEW)
        self.assertEqual(second_event.new_status, CarPart.STATUS_ORDERED)
        self.assertEqual(second_event.note, 'Ordered replacement set from supplier.')
        self.assertIsNotNone(second_event.changed_at)


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

    def test_owner_can_delete_car_from_car_list(self):
        self.client.force_login(self.owner)
        car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Yaris',
            vin='JTDKB20U793512345',
        )

        response = self.client.post(reverse('shop-car-delete', args=[car.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-car-list'))
        self.assertFalse(Car.objects.filter(pk=car.pk).exists())


class KnownShopTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='shop-user',
            email='shop-user@example.com',
            password='pass1234',
        )
        self.other_user = ShopUser.objects.create_user(
            username='other-shop-user',
            email='other-shop-user@example.com',
            password='pass1234',
        )

    def test_user_can_add_shop_and_proof(self):
        self.client.force_login(self.user)

        shop_response = self.client.post(
            reverse('shop-known-shop-create'),
            data={
                'name': 'Northside Auto',
                'email': 'service@northside.example',
                'phone': '555-0100',
                'address': '10 Main Street',
                'notes': 'Recommended by the fleet manager.',
            },
        )

        self.assertEqual(shop_response.status_code, 302)
        shop = KnownShop.objects.get(name='Northside Auto')
        self.assertEqual(shop.created_by, self.user)
        proof_response = self.client.post(
            reverse('shop-known-shop-proof-create', args=[shop.pk]),
            data={
                'title': 'Business registration',
                'content': 'Registration document received.',
                'file': SimpleUploadedFile('registration.pdf', b'%PDF-1.4 proof', content_type='application/pdf'),
            },
        )

        self.assertEqual(proof_response.status_code, 302)
        proof = KnownShopProof.objects.get(shop=shop)
        self.assertEqual(proof.title, 'Business registration')
        self.assertIn('registration', proof.file.name)
        self.assertTrue(proof.file.name.endswith('.pdf'))

    def test_other_user_cannot_view_or_add_proof_to_owned_shop(self):
        shop = KnownShop.objects.create(name='Private Shop', created_by=self.user)
        self.client.force_login(self.other_user)

        detail_response = self.client.get(reverse('shop-known-shop-detail', args=[shop.pk]))
        proof_response = self.client.get(reverse('shop-known-shop-proof-create', args=[shop.pk]))

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(proof_response.status_code, 404)

    def test_known_shop_model_str_and_invitation_methods(self):
        shop = KnownShop.objects.create(name='Str Shop', created_by=self.user)
        self.assertEqual(str(shop), 'Str Shop')

        proof = KnownShopProof.objects.create(shop=shop, title='Str Proof')
        self.assertEqual(str(proof), 'Str Proof (Str Shop)')

        garage = Garage.objects.create(name='Str Garage', created_by=self.user)
        membership = GarageMembership.objects.create(
            garage=garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )
        self.assertIn('owner', str(membership))

        invitation = GarageInvitation.objects.create(
            garage=garage,
            invited_email='invite@example.com',
            invited_by=self.user,
        )
        self.assertIn('invite@example.com', str(invitation))

        with patch('shop.models.garage.send_mail', return_value=1):
            sent_count = invitation.send_invitation_email(
                accept_base_url='https://example.com/accept',
                sender_email='from@example.com',
            )
        self.assertEqual(sent_count, 1)

        invitation_with_message = GarageInvitation.objects.create(
            garage=garage,
            invited_email='invite-message@example.com',
            invited_by=self.user,
            message='Please join our fleet.',
        )
        with patch('shop.models.garage.send_mail', return_value=1) as mock_send:
            invitation_with_message.send_invitation_email(accept_base_url='https://example.com/accept')
            self.assertIn('Please join our fleet.', mock_send.call_args[1]['message'])

    def test_known_shop_proof_file_deleted_on_model_delete(self):
        shop = KnownShop.objects.create(name='Delete Proof Shop', created_by=self.user)
        proof = KnownShopProof.objects.create(
            shop=shop,
            title='Delete proof',
            file=SimpleUploadedFile('delete.pdf', b'%PDF-1.4 delete', content_type='application/pdf'),
        )
        file_path = proof.file.path
        self.assertTrue(Path(file_path).exists())
        proof.delete()
        self.assertFalse(Path(file_path).exists())

    def test_known_shop_proof_file_requires_authentication(self):
        self.client.force_login(self.user)
        shop = KnownShop.objects.create(name='Proof Shop', created_by=self.user)
        proof = KnownShopProof.objects.create(
            shop=shop,
            title='Insurance proof',
            file=SimpleUploadedFile(
                'insurance.pdf',
                b'%PDF-1.4 shop proof',
                content_type='application/pdf',
            ),
        )

        try:
            response = self.client.get(
                reverse('shop-known-shop-proof-file', args=[shop.pk, proof.pk]),
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/pdf')
            self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 shop proof')

            self.client.logout()
            anonymous_response = self.client.get(
                reverse('shop-known-shop-proof-file', args=[shop.pk, proof.pk]),
            )
            self.assertEqual(anonymous_response.status_code, 302)
        finally:
            proof.file.delete(save=False)


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
        actual = set(ReportForm.base_fields.keys())
        self.assertTrue(expected.issubset(actual))
        self.assertSetEqual(actual - expected, {'attachments', 'external_links'})


class ColourFieldTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='colour-owner',
            email='colour-owner@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Colour Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )

    def test_car_persists_colour_field(self):
        car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Yaris',
            colour='Noir',
            vin='JTDKB20U793512346',
        )
        car.refresh_from_db()
        self.assertEqual(car.colour, 'Noir')

    def test_car_create_form_includes_colour_field_with_british_label(self):
        self.assertIn('colour', CarCreateForm.base_fields)
        form = CarCreateForm(user=self.user)
        self.assertEqual(form.fields['colour'].label, 'Colour')

    def test_importer_reads_colour_key_from_record(self):
        importer = CSVImporter()
        result = importer.import_records(
            Car,
            [{
                'make': 'Toyota',
                'model': 'Yaris',
                'colour': 'Blanc',
                'vin': 'JTDKB20U793512347',
            }],
            context=ImportContext(garage=self.garage),
        )

        self.assertFalse(result.has_errors)
        self.assertEqual(result.created_count, 1)
        car = Car.objects.get(vin='JTDKB20U793512347')
        self.assertEqual(car.colour, 'Blanc')

    def test_car_list_renders_colour_label_and_value(self):
        self.client.force_login(self.user)
        Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Yaris',
            colour='Noir',
            vin='JTDKB20U793512348',
        )

        response = self.client.get(reverse('shop-car-list'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Colour:', response.content)
        self.assertIn(b'Noir', response.content)

    def test_car_detail_renders_colour_label_and_value(self):
        self.client.force_login(self.user)
        car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Yaris',
            colour='Noir',
            vin='JTDKB20U793512349',
        )

        response = self.client.get(reverse('shop-car-detail', args=[car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Colour:', response.content)
        self.assertIn(b'Noir', response.content)


class ReportAttachmentTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='report-owner',
            email='report-owner@example.com',
            password='pass1234',
            is_mechanic=True,
        )
        self.stranger = ShopUser.objects.create_user(
            username='report-stranger',
            email='report-stranger@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Report Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Prius',
            vin='JTDKB20U123456789',
        )

    def test_report_create_accepts_uploads_and_external_links(self):
        self.client.force_login(self.user)
        image = SimpleUploadedFile('before.png', b'fake-image', content_type='image/png')
        video = SimpleUploadedFile('clip.mp4', b'fake-video', content_type='video/mp4')

        job_name = f'Brake service {self._testMethodName}'
        response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data={
                'mileage': '125000',
                'job_name': job_name,
                'date_done': '2026-08-09',
                'note': 'Replaced brake pads',
                'additional_information': 'Used OEM parts and torqued wheels to spec',
                'external_links': 'https://onedrive.example.com/share/abc\nhttps://drive.google.com/file/d/123/view',
                'attachments': [image, video],
            },
        )

        self.assertEqual(response.status_code, 302)
        report = Report.objects.get(job_name=job_name)
        self.assertEqual(report.attachments.count(), 4)
        self.assertEqual(report.attachments.filter(source_type='upload').count(), 2)
        self.assertEqual(report.attachments.filter(source_type='external').count(), 2)
        self.assertEqual(report.additional_information, 'Used OEM parts and torqued wheels to spec')
        self.assertTrue(report.attachments.filter(source_type='external').exists())
        self.assertTrue(report.attachments.filter(source_type='upload', kind='image').exists())
        self.assertTrue(report.attachments.filter(source_type='upload', kind='video').exists())
        attachment_urls = {attachment.url for attachment in report.attachments.all()}
        self.assertIn('https://onedrive.example.com/share/abc', attachment_urls)
        self.assertIn('https://drive.google.com/file/d/123/view', attachment_urls)

    def test_report_form_rejects_unsafe_links_and_upload_types(self):
        unsafe_link_form = ReportForm(data={
            'job_name': 'Unsafe link',
            'date_done': '2026-08-10',
            'external_links': 'javascript:alert(1)',
        })
        self.assertFalse(unsafe_link_form.is_valid())
        self.assertIn('external_links', unsafe_link_form.errors)

        unsafe_file_form = ReportForm(
            data={
                'job_name': 'Executable attachment',
                'date_done': '2026-08-10',
            },
            files={
                'attachments': SimpleUploadedFile(
                    'payload.exe',
                    b'MZ executable',
                    content_type='application/x-msdownload',
                ),
            },
        )
        self.assertFalse(unsafe_file_form.is_valid())
        self.assertIn('attachments', unsafe_file_form.errors)

    def test_uploaded_report_attachment_is_streamed_only_to_car_members(self):
        report = Report.objects.create(
            car=self.car,
            job_name='Uploaded invoice',
            date_done='2026-08-10',
        )
        attachment = ReportAttachment.objects.create(
            report=report,
            file=SimpleUploadedFile(
                'invoice.pdf',
                b'%PDF-1.4 invoice',
                content_type='application/pdf',
            ),
        )

        try:
            self.client.force_login(self.user)
            response = self.client.get(
                reverse(
                    'shop-report-attachment-file',
                    args=[self.car.pk, report.pk, attachment.pk],
                ),
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 invoice')

            self.client.force_login(self.stranger)
            forbidden_response = self.client.get(
                reverse(
                    'shop-report-attachment-file',
                    args=[self.car.pk, report.pk, attachment.pk],
                ),
            )
            self.assertEqual(forbidden_response.status_code, 404)
        finally:
            attachment.file.delete(save=False)

    def test_car_detail_renders_attachment_preview_links(self):
        self.client.force_login(self.user)
        report = Report.objects.create(
            car=self.car,
            job_name='Oil change',
            date_done='2026-08-10',
            note='Completed',
        )
        ReportAttachment.objects.create(
            report=report,
            source_type='external',
            url='https://drive.google.com/file/d/456/view',
            display_name='Service checklist',
            kind='link',
        )

        response = self.client.get(reverse('shop-car-detail', args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Service checklist')
        self.assertContains(response, 'https://drive.google.com/file/d/456/view')


class CSVImporterTests(TestCase):
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
        self.importer = CSVImporter()

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
                'photos': 'before.jpg\nafter.jpg',
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

    def test_workjob_import_requires_garage_scope(self):
        car = Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512345',
        )

        result = self.importer.import_records(
            WorkJob,
            [{'car': str(car.pk), 'title': 'Oil change'}],
            context=ImportContext(),
            dry_run=True,
        )

        self.assertTrue(result.has_errors)
        self.assertIn('target garage or car context', result.errors[0].message)

    def test_car_resolver_handles_malformed_uuid_without_leaking_validation_error(self):
        result = self.importer.import_records(
            WorkJob,
            [{'car': '00000000-0000-0000-0000-invalid', 'title': 'Oil change'}],
            context=ImportContext(garage=self.garage),
            dry_run=True,
        )

        self.assertTrue(result.has_errors)
        self.assertIn('Car not found', result.errors[0].message)


class ImportCsvCommandTests(TestCase):
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
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('make,model,vin\nMazda,3,JM1BK323171512345\n')
            temp_path = handle.name

        output = StringIO()
        try:
            call_command(
                'import_csv',
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

    def test_import_command_rejects_invalid_garage_uuid(self):
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('make,model,vin\nMazda,3,JM1BK323171512345\n')
            temp_path = handle.name

        try:
            with self.assertRaises(CommandError):
                call_command('import_csv', 'Car', temp_path, '--garage', 'not-a-uuid')
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_import_command_rejects_non_positive_batch_size(self):
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('make,model,vin\nMazda,3,JM1BK323171512345\n')
            temp_path = handle.name

        try:
            with self.assertRaises(CommandError):
                call_command(
                    'import_csv',
                    'Car',
                    temp_path,
                    '--garage',
                    str(self.garage.pk),
                    '--batch-size',
                    '0',
                )
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_export_garage_command_writes_excel_file(self):
        Car.objects.create(
            garage=self.garage,
            usual_name='Command Export Car',
            make='Mazda',
            model='3',
            vin='JM1BK323171512345',
        )
        output = StringIO()

        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as handle:
            output_path = Path(handle.name)
        output_path.unlink(missing_ok=True)

        try:
            call_command(
                'export_garage',
                str(self.garage.pk),
                '--output',
                str(output_path),
                stdout=output,
            )
            self.assertTrue(output_path.exists())
            workbook = load_workbook(filename=str(output_path))
            self.assertIn('cars_import', workbook.sheetnames)
            cars_sheet = workbook['cars_import']
            rows = list(cars_sheet.iter_rows(min_row=2, values_only=True))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][3], 'Mazda')
        finally:
            output_path.unlink(missing_ok=True)

    def test_export_garage_command_errors_for_unknown_garage(self):
        with self.assertRaises(CommandError):
            call_command('export_garage', str(uuid.uuid4()))

    def test_export_garage_command_rejects_invalid_garage_uuid(self):
        with self.assertRaises(CommandError):
            call_command('export_garage', 'not-a-uuid')


class GarageExportServiceTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='export-owner',
            email='export-owner@example.com',
            password='pass1234',
            is_mechanic=True,
        )
        self.garage = Garage.objects.create(name='Primary Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )

        self.other_garage = Garage.objects.create(name='Other Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.other_garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )

        self.primary_car = Car.objects.create(
            garage=self.garage,
            usual_name='Daily Driver',
            make='Toyota',
            model='Corolla',
            vin='2T1BURHE5JC512345',
        )
        self.other_car = Car.objects.create(
            garage=self.other_garage,
            usual_name='Spare Car',
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512345',
        )

        WorkJob.objects.create(
            car=self.primary_car,
            title='Oil Change',
            assigned_to=self.owner,
            required_items=['Oil', 'Filter'],
            status='pending',
            urgency='soon',
        )
        WorkJob.objects.create(
            car=self.other_car,
            title='Do Not Export',
        )

        Report.objects.create(
            car=self.primary_car,
            mileage=120000,
            job_name='Brake Service',
            assigned_to=self.owner,
            date_done=timezone.now().date(),
            documents=['invoice.pdf'],
            photos=['before.jpg', 'after.jpg'],
        )
        Report.objects.create(
            car=self.other_car,
            job_name='Skip Report',
            date_done=timezone.now().date(),
        )

    def test_export_garage_to_excel_includes_expected_sheets_and_rows(self):
        workbook_file = export_garage_to_excel(self.garage)
        workbook = load_workbook(filename=BytesIO(workbook_file.content))

        self.assertIn('meta', workbook.sheetnames)
        self.assertIn('garage', workbook.sheetnames)
        self.assertIn('memberships', workbook.sheetnames)
        self.assertIn('cars_import', workbook.sheetnames)
        self.assertIn('workjobs_import', workbook.sheetnames)
        self.assertIn('reports_import', workbook.sheetnames)

        cars_rows = list(workbook['cars_import'].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(cars_rows), 1)
        self.assertEqual(cars_rows[0][3], 'Toyota')
        self.assertNotIn('2HGFG12698H512345', [row[7] for row in cars_rows])

        job_rows = list(workbook['workjobs_import'].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(job_rows), 1)
        self.assertEqual(job_rows[0][3], 'Oil Change')
        self.assertEqual(job_rows[0][14], 'Oil\nFilter')

        report_rows = list(workbook['reports_import'].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(report_rows), 1)
        self.assertEqual(report_rows[0][4], 'Brake Service')
        self.assertEqual(report_rows[0][12], 'invoice.pdf')
        self.assertEqual(report_rows[0][13], 'before.jpg\nafter.jpg')


class GarageExportViewTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='export-view-owner',
            email='export-view-owner@example.com',
            password='pass1234',
            is_mechanic=True,
        )
        self.manager = ShopUser.objects.create_user(
            username='export-view-manager',
            email='export-view-manager@example.com',
            password='pass1234',
        )
        self.member = ShopUser.objects.create_user(
            username='export-view-member',
            email='export-view-member@example.com',
            password='pass1234',
        )

        self.garage = Garage.objects.create(name='Export View Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.manager,
            role=GarageMembership.ROLE_MANAGER,
        )
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.member,
            role=GarageMembership.ROLE_MEMBER,
        )

        self.primary_car = Car.objects.create(
            garage=self.garage,
            usual_name='Exportable',
            make='Ford',
            model='Focus',
            vin='1FAHP3F28CL512345',
        )

        self.other_garage = Garage.objects.create(name='External Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.other_garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        Car.objects.create(
            garage=self.other_garage,
            usual_name='Hidden',
            make='Tesla',
            model='Model 3',
            vin='5YJ3E1EA7LF512345',
        )

    def test_unauthenticated_user_is_redirected_from_garage_export(self):
        response = self.client.get(reverse('shop-garage-export', args=[self.garage.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(f"{reverse('shop-login')}?next="))

    def test_non_manager_is_redirected_from_garage_export(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse('shop-garage-export', args=[self.garage.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-garage-detail', args=[self.garage.pk]))

    def test_manager_can_download_garage_export_workbook(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse('shop-garage-export', args=[self.garage.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertIn('attachment; filename="garage_export-view-garage_', response['Content-Disposition'])

        workbook = load_workbook(filename=BytesIO(response.content))
        cars_rows = list(workbook['cars_import'].iter_rows(min_row=2, values_only=True))
        vins = [row[7] for row in cars_rows]
        self.assertIn('1FAHP3F28CL512345', vins)
        self.assertNotIn('5YJ3E1EA7LF512345', vins)


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
            'cars.csv',
            b'make,model,vin\nSubaru,Outback,4S4BSENC0J3351234',
            content_type='text/csv',
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
            'cars.csv',
            b'make,model,vin\nFord,Focus,1FAHP3F28CL512345',
            content_type='text/csv',
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
            'workjobs.csv',
            b'title,planned_date\nOil change,2026-08-02',
            content_type='text/csv',
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
            'reports.csv',
            b'job_name,date_done,note\nBrake service,2026-08-03,Pads replaced',
            content_type='text/csv',
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


class AdditionalCoverageRegressionTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='coverage-owner',
            email='coverage-owner@example.com',
            password='pass1234',
            is_mechanic=True,
        )
        self.member = ShopUser.objects.create_user(
            username='coverage-member',
            email='coverage-member@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Coverage Garage', created_by=self.owner)
        GarageMembership.objects.create(garage=self.garage, user=self.owner, role=GarageMembership.ROLE_OWNER)
        GarageMembership.objects.create(garage=self.garage, user=self.member, role=GarageMembership.ROLE_MEMBER)
        self.car = Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Accord',
            vin='1HGCM82633A004352',
        )

    def test_login_theme_and_hanko_callback_branches(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shop-login'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-index'))

        self.client.logout()
        session = self.client.session
        session['logged_out'] = True
        session.save()
        login_response = self.client.get(reverse('shop-login'))
        self.assertTrue(login_response.context['logged_out'])

        invalid_theme = self.client.get(reverse('shop-theme', kwargs={'theme': 'banana'}), {'next': reverse('shop-login')})
        self.assertEqual(invalid_theme.cookies['theme'].value, 'light')

        dark_theme = self.client.get(reverse('shop-theme', kwargs={'theme': 'dark'}), {'next': reverse('shop-login')})
        self.assertEqual(dark_theme.cookies['theme'].value, 'dark')

        empty_payload = self.client.post(reverse('shop-hanko-callback'), data='not-json', content_type='application/json')
        self.assertEqual(empty_payload.status_code, 400)
        self.assertEqual(empty_payload.json()['error'], 'Missing user payload')

        valid_payload = {
            'user': {
                'id': 'hanko-coverage',
                'email': 'new-coverage@example.com',
                'name': 'Coverage User',
                'display_name': 'Coverage User',
                'provider': 'hanko',
            },
            'session_token': 'token-coverage-123',
        }
        with patch('shop.auth.requests.get', return_value=FakeHankoResponse({
            'id': 'hanko-coverage',
            'email': 'new-coverage@example.com',
            'name': 'Coverage User',
            'display_name': 'Coverage User',
            'provider': 'hanko',
        })):
            callback_response = self.client.post(
                reverse('shop-hanko-callback'),
                data=json.dumps(valid_payload),
                content_type='application/json',
            )
        self.assertEqual(callback_response.status_code, 200)
        self.assertEqual(callback_response.json()['user']['email'], 'new-coverage@example.com')
        self.assertEqual(self.client.session['hanko_session_token'], 'token-coverage-123')

    def test_garage_share_and_invitation_branches(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse('shop-garage-share', args=[self.garage.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-garage-detail', args=[self.garage.pk]))

        self.client.force_login(self.owner)
        with patch('shop.models.garage.send_mail', side_effect=Exception('mail failed')):
            response = self.client.post(
                reverse('shop-garage-share', args=[self.garage.pk]),
                data={
                    'invited_email': 'someone@example.com',
                    'message': 'Join us',
                    'expires_in_days': 7,
                },
                follow=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(GarageInvitation.objects.filter(invited_email='someone@example.com').exists())

        invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='coverage-member@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.client.force_login(self.member)
        response = self.client.get(reverse('shop-garage-invitation-accept', args=[invitation.token]), follow=True)
        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, GarageInvitation.STATUS_EXPIRED)

        other_invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='coverage-member@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shop-garage-invitation-accept', args=[other_invitation.token]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], reverse('shop-index'))

    def test_car_crud_and_report_workflow_views(self):
        self.client.force_login(self.owner)
        create_response = self.client.post(
            reverse('shop-car-create'),
            data={
                'garage': str(self.garage.pk),
                'usual_name': 'Roadster',
                'make': 'Mazda',
                'model': 'MX-5',
                'colour': 'Red',
                'year': '2024',
                'vin': 'JM1NDAB77P0112345',
                'license_plate': 'ABC 123',
            },
        )
        self.assertEqual(create_response.status_code, 302)
        created_car = Car.objects.get(vin='JM1NDAB77P0112345')

        update_response = self.client.post(
            reverse('shop-car-update', args=[created_car.pk]),
            data={
                'garage': str(self.garage.pk),
                'usual_name': 'Roadster Updated',
                'make': 'Mazda',
                'model': 'MX-5',
                'colour': 'Blue',
                'year': '2024',
                'vin': 'JM1NDAB77P0112345',
                'license_plate': 'XYZ 999',
            },
        )
        self.assertEqual(update_response.status_code, 302)
        created_car.refresh_from_db()
        self.assertEqual(created_car.usual_name, 'Roadster Updated')

        part_response = self.client.post(
            reverse('shop-part-create', args=[created_car.pk]),
            data={'name': 'Brake pads', 'status': CarPart.STATUS_NEW, 'notes': 'Initial inspection'},
        )
        self.assertEqual(part_response.status_code, 302)
        part = created_car.parts.get(name='Brake pads')

        workjob_response = self.client.post(
            reverse('shop-workjob-create', args=[created_car.pk]),
            data={
                'title': 'Oil service',
                'maintenance_type': 'service',
                'assigned_to': str(self.owner.pk),
                'planned_date': '2026-08-11',
                'status': 'pending',
                'urgency': 'soon',
                'required_items': 'Oil\nFilter',
                'notes': 'Routine service',
            },
        )
        self.assertEqual(workjob_response.status_code, 302)
        work_job = WorkJob.objects.get(title='Oil service')

        report_response = self.client.post(
            reverse('shop-report-create', args=[created_car.pk]),
            data={
                'mileage': '10000',
                'job_name': 'Oil service',
                'date_done': '2026-08-12',
                'documents': 'invoice.pdf',
                'photos': 'before.jpg',
                'external_links': 'https://example.com/invoice',
                'note': 'Completed',
                'additional_information': 'Used synthetic oil',
            },
        )
        self.assertEqual(report_response.status_code, 302)
        report = Report.objects.get(job_name='Oil service')

        self.client.post(reverse('shop-logout'))
        first_login = self.client.get(reverse('shop-login'))
        self.assertTrue(first_login.context['logged_out'])

        second_login = self.client.get(reverse('shop-login'))
        self.assertFalse(second_login.context['logged_out'])

        part_update_response = self.client.post(
            reverse('shop-part-update', args=[created_car.pk, part.pk]),
            data={'name': 'Brake pads', 'status': CarPart.STATUS_ORDERED, 'notes': 'Parts ordered'},
        )
        self.assertEqual(part_update_response.status_code, 302)

        workjob_update_response = self.client.post(
            reverse('shop-workjob-update', args=[created_car.pk, work_job.pk]),
            data={
                'title': 'Oil service',
                'maintenance_type': 'service',
                'assigned_to': str(self.owner.pk),
                'planned_date': '2026-08-11',
                'status': 'done',
                'is_done': 'on',
                'done_date': '2026-08-12',
                'urgency': 'ahead',
                'required_items': 'Oil\nFilter',
                'notes': 'Routine service complete',
            },
        )
        self.assertEqual(workjob_update_response.status_code, 302)

        report_update_response = self.client.post(
            reverse('shop-report-update', args=[created_car.pk, report.pk]),
            data={
                'mileage': '10001',
                'job_name': 'Oil service',
                'date_done': '2026-08-12',
                'documents': 'invoice.pdf',
                'photos': 'before.jpg',
                'external_links': 'https://example.com/invoice',
                'note': 'Completed and rechecked',
                'additional_information': 'Used synthetic oil and filter',
            },
        )
        self.assertEqual(report_update_response.status_code, 302)

        self.client.force_login(self.owner)
        car_delete_response = self.client.post(reverse('shop-car-delete', args=[created_car.pk]))
        self.assertEqual(car_delete_response.status_code, 302)
        self.assertFalse(Car.objects.filter(pk=created_car.pk).exists())

    def test_importer_edge_cases_and_unknown_model_branches(self):
        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer.resolve_model('unknown_model')

        result = importer.import_records(Car, [{'make': 'Nope'}], context=ImportContext(garage=self.garage))
        self.assertTrue(result.has_errors)
        self.assertIn("Field 'model' is required", result.errors[0].message)

        result = importer.import_records(Car, [42], context=ImportContext(garage=self.garage))
        self.assertTrue(result.has_errors)
        self.assertIn('Record is not an object', result.errors[0].message)

        self.client.force_login(self.owner)
        result = importer.import_records(
            WorkJob,
            [{
                'car': str(self.car.pk),
                'title': 'Tire rotation',
                'assigned_to': 'missing-user@example.com',
                'assigned_shop': 'missing-shop@example.com',
            }],
            context=ImportContext(garage=self.garage),
        )
        self.assertTrue(result.has_errors)

        result = importer.import_records(
            Report,
            [{
                'car': str(self.car.pk),
                'job_name': 'Inspection',
                'date_done': '2026-08-13',
                'assigned_to': 'not-a-mechanic@example.com',
                'assigned_shop': 'not-a-shop@example.com',
            }],
            context=ImportContext(garage=self.garage),
        )
        self.assertTrue(result.has_errors)

        self.assertTrue(importer._looks_like_uuid(str(self.car.pk)))
        self.assertFalse(importer._looks_like_uuid('not-a-uuid'))
        self.assertEqual(importer._parse_date_value('2026-08-15'), date(2026, 8, 15))

class ImporterCoverageTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='importer-owner',
            email='importer-owner@example.com',
            password='pass1234',
            is_mechanic=True,
        )
        self.garage = Garage.objects.create(name='Importer Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512348',
            year=2022,
        )

    def test_parse_csv_file_handles_missing_and_undecodable_files(self):
        importer = CSVImporter()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write('make,model,vin\nToyota,Yaris,JTDKB20U793512346\n')
            path = Path(f.name)
        try:
            records = importer.parse_csv_file(path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['make'], 'Toyota')
        finally:
            path.unlink()

        with self.assertRaises(ImportValidationError):
            importer.parse_csv_file('/nonexistent/path.csv')

        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as f:
            f.write(b'\xff\xfe')
            bad_path = Path(f.name)
        try:
            with self.assertRaises(ImportValidationError):
                importer.parse_csv_file(bad_path)
        finally:
            bad_path.unlink()

    def test_import_records_validates_batch_size_and_skips_empty_records(self):
        importer = CSVImporter()

        with self.assertRaises(ImportValidationError):
            importer.import_records(Car, [], batch_size=0)

        result = importer.import_records(
            Car,
            [{'make': 'Honda', 'model': 'Civic', 'vin': 'JTDKB20U793512300'}],
            context=ImportContext(garage=self.garage),
            dry_run=True,
        )
        self.assertEqual(result.created_count, 1)

    def test_prepare_record_raises_for_unsupported_model(self):
        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer._prepare_record(KnownShop, {}, ImportContext())

    def test_car_import_requires_garage(self):
        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer._prepare_record(Car, {'make': 'Honda', 'model': 'Civic', 'vin': 'JTDKB20U793512301'}, ImportContext())

    def test_resolve_car_with_context_car_and_uuid(self):
        importer = CSVImporter()
        resolved = importer._resolve_car(str(self.car.pk), ImportContext(car=self.car))
        self.assertEqual(resolved.pk, self.car.pk)

        empty_context = ImportContext(car=self.car)
        with self.assertRaises(ImportValidationError):
            importer._resolve_car('not-the-car-uuid', empty_context)

    def test_resolve_car_without_context_raises(self):
        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer._resolve_car(str(self.car.pk), ImportContext())

    def test_resolve_car_by_garage_only(self):
        importer = CSVImporter()
        resolved = importer._resolve_car(str(self.car.pk), ImportContext(garage=self.garage))
        self.assertEqual(resolved.pk, self.car.pk)

        with self.assertRaises(ImportValidationError):
            importer._resolve_car('', ImportContext(garage=self.garage))

    def test_resolve_car_by_vin_and_license_plate_and_usual_name(self):
        importer = CSVImporter()
        self.car.license_plate = 'ABC 123'
        self.car.usual_name = 'Daily Driver'
        self.car.save(update_fields=['license_plate', 'usual_name'])

        context = ImportContext(garage=self.garage)
        self.assertEqual(importer._resolve_car('ABC 123', context).pk, self.car.pk)
        self.assertEqual(importer._resolve_car('Daily Driver', context).pk, self.car.pk)

    def test_resolve_car_ambiguous_reference_raises(self):
        Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512349',
            usual_name='Same Name',
        )
        Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Accord',
            vin='1HGCM82633A123456',
            usual_name='Same Name',
        )

        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer._resolve_car('Same Name', ImportContext(garage=self.garage))

    def test_resolve_car_by_non_uuid_pk(self):
        importer = CSVImporter()
        resolved = importer._resolve_car(self.car.pk, ImportContext(garage=self.garage))
        self.assertEqual(resolved.pk, self.car.pk)

    def test_resolve_mechanic_and_shop_branches(self):
        importer = CSVImporter()
        self.assertIsNone(importer._resolve_mechanic(''))
        self.assertIsNone(importer._resolve_mechanic(None))
        self.assertIsNone(importer._resolve_mechanic('   '))

        with self.assertRaises(ImportValidationError):
            importer._resolve_mechanic('no-such-mechanic@example.com')

        with self.assertRaises(ImportValidationError):
            importer._resolve_mechanic(uuid.uuid4())

        shop = KnownShop.objects.create(name='Test Shop', email='shop@example.com')
        self.assertEqual(importer._resolve_shop('Test Shop').pk, shop.pk)
        self.assertEqual(importer._resolve_shop('shop@example.com').pk, shop.pk)
        self.assertEqual(importer._resolve_shop(shop.pk).pk, shop.pk)

        with self.assertRaises(ImportValidationError):
            importer._resolve_shop('Missing Shop')

        with self.assertRaises(ImportValidationError):
            importer._resolve_shop(uuid.uuid4())

    def test_prepare_workjob_record_with_car_context(self):
        importer = CSVImporter()
        data, warnings = importer._prepare_workjob_record(
            {'title': 'Brake job', 'assigned_to': self.user.email, 'unknown_field': 'x'},
            ImportContext(car=self.car),
        )
        self.assertEqual(data['car'].pk, self.car.pk)
        self.assertEqual(data['assigned_to'].pk, self.user.pk)
        self.assertIn("Ignored fields", warnings[0])

    def test_prepare_report_record_with_description_alias(self):
        importer = CSVImporter()
        data, warnings = importer._prepare_report_record(
            {'description': 'Annual service', 'date': '2026-08-20'},
            ImportContext(car=self.car),
        )
        self.assertEqual(data['job_name'], 'Annual service')
        self.assertEqual(data['date_done'], date(2026, 8, 20))
        self.assertEqual(data['additional_information'], '')

    def test_prepare_report_record_requires_job_name_and_date(self):
        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer._prepare_report_record({}, ImportContext(car=self.car))

        with self.assertRaises(ImportValidationError):
            importer._prepare_report_record({'job_name': 'Missing date'}, ImportContext(car=self.car))

    def test_coerce_bool_and_int_and_string_list_edge_cases(self):
        importer = CSVImporter()

        self.assertTrue(importer._coerce_bool(True, field_name='flag'))
        self.assertFalse(importer._coerce_bool(False, field_name='flag'))
        self.assertTrue(importer._coerce_bool('Y', field_name='flag'))
        self.assertFalse(importer._coerce_bool('N', field_name='flag'))

        with self.assertRaises(ImportValidationError):
            importer._coerce_optional_int(-5, field_name='mileage')
        with self.assertRaises(ImportValidationError):
            importer._coerce_optional_int('abc', field_name='mileage')

        self.assertEqual(
            importer._coerce_string_list(['a', '', 'b'], field_name='list'),
            ['a', 'b'],
        )
        with self.assertRaises(ImportValidationError):
            importer._coerce_string_list({'not': 'list'}, field_name='list')

    def test_parse_date_value_branches(self):
        importer = CSVImporter()
        self.assertIsNone(importer._parse_date_value(None))
        self.assertEqual(importer._parse_date_value(date(2026, 8, 20)), date(2026, 8, 20))

        with self.assertRaises(ImportValidationError):
            importer._parse_date_value(12345)

    def test_normalize_license_plate_and_vin(self):
        importer = CSVImporter()
        self.assertEqual(importer._normalize_license_plate('abc 123'), 'ABC 123')

        with self.assertRaises(ImportValidationError):
            importer._normalize_vin('1HGBH41JXMN10918!')

    def test_ignored_field_warnings(self):
        importer = CSVImporter()
        self.assertEqual(
            importer._ignored_field_warnings({'a': 1, 'b': 2}, {'a'}),
            ["Ignored fields: ['b']"],
        )
        self.assertEqual(importer._ignored_field_warnings({'a': 1}, {'a'}), [])


class AuthAndInputCoverageTests(TestCase):
    def test_sync_hanko_user_builds_unique_usernames_and_updates_existing_user(self):
        existing = ShopUser.objects.create_user(username='alice', email='alice@example.com', password='pass1234')
        existing.hanko_id = 'hanko-42'
        existing.display_name = ''
        existing.avatar_url = ''
        existing.auth_provider = 'legacy'
        existing.save(update_fields=['hanko_id', 'display_name', 'avatar_url', 'auth_provider'])

        user = sync_hanko_user(hanko_id='hanko-42', email='alice@example.com', username='Alice', avatar_url='https://img.example.com/alice.png')
        self.assertEqual(user.pk, existing.pk)
        self.assertEqual(user.display_name, 'Alice')
        self.assertEqual(user.avatar_url, 'https://img.example.com/alice.png')

        created = sync_hanko_user(email='new@example.com', username='alice', hanko_id='hanko-99')
        self.assertTrue(created.username.startswith('alice'))
        self.assertNotEqual(created.username, 'alice')

    def test_complete_hanko_login_sets_session_values(self):
        factory = RequestFactory()
        request = factory.get('/auth/hanko/callback/')
        SessionMiddleware(lambda _request: None).process_request(request)

        user = complete_hanko_login(
            request,
            {
                'id': 'hanko-session-1',
                'email': 'session-user@example.com',
                'name': 'Session User',
                'avatar_url': 'https://img.example.com/session.png',
                'provider': 'hanko',
            },
        )

        self.assertTrue(request.user.is_authenticated)
        self.assertEqual(user.email, 'session-user@example.com')
        self.assertEqual(request.session['hanko_user_id'], 'hanko-session-1')
        self.assertEqual(request.session['hanko_email'], 'session-user@example.com')
        self.assertEqual(request.session['hanko_provider'], 'hanko')

    def test_fetch_hanko_userinfo_validates_token_and_response(self):
        with override_settings(HANKO_API_URL='https://hanko.example.com'):
            with self.assertRaises(HankoAuthenticationError):
                fetch_hanko_userinfo('')
            with self.assertRaises(HankoAuthenticationError):
                fetch_hanko_userinfo(123)  # type: ignore[arg-type]

            with patch('shop.auth.requests.get', side_effect=requests.RequestException('network')):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

            with patch('shop.auth.requests.get', return_value=FakeHankoResponse('not-a-dict')):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

            with patch('shop.auth.requests.get', return_value=FakeHankoResponse({})):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

            with patch('shop.auth.requests.get', return_value=FakeHankoResponse({
                'id': '  hanko-id  ',
                'email': 'user@example.com',
                'emails': [{'address': 'ignored@example.com'}],
                'name': 'User',
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['id'], 'hanko-id')
                self.assertEqual(info['email'], 'user@example.com')

            with patch('shop.auth.requests.get', return_value=FakeHankoResponse({
                'id': 'fallback-id',
                'emails': [{'address': 'fallback@example.com'}],
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['email'], 'fallback@example.com')

            with patch('shop.auth.requests.get', return_value=FakeHankoResponse({
                'id': 'invalid-field-id',
                'email': 'valid@example.com',
                'name': None,
                'provider': 'hanko',
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['email'], 'valid@example.com')

            with patch('shop.auth.requests.get', return_value=FakeHankoResponse({
                'id': 'invalid-field-id',
                'email': ['not', 'a', 'string'],
            })):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

    @override_settings(HANKO_API_URL='')
    def test_fetch_hanko_userinfo_requires_api_url(self):
        with patch.dict('os.environ', {'HANKO_API_URL': ''}):
            with self.assertRaises(HankoAuthenticationError):
                fetch_hanko_userinfo('token')

    def test_build_username_handles_collision_and_special_characters(self):
        base = _build_username('valid user!')
        self.assertEqual(base, 'valid-user-')

        ShopUser.objects.create_user(username='collider', email='collider@example.com', password='pass1234')

        first = _build_username('collider', hanko_id='id-1')
        self.assertEqual(first, 'collider1')

        second = _build_username('collider', hanko_id='id-2')
        self.assertEqual(second, 'collider1')

        empty = _build_username('', hanko_id='id-3')
        self.assertEqual(empty, 'hanko-id-3')

    def test_build_username_very_long_base_is_truncated(self):
        long_name = 'a' * 200
        result = _build_username(long_name)
        self.assertEqual(len(result), 150)
        self.assertTrue(result.startswith('a' * 140))

    def test_sync_hanko_user_falls_back_to_email_lookup_and_creates_user(self):
        email_user = ShopUser.objects.create_user(
            username='email-user',
            email='lookup@example.com',
            password='pass1234',
        )
        linked = sync_hanko_user(hanko_id='new-hanko-id', email='LOOKUP@EXAMPLE.COM', username='Linked User')
        self.assertEqual(linked.pk, email_user.pk)
        self.assertEqual(linked.hanko_id, 'new-hanko-id')
        self.assertEqual(linked.display_name, 'Linked User')

        created_no_email = sync_hanko_user()
        self.assertTrue(created_no_email.username.startswith('hanko-user'))
        self.assertEqual(created_no_email.email, '')

    def test_sync_hanko_user_only_backfills_empty_fields_for_existing_hanko_user(self):
        user = ShopUser.objects.create_user(
            username='backfill',
            email='backfill@example.com',
            password='pass1234',
        )
        user.hanko_id = 'backfill-hanko-id'
        user.email = ''
        user.display_name = ''
        user.avatar_url = ''
        user.auth_provider = ''
        user.save(update_fields=['hanko_id', 'email', 'display_name', 'avatar_url', 'auth_provider'])

        updated = sync_hanko_user(
            hanko_id='backfill-hanko-id',
            email='new@example.com',
            username='New Name',
            avatar_url='https://example.com/new.png',
            provider='hanko',
        )
        self.assertEqual(updated.email, 'new@example.com')
        self.assertEqual(updated.display_name, 'New Name')
        self.assertEqual(updated.avatar_url, 'https://example.com/new.png')
        self.assertEqual(updated.auth_provider, 'hanko')

    def test_sync_hanko_user_preserves_populated_fields_for_existing_users(self):
        user = ShopUser.objects.create_user(
            username='preserve',
            email='preserve@example.com',
            password='pass1234',
        )
        user.hanko_id = 'preserve-hanko-id'
        user.display_name = 'Existing Name'
        user.avatar_url = 'https://example.com/existing.png'
        user.auth_provider = 'hanko'
        user.save(update_fields=['hanko_id', 'display_name', 'avatar_url', 'auth_provider'])

        updated_by_hanko_id = sync_hanko_user(
            hanko_id='preserve-hanko-id',
            email='new@example.com',
            username='Ignored Name',
            avatar_url='https://example.com/ignored.png',
            provider='legacy',
        )
        self.assertEqual(updated_by_hanko_id.display_name, 'Existing Name')
        self.assertEqual(updated_by_hanko_id.avatar_url, 'https://example.com/existing.png')
        self.assertEqual(updated_by_hanko_id.auth_provider, 'legacy')

        updated_by_hanko_id_no_provider = sync_hanko_user(
            hanko_id='preserve-hanko-id',
            email='new2@example.com',
            username='Ignored Name 2',
            avatar_url='https://example.com/ignored2.png',
        )
        self.assertEqual(updated_by_hanko_id_no_provider.display_name, 'Existing Name')
        self.assertEqual(updated_by_hanko_id_no_provider.avatar_url, 'https://example.com/existing.png')

        email_user_no_avatar = ShopUser.objects.create_user(
            username='preserve-email-empty-avatar',
            email='preserve-email-empty-avatar@example.com',
            password='pass1234',
        )
        email_user_no_avatar.display_name = 'Email Existing Name'
        email_user_no_avatar.save(update_fields=['display_name'])

        updated_email_no_avatar = sync_hanko_user(
            hanko_id='new-hanko-empty-avatar',
            email='preserve-email-empty-avatar@example.com',
            username='Ignored Email Name',
            avatar_url='https://example.com/new-avatar.png',
        )
        self.assertEqual(updated_email_no_avatar.display_name, 'Ignored Email Name')
        self.assertEqual(updated_email_no_avatar.avatar_url, 'https://example.com/new-avatar.png')

        other_email = ShopUser.objects.create_user(
            username='preserve-email',
            email='emailpreserve@example.com',
            password='pass1234',
        )
        other_email.display_name = 'Email Existing'
        other_email.avatar_url = 'https://example.com/email-existing.png'
        other_email.auth_provider = 'hanko'
        other_email.save(update_fields=['display_name', 'avatar_url', 'auth_provider'])

        updated_by_email = sync_hanko_user(
            hanko_id='new-hanko-for-email',
            email='emailpreserve@example.com',
            username='Ignored Email Name',
            avatar_url='https://example.com/ignored-email.png',
            provider='legacy',
        )
        self.assertEqual(updated_by_email.hanko_id, 'new-hanko-for-email')
        self.assertEqual(updated_by_email.display_name, 'Ignored Email Name')
        self.assertEqual(updated_by_email.avatar_url, 'https://example.com/ignored-email.png')
        self.assertEqual(updated_by_email.auth_provider, 'legacy')

    def test_sync_hanko_user_with_empty_provider_does_not_overwrite_existing_provider(self):
        user = ShopUser.objects.create_user(
            username='provider-test',
            email='provider@example.com',
            password='pass1234',
        )
        user.hanko_id = 'provider-hanko-id'
        user.auth_provider = 'hanko'
        user.save(update_fields=['hanko_id', 'auth_provider'])

        updated_by_hanko_id = sync_hanko_user(
            hanko_id='provider-hanko-id',
            email='provider@example.com',
            username='Provider User',
            provider='',
        )
        self.assertEqual(updated_by_hanko_id.auth_provider, 'hanko')

        email_user = ShopUser.objects.create_user(
            username='provider-email-test',
            email='provider-email@example.com',
            password='pass1234',
        )
        email_user.auth_provider = 'hanko'
        email_user.save(update_fields=['auth_provider'])

        updated_by_email = sync_hanko_user(
            hanko_id='new-provider-hanko-id',
            email='provider-email@example.com',
            username='Provider Email User',
            provider='',
        )
        self.assertEqual(updated_by_email.auth_provider, 'hanko')

    def test_car_form_validators_cover_invalid_ranges_and_duplicates(self):
        self.user = ShopUser.objects.create_user(username='validator', email='validator@example.com', password='pass1234')
        self.garage = Garage.objects.create(name='Validator Garage', created_by=self.user)
        GarageMembership.objects.create(garage=self.garage, user=self.user, role=GarageMembership.ROLE_OWNER)

        Car.objects.create(garage=self.garage, make='Toyota', model='Yaris', vin='JTDKB20U793512346')

        invalid_year = CarCreateForm(data={
            'garage': self.garage.pk,
            'make': 'Honda',
            'model': 'Civic',
            'year': '1800',
            'vin': 'JTDKB20U793512346',
            'license_plate': 'ABC 123',
        }, user=self.user)
        self.assertFalse(invalid_year.is_valid())
        self.assertIn('year', invalid_year.errors)

        duplicate_vin = CarCreateForm(data={
            'garage': self.garage.pk,
            'make': 'Honda',
            'model': 'Civic',
            'year': '2024',
            'vin': 'JTDKB20U793512346',
            'license_plate': 'DEF456',
        }, user=self.user)
        self.assertFalse(duplicate_vin.is_valid())
        self.assertIn('vin', duplicate_vin.errors)

        invalid_chars = CarCreateForm(data={
            'garage': self.garage.pk,
            'make': 'Honda',
            'model': 'Civic',
            'year': '2024',
            'vin': 'JTDKB20U7935I2346',
            'license_plate': 'ABC123',
        }, user=self.user)
        self.assertFalse(invalid_chars.is_valid())
        self.assertIn('vin', invalid_chars.errors)

        invalid_plate = CarCreateForm(data={
            'garage': self.garage.pk,
            'make': 'Honda',
            'model': 'Civic',
            'year': '2024',
            'vin': 'JTDKB20U793512350',
            'license_plate': 'BAD@PLATE',
        }, user=self.user)
        self.assertFalse(invalid_plate.is_valid())
        self.assertIn('license_plate', invalid_plate.errors)

    def test_car_orm_validation_rejects_invalid_vin_and_license_plate(self):
        user = ShopUser.objects.create_user(
            username='orm-car-validator',
            email='orm-car-validator@example.com',
            password='pass1234',
        )
        garage = Garage.objects.create(name='ORM Car Garage', created_by=user)
        GarageMembership.objects.create(garage=garage, user=user, role=GarageMembership.ROLE_OWNER)

        with self.assertRaises(ValidationError):
            Car.objects.create(
                garage=garage,
                make='Honda',
                model='Civic',
                vin='SHORT',
            )

        with self.assertRaises(ValidationError):
            Car.objects.create(
                garage=garage,
                make='Honda',
                model='Civic',
                vin='JTDKB20U793512351',
                license_plate='BAD@PLATE',
            )

    def test_workjob_and_report_form_line_lists_and_assignment_guards(self):
        user = ShopUser.objects.create_user(username='mechanic-form-user', email='mechanic@shop.test', password='pass1234', is_mechanic=True)
        shop = KnownShop.objects.create(name='Northside Auto', email='shop@example.com')

        workjob_form = WorkJobForm(data={
            'title': 'Brake service',
            'maintenance_type': 'inspection',
            'assigned_to': str(user.pk),
            'assigned_shop': str(shop.pk),
            'planned_date': '2026-08-09',
            'status': 'pending',
            'urgency': 'soon',
            'required_items': 'Pads\nFluid',
            'notes': 'Inspect',
        })
        self.assertFalse(workjob_form.is_valid())
        self.assertIn('__all__', workjob_form.errors)

        cleaned = WorkJobForm(data={
            'title': 'Brake service',
            'maintenance_type': 'inspection',
            'assigned_to': str(user.pk),
            'planned_date': '2026-08-09',
            'status': 'pending',
            'urgency': 'soon',
            'required_items': 'Pads\nFluid',
            'notes': 'Inspect',
        })
        self.assertTrue(cleaned.is_valid())
        self.assertEqual(cleaned.cleaned_data['required_items'], ['Pads', 'Fluid'])

        report_form = ReportForm(data={
            'mileage': '125000',
            'job_name': 'Brake service',
            'date_done': '2026-08-09',
            'documents': 'invoice.pdf\nchecklist.pdf',
            'photos': 'before.jpg\nafter.jpg',
            'external_links': 'https://example.com/one\nhttps://example.com/two',
            'note': 'Performed service.',
            'additional_information': 'Used OEM parts',
        })
        self.assertTrue(report_form.is_valid())
        self.assertEqual(report_form.cleaned_data['documents'], ['invoice.pdf', 'checklist.pdf'])
        self.assertEqual(report_form.cleaned_data['photos'], ['before.jpg', 'after.jpg'])
        self.assertEqual(report_form.cleaned_data['external_links'], ['https://example.com/one', 'https://example.com/two'])

    def test_known_shop_proof_form_rejects_invalid_files(self):
        form = KnownShopProofForm(data={'title': 'Proof', 'content': 'Valid proof'}, files={'file': SimpleUploadedFile('bad.txt', b'nope', content_type='text/plain')})
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)

        spoofed_pdf = SimpleUploadedFile('spoofed.pdf', b'not a pdf', content_type='application/pdf')
        spoofed_form = KnownShopProofForm(data={'title': 'Proof', 'content': 'Invalid proof'}, files={'file': spoofed_pdf})
        self.assertFalse(spoofed_form.is_valid())
        self.assertIn('file', spoofed_form.errors)

        pdf = SimpleUploadedFile('valid.pdf', b'%PDF-1.4', content_type='application/pdf')
        valid_form = KnownShopProofForm(data={'title': 'Proof', 'content': 'Valid proof'}, files={'file': pdf})
        self.assertTrue(valid_form.is_valid())

    def test_orm_assignment_guards_reject_non_mechanics(self):
        non_mechanic = ShopUser.objects.create_user(
            username='orm-non-mechanic',
            email='orm-non-mechanic@example.com',
            password='pass1234',
        )
        garage = Garage.objects.create(name='ORM Guard Garage', created_by=non_mechanic)
        GarageMembership.objects.create(
            garage=garage,
            user=non_mechanic,
            role=GarageMembership.ROLE_OWNER,
        )
        car = Car.objects.create(
            garage=garage,
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512346',
        )

        with self.assertRaises(ValidationError):
            WorkJob.objects.create(car=car, title='Invalid assignment', assigned_to=non_mechanic)
        with self.assertRaises(ValidationError):
            Report.objects.create(
                car=car,
                job_name='Invalid assignment',
                date_done='2026-08-09',
                assigned_to=non_mechanic,
            )

    def test_importer_list_and_type_validations(self):
        importer = CSVImporter()

        self.assertEqual(importer.parse_csv_content(''), [])
        self.assertEqual(importer.parse_csv_content('   \n '), [])
        self.assertEqual(importer._detect_dialect('make,model,vin\n').delimiter, ',')
        self.assertEqual(importer._detect_dialect('justaword\n'), csv.excel)
        self.assertEqual(importer._coerce_bool('yes', field_name='flag'), True)
        self.assertEqual(importer._coerce_bool('0', field_name='flag'), False)
        self.assertEqual(importer._coerce_bool('', field_name='flag'), False)
        with self.assertRaises(ImportValidationError):
            importer._coerce_bool('maybe', field_name='flag')

        self.assertEqual(importer._parse_date_value('2026-08'), date(2026, 8, 1))
        self.assertEqual(importer._parse_date_value('2026'), date(2026, 1, 1))
        with self.assertRaises(ImportValidationError):
            importer._parse_date_value('not-a-date')

        self.assertEqual(importer._coerce_string_list(['', 'fee', None], field_name='list'), ['fee'])
        self.assertEqual(importer._coerce_string_list('one\ntwo', field_name='list'), ['one', 'two'])
        with self.assertRaises(ImportValidationError):
            importer._coerce_string_list(123, field_name='list')

        with self.assertRaises(ImportValidationError):
            importer._normalize_vin('1HGBH41JXMN10918I')
        with self.assertRaises(ImportValidationError):
            importer._normalize_vin('SHORT')
        self.assertEqual(importer._normalize_vin(' 1hgbh41jxmn109186 '), '1HGBH41JXMN109186')

        with self.assertRaises(ImportValidationError):
            importer._normalize_license_plate('A' * 21)
        with self.assertRaises(ImportValidationError):
            importer._normalize_license_plate('BAD_PLATE')
        self.assertEqual(importer._normalize_license_plate('abc 123'), 'ABC 123')
        self.assertEqual(importer._normalize_license_plate(''), '')

        with self.assertRaises(ImportValidationError):
            importer._coerce_optional_int('not-an-int', field_name='mileage')
        self.assertEqual(importer._coerce_optional_int('', field_name='mileage'), None)
        self.assertEqual(importer._coerce_optional_int('123', field_name='mileage'), 123)

        self.assertEqual(importer._format_validation_error(ValidationError({'make': ['Bad value.']})), 'make: Bad value.')
        self.assertEqual(importer._format_validation_error(ValidationError('Plain error.')), 'Plain error.')

    def test_mailgun_backend_success_and_error_paths(self):
        settings_override = override_settings(MAILGUN_API_KEY='secret', MAILGUN_SANDBOX_DOMAIN='mg.example.com', MAILGUN_BASE_DOMAIN='https://api.mailgun.net')
        with settings_override:
            with patch('shop.mailgun_backend.requests.post') as mock_post:
                mock_post.return_value.raise_for_status.return_value = None
                backend = MailgunEmailBackend(fail_silently=False)
                message = EmailMessage(subject='Test', body='Body', to=['one@example.com'], from_email='from@example.com')
                self.assertEqual(backend.send_messages([message]), 1)

            with patch('shop.mailgun_backend.requests.post', side_effect=requests.RequestException('boom')):
                backend = MailgunEmailBackend(fail_silently=False)
                message = EmailMessage(subject='Test', body='Body', to=['one@example.com'], from_email='from@example.com')
                with self.assertRaises(requests.RequestException):
                    backend.send_messages([message])

        with override_settings(MAILGUN_API_KEY='', MAILGUN_SANDBOX_DOMAIN=''):
            backend = MailgunEmailBackend(fail_silently=False)
            with self.assertRaises(ValueError):
                backend.send_messages([EmailMessage(subject='Test', body='Body', to=['one@example.com'])])

    def test_convert_user_to_mechanic_command_handles_grant_and_revoke_branches(self):
        user = ShopUser.objects.create_user(username='mechanic-cmd', email='mechanic-cmd@example.com', password='pass1234')

        call_command('convert_user_to_mechanic', user.email)
        user.refresh_from_db()
        self.assertTrue(user.is_mechanic)
        self.assertIsNotNone(user.mechanic_promoted_at)

        call_command('convert_user_to_mechanic', user.email, '--revoke')
        user.refresh_from_db()
        self.assertFalse(user.is_mechanic)
        self.assertIsNone(user.mechanic_promoted_at)

        with self.assertRaises(CommandError):
            call_command('convert_user_to_mechanic', '')

    def test_hanko_auth_middleware_and_decorator_cover_redirect_and_rehydrate_paths(self):
        factory = RequestFactory()

        with override_settings(HANKO_API_URL='https://hanko.example.com'):
            request = factory.get('/secure/route/')
            SessionMiddleware(lambda _request: None).process_request(request)
            request.session['hanko_session_token'] = 'session-token-ABC'
            request.user = AnonymousUser()

            with patch('shop.auth.requests.get') as mock_get:
                mock_get.return_value.raise_for_status.return_value = None
                mock_get.return_value.json.return_value = {
                    'id': 'recovered-hanko-id',
                    'email': 'recovered@example.com',
                    'name': 'Recovered User',
                }
                response = HankoAuthenticationMiddleware(lambda _request: HttpResponse()).process_request(request)
                self.assertIsNone(response)
                self.assertTrue(request.user.is_authenticated)

        public_request = factory.get('/login/')
        SessionMiddleware(lambda _request: None).process_request(public_request)
        public_request.user = AnonymousUser()
        self.assertIsNone(HankoAuthenticationMiddleware(lambda _request: HttpResponse()).process_request(public_request))

        no_session = factory.get('/private/')
        SessionMiddleware(lambda _request: None).process_request(no_session)
        no_session.user = AnonymousUser()
        response = HankoAuthenticationMiddleware(lambda _request: HttpResponse()).process_request(no_session)
        self.assertEqual(response.status_code, 302)

        decorated = hanko_login_required(lambda _request: HttpResponse('ok'))
        decorator_request = factory.get('/private/')
        SessionMiddleware(lambda _request: None).process_request(decorator_request)
        decorator_request.user = AnonymousUser()
        result = decorated(decorator_request)
        self.assertEqual(result.status_code, 302)

        authenticated = factory.get('/private/')
        SessionMiddleware(lambda _request: None).process_request(authenticated)
        authenticated.user = ShopUser.objects.create_user(username='decorated-user', email='decorated@example.com', password='pass1234')
        self.assertEqual(decorated(authenticated).status_code, 200)


class ViewCoverageTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='view-owner',
            email='view-owner@example.com',
            password='pass1234',
            is_mechanic=True,
        )
        self.member = ShopUser.objects.create_user(
            username='view-member',
            email='view-member@example.com',
            password='pass1234',
        )
        self.stranger = ShopUser.objects.create_user(
            username='view-stranger',
            email='view-stranger@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='View Garage', created_by=self.owner)
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
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512347',
            year=2022,
        )

    def test_garage_create_renders_form_and_handles_invalid_post(self):
        self.client.force_login(self.owner)

        get_response = self.client.get(reverse('shop-garage-create'))
        self.assertEqual(get_response.status_code, 200)

        post_response = self.client.post(reverse('shop-garage-create'), data={'name': ''})
        self.assertEqual(post_response.status_code, 200)
        self.assertFalse(Garage.objects.filter(name='').exists())

    def test_garage_detail_and_index_render_for_member(self):
        self.client.force_login(self.owner)

        detail_response = self.client.get(reverse('shop-garage-detail', args=[self.garage.pk]))
        self.assertEqual(detail_response.status_code, 200)

        index_response = self.client.get(reverse('shop-index'))
        self.assertEqual(index_response.status_code, 200)

    def test_garage_share_branches(self):
        self.client.force_login(self.owner)

        # Already a member
        member_response = self.client.post(
            reverse('shop-garage-share', args=[self.garage.pk]),
            data={
                'invited_email': self.member.email,
                'message': 'Already member',
                'expires_in_days': 14,
            },
        )
        self.assertEqual(member_response.status_code, 302)

        # Invalid form
        invalid_response = self.client.post(
            reverse('shop-garage-share', args=[self.garage.pk]),
            data={
                'invited_email': 'not-an-email',
                'message': 'Bad',
                'expires_in_days': 14,
            },
        )
        self.assertEqual(invalid_response.status_code, 200)

        # Successful invitation renders GET form
        with patch('shop.models.garage.send_mail', side_effect=Exception('SMTP down')):
            send_failure_response = self.client.post(
                reverse('shop-garage-share', args=[self.garage.pk]),
                data={
                    'invited_email': 'new-invite@example.com',
                    'message': 'Join us',
                    'expires_in_days': 14,
                },
            )
        self.assertEqual(send_failure_response.status_code, 302)

    def test_garage_import_branches(self):
        self.client.force_login(self.owner)

        csv_content = b'make,model,vin\nFord,F-150,1FTFW1ET5DFC12345\n'
        valid_response = self.client.post(
            reverse('shop-garage-import', args=[self.garage.pk]),
            data={
                'import_file': SimpleUploadedFile('cars.csv', csv_content, content_type='text/csv'),
                'dry_run': 'on',
            },
        )
        self.assertEqual(valid_response.status_code, 200)

        invalid_response = self.client.post(
            reverse('shop-garage-import', args=[self.garage.pk]),
            data={
                'import_file': SimpleUploadedFile('bad.txt', b'garbage', content_type='text/plain'),
                'dry_run': '',
            },
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertIn('import_file', invalid_response.context['form'].errors)

        get_response = self.client.get(reverse('shop-garage-import', args=[self.garage.pk]))
        self.assertEqual(get_response.status_code, 200)

        self.client.force_login(self.member)
        forbidden_response = self.client.get(reverse('shop-garage-import', args=[self.garage.pk]))
        self.assertEqual(forbidden_response.status_code, 302)

    def test_garage_export_forbidden_to_non_managers(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse('shop-garage-export', args=[self.garage.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-garage-detail', args=[self.garage.pk]))

    def test_known_shop_create_and_detail_and_proof_branches(self):
        self.client.force_login(self.owner)

        create_response = self.client.post(
            reverse('shop-known-shop-create'),
            data={
                'name': 'Branch Shop',
                'email': 'branch@example.com',
                'phone': '555-0200',
                'address': '20 Side Street',
                'notes': 'Note',
            },
        )
        self.assertEqual(create_response.status_code, 302)
        shop = KnownShop.objects.get(name='Branch Shop')

        detail_response = self.client.get(reverse('shop-known-shop-detail', args=[shop.pk]))
        self.assertEqual(detail_response.status_code, 200)

        invalid_proof_response = self.client.post(
            reverse('shop-known-shop-proof-create', args=[shop.pk]),
            data={
                'title': 'Bad proof',
                'content': 'No file',
                'file': SimpleUploadedFile('not-pdf.txt', b'not a pdf', content_type='text/plain'),
            },
        )
        self.assertEqual(invalid_proof_response.status_code, 200)
        self.assertIn('file', invalid_proof_response.context['form'].errors)

        # Non-manager cannot add proof
        self.client.force_login(self.stranger)
        forbidden_proof_response = self.client.get(
            reverse('shop-known-shop-proof-create', args=[shop.pk]),
        )
        self.assertEqual(forbidden_proof_response.status_code, 404)

    def test_known_shop_proof_file_missing_file_raises_404(self):
        self.client.force_login(self.owner)
        shop = KnownShop.objects.create(name='No Proof Shop', created_by=self.owner)
        proof = KnownShopProof.objects.create(shop=shop, title='No file')

        response = self.client.get(reverse('shop-known-shop-proof-file', args=[shop.pk, proof.pk]))
        self.assertEqual(response.status_code, 404)

    def test_car_import_branches(self):
        self.client.force_login(self.owner)

        csv_content = b'title,maintenance_type,planned_date,status,urgency\nTire rotation,service,2026-08-20,pending,soon\n'
        valid_response = self.client.post(
            reverse('shop-car-import', args=[self.car.pk]),
            data={
                'import_file': SimpleUploadedFile('workjobs.csv', csv_content, content_type='text/csv'),
                'import_type': 'workjob',
                'dry_run': '',
            },
        )
        self.assertEqual(valid_response.status_code, 302)

        invalid_response = self.client.post(
            reverse('shop-car-import', args=[self.car.pk]),
            data={
                'import_file': SimpleUploadedFile('bad.txt', b'garbage', content_type='text/plain'),
                'import_type': 'workjob',
                'dry_run': '',
            },
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertIn('import_file', invalid_response.context['form'].errors)

        get_response = self.client.get(
            reverse('shop-car-import', args=[self.car.pk]),
            {'type': 'report'},
        )
        self.assertEqual(get_response.status_code, 200)

        invalid_type_response = self.client.get(
            reverse('shop-car-import', args=[self.car.pk]),
            {'type': 'invalid'},
        )
        self.assertEqual(invalid_type_response.status_code, 200)

    def test_part_create_and_update_branches(self):
        self.client.force_login(self.owner)

        create_response = self.client.post(
            reverse('shop-part-create', args=[self.car.pk]),
                data={'name': 'Brake pads', 'status': CarPart.STATUS_NEW, 'notes': 'Good'},
        )
        self.assertEqual(create_response.status_code, 302)
        part = CarPart.objects.get(car=self.car, name='Brake pads')

        get_update_response = self.client.get(reverse('shop-part-update', args=[self.car.pk, part.pk]))
        self.assertEqual(get_update_response.status_code, 200)

        update_response = self.client.post(
            reverse('shop-part-update', args=[self.car.pk, part.pk]),
            data={'name': 'Brake pads', 'status': CarPart.STATUS_ORDERED, 'notes': 'Ordered'},
        )
        self.assertEqual(update_response.status_code, 302)
        part.refresh_from_db()
        self.assertEqual(part.status, CarPart.STATUS_ORDERED)

    def test_workjob_create_and_update_branches(self):
        self.client.force_login(self.owner)

        create_response = self.client.post(
            reverse('shop-workjob-create', args=[self.car.pk]),
            data={
                'title': 'Oil change',
                'maintenance_type': 'service',
                'planned_date': '2026-08-20',
                'status': 'pending',
                'urgency': 'soon',
            },
        )
        self.assertEqual(create_response.status_code, 302)
        work_job = WorkJob.objects.get(car=self.car, title='Oil change')

        get_update_response = self.client.get(reverse('shop-workjob-update', args=[self.car.pk, work_job.pk]))
        self.assertEqual(get_update_response.status_code, 200)

        update_response = self.client.post(
            reverse('shop-workjob-update', args=[self.car.pk, work_job.pk]),
            data={
                'title': 'Oil change updated',
                'maintenance_type': 'service',
                'planned_date': '2026-08-21',
                'status': 'done',
                'urgency': 'soon',
            },
        )
        self.assertEqual(update_response.status_code, 302)

    def test_report_create_and_update_branches(self):
        self.client.force_login(self.owner)

        create_response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data={
                'mileage': '50000',
                'job_name': 'Inspection',
                'date_done': '2026-08-20',
                'external_links': 'https://example.com/invoice',
            },
        )
        self.assertEqual(create_response.status_code, 302)
        report = Report.objects.get(car=self.car, job_name='Inspection')
        self.assertTrue(report.attachments.exists())

        get_update_response = self.client.get(reverse('shop-report-update', args=[self.car.pk, report.pk]))
        self.assertEqual(get_update_response.status_code, 200)

        update_response = self.client.post(
            reverse('shop-report-update', args=[self.car.pk, report.pk]),
            data={
                'mileage': '50001',
                'job_name': 'Inspection updated',
                'date_done': '2026-08-21',
            },
        )
        self.assertEqual(update_response.status_code, 302)

    def test_report_attachment_file_branches(self):
        self.client.force_login(self.owner)
        report = Report.objects.create(car=self.car, job_name='Attachment test', date_done='2026-08-20')
        attachment = ReportAttachment.objects.create(
            report=report,
            source_type=ReportAttachment.SOURCE_UPLOAD,
            file=SimpleUploadedFile('report.pdf', b'%PDF-1.4 report', content_type='application/pdf'),
        )

        try:
            response = self.client.get(
                reverse('shop-report-attachment-file', args=[self.car.pk, report.pk, attachment.pk]),
            )
            self.assertEqual(response.status_code, 200)
        finally:
            attachment.file.delete(save=False)

        empty_attachment = ReportAttachment.objects.create(
            report=report,
            source_type=ReportAttachment.SOURCE_UPLOAD,
        )
        response = self.client.get(
            reverse('shop-report-attachment-file', args=[self.car.pk, report.pk, empty_attachment.pk]),
        )
        self.assertEqual(response.status_code, 404)

    def test_hanko_callback_branches(self):
        response = self.client.get(reverse('shop-hanko-callback'))
        self.assertEqual(response.status_code, 405)

        empty_response = self.client.post(
            reverse('shop-hanko-callback'),
            data='',
            content_type='application/json',
        )
        self.assertEqual(empty_response.status_code, 400)

        invalid_json_response = self.client.post(
            reverse('shop-hanko-callback'),
            data='not-json',
            content_type='application/json',
        )
        self.assertEqual(invalid_json_response.status_code, 400)

    def test_login_view_redirects_authenticated_users(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shop-login'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-index'))

    def test_theme_view_rejects_unknown_theme(self):
        response = self.client.get(reverse('shop-theme', args=['pink']), {'next': reverse('shop-login')})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.cookies['theme'].value, 'light')

    def test_logout_view_ignores_get(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shop-logout'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_car_create_and_update_invalid_forms(self):
        self.client.force_login(self.owner)

        invalid_create = self.client.post(
            reverse('shop-car-create'),
            data={'make': '', 'model': '', 'garage': str(self.garage.pk)},
        )
        self.assertEqual(invalid_create.status_code, 200)

        invalid_update = self.client.post(
            reverse('shop-car-update', args=[self.car.pk]),
            data={'make': '', 'model': ''},
        )
        self.assertEqual(invalid_update.status_code, 200)
