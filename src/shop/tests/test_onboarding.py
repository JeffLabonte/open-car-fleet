import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from shop.models.user import ShopUser
from shop.tests.helpers import FakeHankoResponse


class OnboardingViewTests(TestCase):
    def test_welcome_view_requires_login(self):
        response = self.client.get(reverse("shop-welcome"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(f"{reverse('shop-login')}?next="))

    def test_welcome_view_renders_for_incomplete_user(self):
        user = ShopUser.objects.create_user(username="new-user", email="new@example.com", password="pass1234")
        self.client.force_login(user)

        response = self.client.get(reverse("shop-welcome"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "onboarding-form")
        self.assertContains(response, "I am a mechanic")

    def test_welcome_view_redirects_when_onboarding_completed(self):
        user = ShopUser.objects.create_user(
            username="existing-user",
            email="existing@example.com",
            password="pass1234",
            onboarding_completed=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("shop-welcome"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("shop-index"))

    def test_onboarding_submission_sets_profile_and_redirects(self):
        user = ShopUser.objects.create_user(username="new-user", email="new@example.com", password="pass1234")
        self.client.force_login(user)

        response = self.client.post(
            reverse("shop-welcome"),
            {
                "first_name": "John",
                "last_name": "Smith",
                "is_mechanic": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("shop-index"))
        user.refresh_from_db()
        self.assertEqual(user.first_name, "John")
        self.assertEqual(user.last_name, "Smith")
        self.assertEqual(user.username, "John-Smith")
        self.assertTrue(user.is_mechanic)
        self.assertTrue(user.onboarding_completed)
        self.assertIsNotNone(user.mechanic_promoted_at)

    def test_onboarding_submission_without_mechanic_flag(self):
        user = ShopUser.objects.create_user(username="new-user", email="new@example.com", password="pass1234")
        self.client.force_login(user)

        response = self.client.post(
            reverse("shop-welcome"),
            {
                "first_name": "John",
                "last_name": "Smith",
                "is_mechanic": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.username, "John-Smith")
        self.assertFalse(user.is_mechanic)
        self.assertTrue(user.onboarding_completed)

    def test_onboarding_requires_name(self):
        user = ShopUser.objects.create_user(username="new-user", email="new@example.com", password="pass1234")
        self.client.force_login(user)

        response = self.client.post(
            reverse("shop-welcome"),
            {
                "first_name": "",
                "last_name": "",
                "is_mechanic": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter your first or last name")


class OnboardingRedirectTests(TestCase):
    def test_new_user_is_redirected_to_welcome_after_hanko_callback(self):
        payload = {
            "user": {
                "id": "hanko-new-user",
                "email": "onboarding@example.com",
                "name": "New User",
                "display_name": "New User",
                "provider": "hanko",
            },
            "session_token": "session-token-new",
        }

        with patch(
            "shop.auth.requests.post",
            return_value=FakeHankoResponse(
                {
                    "is_valid": True,
                    "claims": {
                        "sub": "hanko-new-user",
                        "email": "onboarding@example.com",
                        "username": "New User",
                    },
                }
            ),
        ):
            response = self.client.post(
                reverse("shop-hanko-callback"),
                data=json.dumps(payload),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["redirect_url"], reverse("shop-welcome"))

        user = ShopUser.objects.get(email="onboarding@example.com")
        self.assertFalse(user.onboarding_completed)

    def test_existing_complete_user_skips_welcome_after_hanko_callback(self):
        ShopUser.objects.create_user(
            username="existing-user",
            email="existing@example.com",
            password="pass1234",
            hanko_id="hanko-existing-user",
            onboarding_completed=True,
        )
        payload = {
            "user": {
                "id": "hanko-existing-user",
                "email": "existing@example.com",
                "name": "Existing User",
                "display_name": "Existing User",
                "provider": "hanko",
            },
            "session_token": "session-token-existing",
        }

        with patch(
            "shop.auth.requests.post",
            return_value=FakeHankoResponse(
                {
                    "is_valid": True,
                    "claims": {
                        "sub": "hanko-existing-user",
                        "email": "existing@example.com",
                        "username": "Existing User",
                    },
                }
            ),
        ):
            response = self.client.post(
                reverse("shop-hanko-callback"),
                data=json.dumps(payload),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertNotIn("redirect_url", data)
