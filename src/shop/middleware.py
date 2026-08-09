import os
from functools import wraps
from typing import Any, Callable, Optional, cast

import requests
from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest
from django.http import HttpResponse
from django.contrib.auth.views import redirect_to_login
from django.utils.deprecation import MiddlewareMixin

from shop.auth import complete_hanko_login


PUBLIC_PATHS = {
    '/login',
    '/login/',
    '/theme',
    '/theme/',
    '/auth/hanko/callback/',
}

PUBLIC_PREFIXES = (
    '/static/',
    '/admin/',
)


class HankoAuthenticationMiddleware(MiddlewareMixin):
    """Bridge Hanko's frontend session to Django's authenticated user state."""

    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        if request.path in PUBLIC_PATHS or request.path.startswith(PUBLIC_PREFIXES):
            return None

        if request.path.startswith('/theme/'):
            return None

        if request.user.is_authenticated:
            return None

        hanko_session_token: str | None = request.session.get('hanko_session_token')
        if not hanko_session_token:
            return cast(HttpResponse, redirect_to_login(request.get_full_path()))


        api_url = os.environ.get('HANKO_API_URL', '') or getattr(settings, 'HANKO_API_URL', '')
        if not api_url:
            return cast(HttpResponse, redirect_to_login(request.get_full_path()))

        userinfo_url = f"{api_url.rstrip('/')}/userinfo"
        try:
            response = requests.get(
                userinfo_url,
                headers={'Authorization': f'Bearer {hanko_session_token}'},
                timeout=5,
            )
            response.raise_for_status()
            raw_user_info = response.json()
            if not isinstance(raw_user_info, dict):
                return cast(HttpResponse, redirect_to_login(request.get_full_path()))

            user_info: dict[str, object] = cast(dict[str, object], raw_user_info)
            if not user_info.get('email') and isinstance(user_info.get('emails'), list):
                emails = cast(list[object], user_info['emails'])
                first_email: object = emails[0] if emails else {}
                if isinstance(first_email, dict):
                    first_email_dict = cast(dict[str, object], first_email)
                    user_info['email'] = first_email_dict.get('address', '')
        except (requests.RequestException, ValueError, TypeError):
            logout(request)
            return cast(HttpResponse, redirect_to_login(request.get_full_path()))

        complete_hanko_login(request, user_info)
        return None


def hanko_login_required(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Require Django auth and attempt Hanko session rehydration before redirecting to login."""

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        HankoAuthenticationMiddleware(lambda _request: HttpResponse()).process_request(request)
        if not request.user.is_authenticated:
            return cast(HttpResponse, redirect_to_login(request.get_full_path()))
        return view_func(request, *args, **kwargs)

    return _wrapped_view
