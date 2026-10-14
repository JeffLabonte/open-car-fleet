import logging
import re
from typing import Any, Optional

import requests
from django.conf import settings
from django.contrib.auth import login
from django.http import HttpRequest
from django.utils import timezone

from shop.models.user import ShopUser

security_log = logging.getLogger("security")


class HankoAuthenticationError(ValueError):
    """Raised when a Hanko session cannot be verified or parsed safely."""


def _extract_hanko_email(raw_email: Any) -> str:
    if isinstance(raw_email, str) and raw_email.strip():
        return raw_email.strip()
    if isinstance(raw_email, dict):
        address = raw_email.get("address")
        if isinstance(address, str) and address.strip():
            return address.strip()
    return ""


def _extract_hanko_username(raw_username: Any) -> str:
    if isinstance(raw_username, str) and raw_username.strip():
        return raw_username.strip()
    if isinstance(raw_username, dict):
        name = raw_username.get("username")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return ""


def fetch_hanko_userinfo(session_token: str) -> dict[str, Any]:
    """Fetch and validate the identity bound to a Hanko session token."""
    if not isinstance(session_token, str) or not session_token.strip():
        security_log.warning("hanko_auth_failed: reason=missing_session_token")
        raise HankoAuthenticationError("A Hanko session token is required.")

    api_url = getattr(settings, "HANKO_API_URL", "")
    if not api_url:
        security_log.warning("hanko_auth_failed: reason=missing_api_url")
        raise HankoAuthenticationError("HANKO_API_URL is not configured.")

    try:
        response = requests.post(
            f"{api_url.rstrip('/')}/sessions/validate",
            json={"session_token": session_token.strip()},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        security_log.warning("hanko_auth_failed: reason=api_error error=%s", exc)
        raise HankoAuthenticationError("Unable to verify the Hanko session.") from exc

    if not isinstance(data, dict):
        raise HankoAuthenticationError("Hanko returned an invalid session response.")

    if data.get("is_valid") is not True:
        raise HankoAuthenticationError("Hanko session is not valid.")

    claims = data.get("claims")
    if not isinstance(claims, dict):
        raise HankoAuthenticationError("Hanko returned invalid session claims.")

    user_id = next(
        (
            value.strip()
            for key in ("sub", "subject", "user_id", "id")
            for value in [claims.get(key)]
            if isinstance(value, str) and value.strip()
        ),
        "",
    )
    if not user_id:
        raise HankoAuthenticationError("Hanko returned no user identifier.")

    email = _extract_hanko_email(claims.get("email"))
    username = _extract_hanko_username(claims.get("username"))

    return {
        "id": user_id,
        "user_id": user_id,
        "hanko_id": user_id,
        "email": email,
        "email_address": email,
        "name": username,
        "display_name": username,
        "avatar_url": "",
        "avatar": "",
        "provider": "hanko",
    }


def _build_username(base_name: str, hanko_id: str | None = None) -> str:
    fallback = f"hanko-{hanko_id or 'user'}"
    candidate = re.sub(r"[^\w.@+-]", "-", (base_name or "").strip()) or fallback
    # Reserve room for a numeric collision suffix so the final username never
    # exceeds Django's 150-character AbstractUser username limit.
    candidate = candidate[:140]
    if not candidate:
        candidate = fallback[:140]

    existing = ShopUser.objects.filter(username=candidate).exists()
    if not existing:
        return candidate

    counter = 1
    while True:
        suffix = str(counter)
        alt = f"{candidate[: 150 - len(suffix)]}{suffix}"
        if not ShopUser.objects.filter(username=alt).exists():
            return alt
        counter += 1


def _find_user_by_hanko_id(hanko_id: str) -> ShopUser | None:
    if not hanko_id:
        return None
    return ShopUser.objects.filter(hanko_id=hanko_id).first()


def _find_user_by_email(email: str) -> ShopUser | None:
    if not email:
        return None
    return ShopUser.objects.filter(email__iexact=email).first()


def _backfill_empty_profile_fields(
    user: ShopUser,
    *,
    email: str,
    username: str,
    avatar_url: str,
    provider: str,
) -> None:
    if email and not user.email:
        user.email = email
    if username and not user.display_name:
        user.display_name = username
    if avatar_url and not user.avatar_url:
        user.avatar_url = avatar_url
    if provider:
        user.auth_provider = provider
    user.last_login_at = timezone.now()


def _apply_profile_updates(
    user: ShopUser,
    *,
    username: str,
    avatar_url: str,
    provider: str,
) -> None:
    if username:
        user.display_name = username
    if avatar_url:
        user.avatar_url = avatar_url
    if provider:
        user.auth_provider = provider
    user.last_login_at = timezone.now()


def _verify_email_identity_match(user: ShopUser, hanko_id: str) -> None:
    existing_hanko_id = (user.hanko_id or "").strip()
    if existing_hanko_id and existing_hanko_id != hanko_id:
        security_log.warning(
            "hanko_auth_failed: reason=hanko_id_mismatch email=%s existing_hanko_id=%s attempted_hanko_id=%s",
            user.email,
            existing_hanko_id,
            hanko_id,
        )
        raise HankoAuthenticationError("Hanko identity does not match the account linked to this email.")
    if not existing_hanko_id and hanko_id:
        # A local account with this email exists but has no Hanko identity
        # attached. Do not silently link identities; require explicit,
        # verified linking to prevent account takeover.
        security_log.warning(
            "hanko_auth_failed: reason=silent_link_prevented email=%s attempted_hanko_id=%s",
            user.email,
            hanko_id,
        )
        raise HankoAuthenticationError(
            "An account with this email already exists. Please contact an administrator to link Hanko sign-in."
        )


def _create_hanko_user(
    *,
    hanko_id: str,
    email: str,
    username: str,
    avatar_url: str,
    provider: str,
) -> ShopUser:
    base_username = username or email.split("@")[0] if email else None
    user = ShopUser.objects.create_user(
        username=_build_username(base_username or "hanko-user", hanko_id),
        email=email,
        password=None,
    )
    user.hanko_id = hanko_id or None
    user.display_name = username or (email.split("@")[0] if email else "Hanko User")
    user.avatar_url = avatar_url
    user.auth_provider = provider
    user.last_login_at = timezone.now()
    user.is_active = True
    user.save()
    return user


def sync_hanko_user(
    hanko_id: Optional[str] = None,
    email: Optional[str] = None,
    username: Optional[str] = None,
    avatar_url: str = "",
    provider: str = "hanko",
) -> ShopUser:
    hanko_id = hanko_id or ""
    email = (email or "").strip().lower()
    username = (username or "").strip()

    user = _find_user_by_hanko_id(hanko_id)
    if user:
        _backfill_empty_profile_fields(
            user,
            email=email,
            username=username,
            avatar_url=avatar_url,
            provider=provider,
        )
        user.save(
            update_fields=[
                "email",
                "display_name",
                "avatar_url",
                "auth_provider",
                "last_login_at",
            ]
        )
        return user

    user = _find_user_by_email(email)
    if user:
        _verify_email_identity_match(user, hanko_id)
        _apply_profile_updates(
            user,
            username=username,
            avatar_url=avatar_url,
            provider=provider,
        )
        user.save(update_fields=["display_name", "avatar_url", "auth_provider", "last_login_at"])
        return user

    return _create_hanko_user(
        hanko_id=hanko_id,
        email=email,
        username=username,
        avatar_url=avatar_url,
        provider=provider,
    )


def complete_hanko_login(request: HttpRequest, user_data: dict[str, Any]) -> ShopUser:
    user = sync_hanko_user(
        hanko_id=user_data.get("id") or user_data.get("user_id") or user_data.get("hanko_id") or "",
        email=user_data.get("email") or user_data.get("email_address") or "",
        username=user_data.get("name") or user_data.get("display_name") or user_data.get("username") or "",
        avatar_url=user_data.get("avatar_url") or user_data.get("avatar") or "",
        provider=user_data.get("provider") or "hanko",
    )
    if not user.is_active:
        security_log.warning(
            "hanko_auth_failed: reason=disabled_account user=%s hanko_id=%s",
            user.pk,
            user.hanko_id,
        )
        raise HankoAuthenticationError("Account is disabled.")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.user = user
    request.session["hanko_user_id"] = user.hanko_id or str(user.pk)
    request.session["hanko_email"] = user.email
    request.session["hanko_username"] = user.display_name or user.username
    request.session["hanko_avatar_url"] = user.avatar_url or ""
    request.session["hanko_provider"] = user.auth_provider
    request.session.save()
    return user
