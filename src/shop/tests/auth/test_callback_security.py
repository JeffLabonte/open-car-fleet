import json
from unittest.mock import patch

import requests
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from shop.models.user import ShopUser
from shop.tests.helpers import FakeHankoResponse


class HankoCallbackSecurityTests(TestCase):
    def test_callback_requires_a_session_token(self):
        response = self.client.post(
            reverse("shop-hanko-callback"),
            data=json.dumps({"user": {"id": "forged-user", "email": "forged@example.com"}}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Missing session token")
        self.assertFalse(ShopUser.objects.exists())

    @override_settings(HANKO_API_URL="https://hanko.example.com")
    def test_callback_uses_verified_hanko_identity_instead_of_client_payload(self):
        payload = {
            "user": {
                "id": "attacker-controlled-id",
                "email": "victim@example.com",
                "name": "Attacker supplied name",
            },
            "session_token": "verified-session-token",
        }

        with patch(
            "shop.auth.requests.post",
            return_value=FakeHankoResponse(
                {
                    "is_valid": True,
                    "claims": {
                        "sub": "verified-hanko-id",
                        "email": "verified@example.com",
                        "username": "Verified User",
                    },
                }
            ),
        ) as request:
            response = self.client.post(
                reverse("shop-hanko-callback"),
                data=json.dumps(payload),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["email"], "verified@example.com")
        self.assertFalse(ShopUser.objects.filter(email="victim@example.com").exists())
        self.assertTrue(ShopUser.objects.filter(email="verified@example.com").exists())
        request.assert_called_once_with(
            "https://hanko.example.com/sessions/validate",
            json={"session_token": "verified-session-token"},
            timeout=5,
        )

    def test_callback_fails_closed_when_hanko_rejects_the_token(self):
        with patch("shop.auth.requests.post", side_effect=requests.HTTPError("invalid token")):
            response = self.client.post(
                reverse("shop-hanko-callback"),
                data=json.dumps(
                    {
                        "user": {"id": "forged-id", "email": "forged@example.com"},
                        "session_token": "invalid-token",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "Invalid Hanko session")
        self.assertFalse(ShopUser.objects.exists())
        self.assertNotIn("hanko_session_token", self.client.session)

    def test_callback_requires_csrf_protection(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse("shop-hanko-callback"),
            data=json.dumps({"session_token": "token"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_callback_rejects_disabled_users(self):
        disabled_user = ShopUser.objects.create_user(
            username="disabled-user",
            email="disabled@example.com",
            password="pass1234",
        )
        disabled_user.hanko_id = "disabled-hanko-id"
        disabled_user.is_active = False
        disabled_user.save(update_fields=["hanko_id", "is_active"])

        with patch(
            "shop.auth.requests.post",
            return_value=FakeHankoResponse(
                {
                    "is_valid": True,
                    "claims": {
                        "sub": "disabled-hanko-id",
                        "email": "disabled@example.com",
                    },
                }
            ),
        ):
            response = self.client.post(
                reverse("shop-hanko-callback"),
                data=json.dumps(
                    {
                        "user": {"id": "disabled-hanko-id", "email": "disabled@example.com"},
                        "session_token": "token",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.client.session.get("hanko_session_token"))

    def test_callback_prevents_silent_hanko_id_takeover_via_email(self):
        existing = ShopUser.objects.create_user(
            username="local-only",
            email="local@example.com",
            password="pass1234",
        )
        # Intentionally no hanko_id: this simulates a local account that an
        # attacker tries to take over by signing in via Hanko with the same email.
        self.assertIsNone(existing.hanko_id)

        with patch(
            "shop.auth.requests.post",
            return_value=FakeHankoResponse(
                {
                    "is_valid": True,
                    "claims": {
                        "sub": "attacker-hanko-id",
                        "email": "local@example.com",
                    },
                }
            ),
        ):
            response = self.client.post(
                reverse("shop-hanko-callback"),
                data=json.dumps(
                    {
                        "user": {"id": "attacker-hanko-id", "email": "local@example.com"},
                        "session_token": "token",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 401)
        existing.refresh_from_db()
        self.assertIsNone(existing.hanko_id)

    def test_callback_prevents_hanko_id_swap_for_linked_account(self):
        user = ShopUser.objects.create_user(
            username="linked-user",
            email="linked@example.com",
            password="pass1234",
        )
        user.hanko_id = "original-hanko-id"
        user.save(update_fields=["hanko_id"])

        with patch(
            "shop.auth.requests.post",
            return_value=FakeHankoResponse(
                {
                    "is_valid": True,
                    "claims": {
                        "sub": "different-hanko-id",
                        "email": "linked@example.com",
                    },
                }
            ),
        ):
            response = self.client.post(
                reverse("shop-hanko-callback"),
                data=json.dumps(
                    {
                        "user": {"id": "different-hanko-id", "email": "linked@example.com"},
                        "session_token": "token",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 401)
