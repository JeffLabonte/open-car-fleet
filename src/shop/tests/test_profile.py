from django.test import TestCase
from django.urls import reverse

from shop.models.user import ShopUser


class ProfileViewTests(TestCase):
    def test_profile_view_requires_login(self):
        response = self.client.get(reverse("shop-profile"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(f"{reverse('shop-login')}?next="))

    def test_profile_view_renders_for_authenticated_user(self):
        user = ShopUser.objects.create_user(
            username="profile-user", email="profile@example.com", password="pass1234", onboarding_completed=True
        )
        self.client.force_login(user)

        response = self.client.get(reverse("shop-profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profile-form")

    def test_profile_update_sets_username_from_name_when_blank(self):
        user = ShopUser.objects.create_user(
            username="old-username",
            email="profile@example.com",
            password="pass1234",
            onboarding_completed=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("shop-profile"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "username": "",
                "email": "jane@example.com",
                "phone_number": "+1 555 123 4567",
                "display_name": "",
                "is_mechanic": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("shop-profile"))
        user.refresh_from_db()
        self.assertEqual(user.username, "Jane-Doe")
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.last_name, "Doe")
        self.assertEqual(user.email, "jane@example.com")
        self.assertEqual(user.phone_number, "+1 555 123 4567")
        self.assertTrue(user.is_mechanic)
        self.assertIsNotNone(user.mechanic_promoted_at)

    def test_profile_update_keeps_explicit_username(self):
        user = ShopUser.objects.create_user(
            username="old-username",
            email="profile@example.com",
            password="pass1234",
            onboarding_completed=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("shop-profile"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "username": "custom-username",
                "email": "jane@example.com",
                "phone_number": "",
                "display_name": "",
                "is_mechanic": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.username, "custom-username")
        self.assertFalse(user.is_mechanic)
        self.assertIsNone(user.mechanic_promoted_at)

    def test_profile_update_rejects_duplicate_username(self):
        ShopUser.objects.create_user(
            username="taken-username",
            email="taken@example.com",
            password="pass1234",
            onboarding_completed=True,
        )
        user = ShopUser.objects.create_user(
            username="profile-user",
            email="profile@example.com",
            password="pass1234",
            onboarding_completed=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("shop-profile"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "username": "taken-username",
                "email": "profile@example.com",
                "phone_number": "",
                "display_name": "",
                "is_mechanic": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already taken")

    def test_profile_update_rejects_missing_name_and_username(self):
        user = ShopUser.objects.create_user(
            username="profile-user",
            email="profile@example.com",
            password="pass1234",
            onboarding_completed=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("shop-profile"),
            {
                "first_name": "",
                "last_name": "",
                "username": "",
                "email": "profile@example.com",
                "phone_number": "",
                "display_name": "",
                "is_mechanic": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter your first or last name")
