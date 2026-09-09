from functools import wraps
from typing import Any, Callable, Optional, cast

from django.contrib.auth import logout
from django.http import HttpRequest
from django.http import HttpResponse
from django.contrib.auth.views import redirect_to_login
from django.utils.deprecation import MiddlewareMixin

from shop.auth import HankoAuthenticationError, complete_hanko_login, fetch_hanko_userinfo


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


        try:
            user_info = fetch_hanko_userinfo(hanko_session_token)
        except HankoAuthenticationError:
            logout(request)
            return cast(HttpResponse, redirect_to_login(request.get_full_path()))

        complete_hanko_login(request, user_info)
        return None


def hanko_login_required(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Require Django auth and attempt Hanko session rehydration before redirecting to login."""

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        middleware_response = HankoAuthenticationMiddleware(lambda _request: HttpResponse()).process_request(request)
        if middleware_response is not None:
            return middleware_response
        if not request.user.is_authenticated:
            return cast(HttpResponse, redirect_to_login(request.get_full_path()))
        return view_func(request, *args, **kwargs)

    return _wrapped_view
