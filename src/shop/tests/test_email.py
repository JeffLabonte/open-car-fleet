import json
from datetime import timedelta
from unittest.mock import patch

import requests

from django.core import mail as django_mail
from django.core.mail import EmailMessage, get_connection
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone

from anymail.backends.mailersend import EmailBackend as MailerSendBackend
from anymail.exceptions import (
    AnymailAPIError,
    AnymailConfigurationError,
    AnymailRequestsAPIError,
)

from shop.models.garage import Garage, GarageInvitation
from shop.models.user import ShopUser


class _FakeResponse:
    def __init__(self, status_code=200, headers=None, text=''):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.reason = ''

    def json(self):
        return json.loads(self.text)


class _FakeSession:
    """Stand-in for requests.Session that records requests instead of sending them."""

    def __init__(self, response):
        self.headers = {}
        self._response = response
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self._response

    def close(self):
        pass


@override_settings(
    EMAIL_BACKEND='anymail.backends.mailersend.EmailBackend',
    ANYMAIL={'MAILERSEND_API_TOKEN': 'test-token'},
)
class MailerSendBackendTests(TestCase):
    def _patch_session(self, fake_session):
        return patch(
            'anymail.backends.base_requests.requests.Session',
            return_value=fake_session,
        )

    def test_send_success_posts_to_mailersend_email_endpoint(self):
        fake_session = _FakeSession(
            _FakeResponse(headers={'Content-Type': 'text/plain', 'X-Message-Id': 'MSG-123'})
        )
        with self._patch_session(fake_session):
            message = EmailMessage(
                subject='Test', body='Body',
                to=['one@example.com'], from_email='from@example.com',
            )
            self.assertEqual(message.send(), 1)
            self.assertEqual(message.anymail_status.status, {'queued'})
            self.assertEqual(message.anymail_status.message_id, 'MSG-123')

        self.assertEqual(len(fake_session.calls), 1)
        params = fake_session.calls[0]
        self.assertEqual(params['url'], 'https://api.mailersend.com/v1/email')
        self.assertEqual(params['method'], 'POST')
        self.assertEqual(params['headers']['Authorization'], 'Bearer test-token')
        self.assertEqual(params['headers']['Content-Type'], 'application/json')
        payload = json.loads(params['data'])
        self.assertEqual(payload['from'], {'email': 'from@example.com'})
        self.assertEqual(payload['to'], [{'email': 'one@example.com'}])
        self.assertEqual(payload['subject'], 'Test')
        self.assertEqual(payload['text'], 'Body')

    def test_send_error_raises_anymail_api_error(self):
        fake_session = _FakeSession(
            _FakeResponse(
                status_code=422,
                headers={'Content-Type': 'application/json'},
                text='{"message": "validation_error"}',
            )
        )
        with self._patch_session(fake_session):
            message = EmailMessage(
                subject='Test', body='Body',
                to=['one@example.com'], from_email='from@example.com',
            )
            with self.assertRaises(AnymailAPIError):
                message.send()

    def test_send_network_failure_raises_anymail_requests_api_error(self):
        fake_session = _FakeSession(_FakeResponse())

        def raise_timeout(**kwargs):
            raise requests.ConnectionError('boom')

        fake_session.request = raise_timeout
        with self._patch_session(fake_session):
            message = EmailMessage(
                subject='Test', body='Body',
                to=['one@example.com'], from_email='from@example.com',
            )
            with self.assertRaises(AnymailRequestsAPIError):
                message.send()

    def test_fail_silently_suppresses_errors(self):
        fake_session = _FakeSession(
            _FakeResponse(
                status_code=422,
                headers={'Content-Type': 'application/json'},
                text='{"message": "validation_error"}',
            )
        )
        with self._patch_session(fake_session):
            message = EmailMessage(
                subject='Test', body='Body',
                to=['one@example.com'], from_email='from@example.com',
            )
            connection = get_connection(fail_silently=True)
            self.assertEqual(connection.send_messages([message]), 0)

    def test_missing_token_raises_configuration_error(self):
        with override_settings(ANYMAIL={}):
            with self.assertRaises(AnymailConfigurationError):
                MailerSendBackend()


class LocmemEndToEndTests(TestCase):
    """The pytest/e2e settings force the locmem backend; verify the standard
    Django email API still dispatches through it for the real send sites."""

    def setUp(self):
        self.owner = ShopUser.objects.create_user(
            username='owner', email='owner@example.com', password='pass1234',
        )
        self.garage = Garage.objects.create(name='Alpha Garage', created_by=self.owner)
        self.invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='member@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            expires_at=timezone.now() + timedelta(days=14),
        )

    def test_send_invitation_email_delivers_to_outbox(self):
        sent = self.invitation.send_invitation_email(accept_base_url='https://example.com/accept')

        self.assertEqual(sent, 1)
        self.assertEqual(len(django_mail.outbox), 1)
        self.assertEqual(django_mail.outbox[0].to, ['member@example.com'])
        self.assertIn(f'https://example.com/accept/{self.invitation.token}', django_mail.outbox[0].body)
