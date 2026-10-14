from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from shop.models.user import ShopUser
from shop.tests.helpers import FakeHankoResponse


class HankoSessionBindingTests(TestCase):
    """SEC-006: the remote Hanko identity must match the local user."""

    def test_middleware_recheck_logs_out_when_remote_identity_changes(self):
        user = ShopUser.objects.create_user(
            username='binding-user',
            email='binding@example.com',
            password='pass1234',
        )
        user.hanko_id = 'original-hanko-id'
        user.save(update_fields=['hanko_id'])

        self.client.force_login(user)
        session = self.client.session
        session['hanko_session_token'] = 'session-token-123'
        session['hanko_last_check'] = 0  # force recheck
        session.save()

        with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
            'is_valid': True,
            'claims': {
                'sub': 'attacker-hanko-id',
                'email': 'binding@example.com',
            },
        })):
            response = self.client.get(reverse('shop-index'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(reverse('shop-login')))

    def test_middleware_recheck_allows_matching_identity(self):
        user = ShopUser.objects.create_user(
            username='matching-user',
            email='matching@example.com',
            password='pass1234',
        )
        user.hanko_id = 'matching-hanko-id'
        user.save(update_fields=['hanko_id'])

        self.client.force_login(user)
        session = self.client.session
        session['hanko_session_token'] = 'session-token-123'
        session['hanko_last_check'] = 0
        session.save()

        with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
            'is_valid': True,
            'claims': {
                'sub': 'matching-hanko-id',
                'email': 'matching@example.com',
            },
        })):
            response = self.client.get(reverse('shop-index'))

        self.assertEqual(response.status_code, 200)


