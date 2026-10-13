from typing import Any
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from shop.auth import HankoAuthenticationError, complete_hanko_login, fetch_hanko_userinfo
from shop.middleware import hanko_login_required

def get_theme_from_request(request: HttpRequest) -> str:
    cookie_theme = request.COOKIES.get('theme', '').lower()
    if cookie_theme in {'light', 'dark'}:
        return cookie_theme
    return 'light'


def safe_next_url(request: HttpRequest, default: str = '/') -> str:
    """Return a local, scheme-safe redirect target from ?next=, else the default."""
    candidate = request.GET.get('next', default) or default
    if url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default


def login_view(request: HttpRequest) -> HttpResponse:
    # Always seed a CSRF cookie for the active session so POST-based logout
    # requests from trusted origins can validate even when this page redirects a
    # signed-in user away from the login form.
    get_token(request)

    if request.user.is_authenticated:
        return redirect(reverse('shop-index'))

    # One-time logout marker prevents stale query params from re-triggering
    # frontend logout behavior after users sign back in.
    logged_out = bool(request.session.pop('logged_out', False))

    return render(request, 'shop/login.html', {
        'title': _('Login'),
        'subtitle': _('Authenticate with Hanko to continue'),
            'hanko_api_url': getattr(settings, 'HANKO_API_URL', ''),
        'next_url': safe_next_url(request),
        'logged_out': logged_out,
        'theme': get_theme_from_request(request),
    })


@hanko_login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    return render(request, 'shop/profile.html', {
        'title': _('Profile'),
        'subtitle': _('Manage your Hanko account, emails, and passkeys'),
        'hanko_api_url': getattr(settings, 'HANKO_API_URL', ''),
    })


def theme_view(request: HttpRequest, theme: str) -> HttpResponse:
    normalized_theme = theme.lower() if isinstance(theme, str) else 'light'
    if normalized_theme not in {'light', 'dark'}:
        normalized_theme = 'light'

    response = redirect(safe_next_url(request, default=reverse('shop-index')))
    response.set_cookie('theme', normalized_theme, max_age=60 * 60 * 24 * 365, httponly=False, samesite='Lax')
    response.cookies['theme']['max-age'] = '31536000'
    return response


@require_GET
def set_test_session(request: HttpRequest) -> HttpResponse:
    """DEBUG-only helper that signs a user in by email for Selenium suites.

    The session is created without a Hanko session token, so the
    authentication middleware skips Hanko revalidation for these browser
    sessions. The endpoint is disabled entirely outside DEBUG mode.
    """
    if not getattr(settings, 'DEBUG', False):
        raise Http404(_('Not found.'))

    email = (request.GET.get('email') or '').strip().lower()
    if not email or '@' not in email or len(email) > 254:
        return JsonResponse({'ok': False, 'error': 'A valid email is required.'}, status=400)

    complete_hanko_login(request, {
        'id': f'e2e-{email}',
        'email': email,
        'name': email.split('@')[0],
        'provider': 'local',
    })
    return redirect(safe_next_url(request, default=reverse('shop-index')))


@ratelimit(key='ip', rate='10/m', method='POST')
def hanko_callback(request: HttpRequest) -> JsonResponse:
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Method not allowed'}, status=405)

    raw_payload: Any
    try:
        raw_payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        raw_payload = {}

    payload: dict[str, Any] = cast(dict[str, Any], raw_payload) if isinstance(raw_payload, dict) else {}
    raw_session_token = payload.get('session_token')
    session_token = raw_session_token.strip() if isinstance(raw_session_token, str) else ''

    if not payload:
        return JsonResponse({'ok': False, 'error': 'Missing user payload'}, status=400)
    if not session_token:
        return JsonResponse({'ok': False, 'error': 'Missing session token'}, status=400)

    try:
        user_data = fetch_hanko_userinfo(session_token)
        user = complete_hanko_login(request, user_data)
    except HankoAuthenticationError:
        return JsonResponse({'ok': False, 'error': 'Invalid Hanko session'}, status=401)

    request.session['hanko_session_token'] = session_token
    request.session.save()

    return JsonResponse({
        'ok': True,
        'user': {
            'id': user.pk,
            'username': user.username,
            'email': user.email,
            'display_name': user.display_name or user.username,
        },
    })


def logout_view(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        logout(request)
        request.session['logged_out'] = True
        messages.success(request, _('Logged out successfully.'))
    return redirect(reverse('shop-login'))


