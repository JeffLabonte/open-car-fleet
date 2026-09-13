import csv
import json
from datetime import date
from typing import cast
from unittest.mock import patch
import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.mail import EmailMessage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import IntegrityError
from django.db import transaction
from django.http import HttpRequest
from django.http import HttpResponse
from django.test import RequestFactory
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from shop import views
from shop.auth import HankoAuthenticationError
from shop.auth import _build_username
from shop.auth import complete_hanko_login
from shop.auth import fetch_hanko_userinfo
from shop.auth import sync_hanko_user
from shop.forms import CarCreateForm
from shop.forms import KnownShopProofForm
from shop.forms import ReportForm
from shop.forms import WorkJobForm
from shop.importers import CSVImporter
from shop.importers import ImportValidationError
from shop.mailgun_backend import MailgunEmailBackend
from shop.middleware import HankoAuthenticationMiddleware
from shop.middleware import hanko_login_required
from shop.models.car import Car
from shop.models.garage import Garage
from shop.models.garage import GarageMembership
from shop.models.garage import KnownShop
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.models.user import ShopUser
from shop.tests.helpers import FakeHankoResponse
from shop.tests.helpers import PDF_SIGNATURE


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

        with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
            'is_valid': True,
            'claims': {
                'sub': 'hanko-user-123',
                'email': 'driver@example.com',
                'username': 'Test Driver',
            },
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

            def json(self) -> dict[str, object]:
                return {
                    'is_valid': True,
                    'claims': {
                        'sub': 'hanko-user-123',
                        'email': 'driver@example.com',
                        'username': 'Test Driver',
                    },
                }

        with patch('shop.auth.requests.post', return_value=FakeResponse()):
            self.client.get(reverse('shop-index'))

        factory = RequestFactory()
        request = factory.get(reverse('shop-index'))

        def next_response(_request: HttpRequest) -> HttpResponse:
            return HttpResponse()

        SessionMiddleware(next_response).process_request(request)
        request.session['hanko_session_token'] = 'session-token-123'
        request.session.save()
        AuthenticationMiddleware(next_response).process_request(request)

        with patch('shop.auth.requests.post', return_value=FakeResponse()):
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
        self.assertContains(response, 'data-testid="theme-toggle"')
        self.assertContains(response, '<span>Light</span>')
        self.assertContains(response, '<span>Dark</span>')

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

            def json(self) -> dict[str, object]:
                return {
                    'is_valid': True,
                    'claims': {
                        'sub': 'hanko-user-123',
                        'email': 'driver@example.com',
                        'username': 'Test Driver',
                    },
                }

        with patch('shop.auth.requests.post', return_value=FakeResponse()):
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

        with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
            'is_valid': True,
            'claims': {
                'sub': 'verified-hanko-id',
                'email': 'verified@example.com',
                'username': 'Verified User',
            },
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
            'https://hanko.example.com/sessions/validate',
            json={'session_token': 'verified-session-token'},
            timeout=5,
        )

    def test_callback_fails_closed_when_hanko_rejects_the_token(self):
        with patch('shop.auth.requests.post', side_effect=requests.HTTPError('invalid token')):
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

            with patch('shop.auth.requests.post', side_effect=requests.RequestException('network')):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse('not-a-dict')):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({})):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
                'is_valid': True,
                'claims': {
                    'sub': '  hanko-id  ',
                    'email': {'address': 'user@example.com'},
                    'username': 'User',
                },
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['id'], 'hanko-id')
                self.assertEqual(info['email'], 'user@example.com')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
                'is_valid': True,
                'claims': {
                    'sub': 'fallback-id',
                    'email': 'fallback@example.com',
                },
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['email'], 'fallback@example.com')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
                'is_valid': True,
                'claims': {
                    'sub': 'invalid-field-id',
                    'email': 'valid@example.com',
                    'username': None,
                },
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['email'], 'valid@example.com')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
                'is_valid': True,
                'claims': {
                    'sub': 'invalid-field-id',
                    'email': ['not', 'a', 'string'],
                },
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['email'], '')

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
            'external_links': 'https://example.com/one\nhttps://example.com/two',
            'note': 'Performed service.',
            'additional_information': 'Used OEM parts',
        })
        self.assertTrue(report_form.is_valid())
        self.assertEqual(report_form.cleaned_data['external_links'], ['https://example.com/one', 'https://example.com/two'])

    def test_known_shop_proof_form_rejects_invalid_files(self):
        form = KnownShopProofForm(
            data={'title': 'Proof', 'content': 'Valid proof'},
            files={'attachments': SimpleUploadedFile('bad.txt', b'nope', content_type='text/plain')},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('attachments', form.errors)

        spoofed_pdf = SimpleUploadedFile('spoofed.pdf', b'not a pdf', content_type='application/pdf')
        spoofed_form = KnownShopProofForm(
            data={'title': 'Proof', 'content': 'Invalid proof'},
            files={'attachments': spoofed_pdf},
        )
        self.assertFalse(spoofed_form.is_valid())
        self.assertIn('attachments', spoofed_form.errors)

        pdf = SimpleUploadedFile('valid.pdf', PDF_SIGNATURE, content_type='application/pdf')
        valid_form = KnownShopProofForm(
            data={'title': 'Proof', 'content': 'Valid proof'},
            files={'attachments': pdf},
        )
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

            with patch('shop.auth.requests.post') as mock_post:
                mock_post.return_value.raise_for_status.return_value = None
                mock_post.return_value.json.return_value = {
                    'is_valid': True,
                    'claims': {
                        'sub': 'recovered-hanko-id',
                        'email': 'recovered@example.com',
                        'username': 'Recovered User',
                    },
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
