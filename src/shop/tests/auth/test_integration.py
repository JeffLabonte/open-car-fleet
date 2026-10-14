import json
from typing import cast
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings
from django.urls import reverse

from shop import views
from shop.middleware import HankoAuthenticationMiddleware
from shop.models.user import ShopUser
from shop.tests.helpers import FakeHankoResponse


class HankoAuthenticationIntegrationTests(TestCase):
    def test_logged_off_users_are_redirected_to_login_from_app_routes(self):
        response = self.client.get(reverse("shop-index"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(f"{reverse('shop-login')}?next="))

        login_response = self.client.get(reverse("shop-login"))
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

        with patch(
            "shop.auth.requests.post",
            return_value=FakeHankoResponse(
                {
                    "is_valid": True,
                    "claims": {
                        "sub": "hanko-user-123",
                        "email": "driver@example.com",
                        "username": "Test Driver",
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
        self.assertTrue(response.json()["ok"])

        user = ShopUser.objects.get(email="driver@example.com")
        self.assertEqual(user.hanko_id, "hanko-user-123")
        self.assertEqual(user.display_name, "Test Driver")
        self.assertTrue(user.is_active)
        self.assertFalse(user.fleets.exists())

        self.client.logout()
        self.client.session["hanko_session_token"] = "session-token-123"
        self.client.session.save()

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "is_valid": True,
                    "claims": {
                        "sub": "hanko-user-123",
                        "email": "driver@example.com",
                        "username": "Test Driver",
                    },
                }

        with patch("shop.auth.requests.post", return_value=FakeResponse()):
            self.client.get(reverse("shop-index"))

        factory = RequestFactory()
        request = factory.get(reverse("shop-index"))

        def next_response(_request: HttpRequest) -> HttpResponse:
            return HttpResponse()

        SessionMiddleware(next_response).process_request(request)
        request.session["hanko_session_token"] = "session-token-123"
        request.session.save()
        AuthenticationMiddleware(next_response).process_request(request)

        with patch("shop.auth.requests.post", return_value=FakeResponse()):
            HankoAuthenticationMiddleware(next_response).process_request(request)

        self.assertTrue(request.user.is_authenticated)
        authenticated_user = cast(ShopUser, request.user)
        self.assertEqual(authenticated_user.email, "driver@example.com")
        self.assertEqual(request.session.get("hanko_user_id"), "hanko-user-123")
        self.assertEqual(request.session.get("hanko_email"), "driver@example.com")

        refreshed_user = get_user_model().objects.get(pk=user.pk)
        self.assertEqual(refreshed_user.email, "driver@example.com")

    def test_logout_clears_hanko_session_and_redirects(self):
        user = ShopUser.objects.create_user(username="logout-user", email="logout@example.com", password="pass1234")
        self.client.force_login(user)
        self.client.session["hanko_session_token"] = "session-token-123"
        self.client.session["hanko_user_id"] = "hanko-user-123"
        self.client.session.save()

        response = self.client.post(reverse("shop-logout"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("shop-login"))
        self.assertNotIn("hanko_session_token", self.client.session)
        self.assertNotIn("hanko_user_id", self.client.session)

    def test_logout_marker_is_one_time_in_login_context(self):
        user = ShopUser.objects.create_user(username="logout-user-2", email="logout2@example.com", password="pass1234")
        self.client.force_login(user)

        self.client.post(reverse("shop-logout"))

        first_login_page = self.client.get(reverse("shop-login"))
        second_login_page = self.client.get(reverse("shop-login"))

        self.assertEqual(first_login_page.context["logged_out"], True)
        self.assertEqual(second_login_page.context["logged_out"], False)

    def test_profile_view_requires_login(self):
        response = self.client.get(reverse("shop-profile"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(f"{reverse('shop-login')}?next="))

    @override_settings(HANKO_API_URL="https://hanko.example.com")
    def test_profile_view_renders_for_authenticated_user(self):
        user = ShopUser.objects.create_user(username="profile-user", email="profile@example.com", password="pass1234")
        self.client.force_login(user)

        response = self.client.get(reverse("shop-profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<hanko-profile")
        self.assertContains(response, "https://hanko.example.com")
        self.assertContains(response, "hanko-profile-container")

    @override_settings(HANKO_API_URL="")
    def test_profile_view_shows_missing_api_url_message(self):
        user = ShopUser.objects.create_user(
            username="profile-user-no-api", email="profile-no-api@example.com", password="pass1234"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("shop-profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Missing HANKO_API_URL")

    @override_settings(
        ALLOWED_HOSTS=["xps-server.kanyu-bluegill.ts.net"],
        CSRF_TRUSTED_ORIGINS=["https://xps-server.kanyu-bluegill.ts.net"],
    )
    def test_logout_with_trusted_origin_succeeds(self):
        from django.middleware.csrf import get_token
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        user = ShopUser.objects.create_user(username="csrf-user", email="csrf@example.com", password="pass1234")
        client.force_login(user)

        # login_view doesn't render a {% csrf_token %} tag, so no CSRF cookie
        # is ever set by the response. Generate a token directly and seed it
        # on the client so both the cookie and the submitted form field agree.
        csrf_token = get_token(RequestFactory().get("/"))
        client.cookies["csrftoken"] = csrf_token

        # Untrusted origin fails CSRF check with 403
        untrusted_resp = client.post(
            reverse("shop-logout"),
            {"csrfmiddlewaretoken": csrf_token},
            HTTP_ORIGIN="https://untrusted-domain.com",
            HTTP_HOST="xps-server.kanyu-bluegill.ts.net",
        )
        self.assertEqual(untrusted_resp.status_code, 403)

        # Trusted origin succeeds with 302
        trusted_resp = client.post(
            reverse("shop-logout"),
            {"csrfmiddlewaretoken": csrf_token},
            HTTP_ORIGIN="https://xps-server.kanyu-bluegill.ts.net",
            HTTP_HOST="xps-server.kanyu-bluegill.ts.net",
        )
        self.assertEqual(trusted_resp.status_code, 302)

    def test_theme_preference_sets_cookie_and_redirects(self):
        response = self.client.get(
            reverse("shop-theme", kwargs={"theme": "dark"}),
            {"next": reverse("shop-login")},
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("shop-login"))
        self.assertEqual(response.cookies["theme"].value, "dark")
        self.assertEqual(response.cookies["theme"]["max-age"], "31536000")

    def test_login_page_renders_current_theme_attribute(self):
        response = self.client.get(reverse("shop-login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-theme="light"')

    def test_login_page_includes_mobile_viewport_and_theme_toggle(self):
        response = self.client.get(reverse("shop-login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<meta name="viewport"')
        self.assertContains(response, 'data-testid="theme-toggle"')
        self.assertContains(response, "<span>Light</span>")
        self.assertContains(response, "<span>Dark</span>")

    @override_settings(HANKO_API_URL="https://hanko.example.com")
    def test_car_list_uses_hanko_session_token_to_authenticate(self):
        factory = RequestFactory()
        request = factory.get(reverse("shop-car-list"))

        def next_response(_request: HttpRequest) -> HttpResponse:
            return HttpResponse()

        SessionMiddleware(next_response).process_request(request)
        request.session["hanko_session_token"] = "session-token-123"
        request.session.save()
        AuthenticationMiddleware(next_response).process_request(request)

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "is_valid": True,
                    "claims": {
                        "sub": "hanko-user-123",
                        "email": "driver@example.com",
                        "username": "Test Driver",
                    },
                }

        with patch("shop.auth.requests.post", return_value=FakeResponse()):
            response = views.car_list(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Cars", response.content)
