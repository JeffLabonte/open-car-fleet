from functools import wraps
import time
from typing import Any, Callable, Optional, cast

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest
from django.http import HttpResponse
from django.contrib.auth.views import redirect_to_login
from django.utils.deprecation import MiddlewareMixin
from django_ratelimit.exceptions import Ratelimited

from shop.auth import HankoAuthenticationError, complete_hanko_login, fetch_hanko_userinfo


PUBLIC_PATHS = {
    '/login',
    '/login/',
    '/theme',
    '/theme/',
    '/auth/hanko/callback/',
    '/set-test-session/',
}

PUBLIC_PREFIXES = (
    '/static/',
)

# How often (seconds) an already-authenticated Django session is revalidated
# against the Hanko API, so revoking a Hanko session eventually logs the user
# out of Django too.
SESSION_RECHECK_INTERVAL = 15 * 60


class RatelimitMiddleware(MiddlewareMixin):
    """Return 429 Too Many Requests for django-ratelimit violations."""

    def process_exception(self, request: HttpRequest, exception: BaseException) -> Optional[HttpResponse]:
        if isinstance(exception, Ratelimited):
            return HttpResponse('Too Many Requests', status=429)
        return None


class ContentSecurityPolicyMiddleware(MiddlewareMixin):
    """Add a baseline Content-Security-Policy to all responses."""

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        hanko_api = getattr(settings, 'HANKO_API_URL', '') or ''
        connect_src = "'self'"
        if hanko_api:
            from urllib.parse import urlparse
            parsed = urlparse(hanko_api)
            if parsed.scheme and parsed.netloc:
                connect_src += f" {parsed.scheme}://{parsed.netloc}"
        response['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self'; "
            f"connect-src {connect_src}; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response


class HankoAuthenticationMiddleware(MiddlewareMixin):
    """Bridge Hanko's frontend session to Django's authenticated user state."""

    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        if request.path in PUBLIC_PATHS or request.path.startswith(PUBLIC_PREFIXES):
            return None

        if request.path.startswith('/theme/'):
            return None

        if request.user.is_authenticated:
            hanko_session_token = request.session.get('hanko_session_token')
            if hanko_session_token:
                last_check = request.session.get('hanko_last_check', 0)
                if time.time() - last_check > SESSION_RECHECK_INTERVAL:
                    try:
                        user_info = fetch_hanko_userinfo(hanko_session_token)
                    except HankoAuthenticationError:
                        logout(request)
                        return cast(HttpResponse, redirect_to_login(request.get_full_path()))
                    local_hanko_id = getattr(request.user, 'hanko_id', None)
                    remote_hanko_id = user_info.get('id')
                    if local_hanko_id and remote_hanko_id != local_hanko_id:
                        logout(request)
                        return cast(HttpResponse, redirect_to_login(request.get_full_path()))
                    request.session['hanko_last_check'] = time.time()
                    request.session.save()
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

        # Bind the remote Hanko identity to the local user we just authenticated.
        if request.user.hanko_id != user_info.get('id'):
            logout(request)
            return cast(HttpResponse, redirect_to_login(request.get_full_path()))

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
