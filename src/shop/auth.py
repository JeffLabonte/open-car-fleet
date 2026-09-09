import re
import os
from typing import Any, Optional

import requests
from django.contrib.auth import login
from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from shop.models.user import ShopUser


class HankoAuthenticationError(ValueError):
    """Raised when a Hanko session cannot be verified or parsed safely."""


def fetch_hanko_userinfo(session_token: str) -> dict[str, Any]:
    """Fetch and validate the identity bound to a Hanko session token."""
    if not isinstance(session_token, str) or not session_token.strip():
        raise HankoAuthenticationError('A Hanko session token is required.')

    api_url = getattr(settings, 'HANKO_API_URL', '') or os.environ.get('HANKO_API_URL', '')
    if not api_url:
        raise HankoAuthenticationError('HANKO_API_URL is not configured.')

    try:
        response = requests.get(
            f"{api_url.rstrip('/')}/userinfo",
            headers={'Authorization': f'Bearer {session_token.strip()}'},
            timeout=5,
        )
        response.raise_for_status()
        raw_user_info = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise HankoAuthenticationError('Unable to verify the Hanko session.') from exc

    if not isinstance(raw_user_info, dict):
        raise HankoAuthenticationError('Hanko returned an invalid user response.')

    user_info = dict(raw_user_info)
    user_id = next(
        (
            value.strip()
            for key in ('id', 'user_id', 'hanko_id')
            for value in [user_info.get(key)]
            if isinstance(value, str) and value.strip()
        ),
        '',
    )
    if not user_id:
        raise HankoAuthenticationError('Hanko returned no user identifier.')
    user_info['id'] = user_id

    email = user_info.get('email')
    if not isinstance(email, str) or not email.strip():
        emails = user_info.get('emails')
        first_email = emails[0] if isinstance(emails, list) and emails else None
        if isinstance(first_email, dict):
            email = first_email.get('address')
        if isinstance(email, str) and email.strip():
            user_info['email'] = email.strip()

    for key in ('email', 'email_address', 'name', 'display_name', 'username', 'avatar_url', 'avatar', 'provider'):
        value = user_info.get(key)
        if value is not None and not isinstance(value, str):
            raise HankoAuthenticationError(f'Hanko returned an invalid {key} value.')

    return user_info


def _build_username(base_name: str, hanko_id: str | None = None) -> str:
    fallback = f"hanko-{hanko_id or 'user'}"
    candidate = re.sub(r'[^\w.@+-]', '-', (base_name or '').strip()) or fallback
    candidate = candidate[:150]
    if not candidate:
        candidate = fallback

    existing = ShopUser.objects.filter(username=candidate).exists()
    if not existing:
        return candidate

    counter = 1
    while True:
        alt = f"{candidate}{counter}"
        if not ShopUser.objects.filter(username=alt).exists():
            return alt
        counter += 1


def sync_hanko_user(
    hanko_id: Optional[str] = None,
    email: Optional[str] = None,
    username: Optional[str] = None,
    avatar_url: str = '',
    provider: str = 'hanko',
) -> ShopUser:
    hanko_id = hanko_id or ''
    email = (email or '').strip().lower()
    username = (username or '').strip()

    if hanko_id:
        user = ShopUser.objects.filter(hanko_id=hanko_id).first()
        if user:
            if email and not user.email:
                user.email = email
            if username and not user.display_name:
                user.display_name = username
            if avatar_url and not user.avatar_url:
                user.avatar_url = avatar_url
            if provider:
                user.auth_provider = provider
            user.last_login_at = timezone.now()
            user.save(update_fields=[
                'email',
                'display_name',
                'avatar_url',
                'auth_provider',
                'last_login_at',
            ])
            return user

    if email:
        user = ShopUser.objects.filter(email__iexact=email).first()
        if user:
            if hanko_id:
                user.hanko_id = hanko_id
            if username:
                user.display_name = username
            if avatar_url:
                user.avatar_url = avatar_url
            if provider:
                user.auth_provider = provider
            user.last_login_at = timezone.now()
            user.save(update_fields=['hanko_id', 'display_name', 'avatar_url', 'auth_provider', 'last_login_at'])
            return user

    base_username = username or email.split('@')[0] if email else None
    user = ShopUser.objects.create_user(
        username=_build_username(base_username or 'hanko-user', hanko_id),
        email=email,
        password=None,
    )
    user.hanko_id = hanko_id or None
    user.display_name = username or (email.split('@')[0] if email else 'Hanko User')
    user.avatar_url = avatar_url
    user.auth_provider = provider
    user.last_login_at = timezone.now()
    user.is_active = True
    user.save()
    return user


def complete_hanko_login(request: HttpRequest, user_data: dict[str, Any]) -> ShopUser:
    user = sync_hanko_user(
        hanko_id=user_data.get('id') or user_data.get('user_id') or user_data.get('hanko_id') or '',
        email=user_data.get('email') or user_data.get('email_address') or '',
        username=user_data.get('name') or user_data.get('display_name') or user_data.get('username') or '',
        avatar_url=user_data.get('avatar_url') or user_data.get('avatar') or '',
        provider=user_data.get('provider') or 'hanko',
    )
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.user = user
    request.session['hanko_user_id'] = user.hanko_id or str(user.pk)
    request.session['hanko_email'] = user.email
    request.session['hanko_username'] = user.display_name or user.username
    request.session['hanko_avatar_url'] = user.avatar_url or ''
    request.session['hanko_provider'] = user.auth_provider
    request.session.save()
    return user
