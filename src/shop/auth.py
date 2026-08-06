import re
from typing import Any, Optional

from django.contrib.auth import login
from django.http import HttpRequest
from django.utils import timezone

from .models.user import ShopUser


def ensure_default_garage(user: ShopUser) -> None:
    """Create a personal garage for users who do not have one yet."""
    if user.garages.exists():
        return

    from .models.garage import Garage, GarageMembership

    display = user.display_name or user.username or user.email.split('@')[0] if user.email else 'User'
    garage = Garage.objects.create(
        name=f"{display}'s Garage",
        created_by=user,
    )
    GarageMembership.objects.create(
        garage=garage,
        user=user,
        role=GarageMembership.ROLE_OWNER,
    )


def _build_username(base_name: str, hanko_id: str | None = None) -> str:
    candidate = re.sub(r'[^\w.@+-]', '-', (base_name or '').strip()) or f"hanko-{hanko_id or 'user'}"
    candidate = candidate[:150]
    if not candidate:
        candidate = f"hanko-{hanko_id or 'user'}"

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
    email = (email or '').strip()
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
    ensure_default_garage(user)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.user = user
    request._cached_user = user
    request.session['hanko_user_id'] = user.hanko_id or str(user.pk)
    request.session['hanko_email'] = user.email
    request.session['hanko_username'] = user.display_name or user.username
    request.session['hanko_avatar_url'] = user.avatar_url or ''
    request.session['hanko_provider'] = user.auth_provider
    request.session.save()
    return user
