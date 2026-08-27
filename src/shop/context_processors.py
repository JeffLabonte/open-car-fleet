from django.http import HttpRequest
from django.conf import settings
from django.utils.translation import get_language


def theme(request: HttpRequest) -> dict:
    cookie_theme = request.COOKIES.get('theme', '').lower()
    theme_value = cookie_theme if cookie_theme in {'light', 'dark'} else 'light'
    return {'theme': theme_value}


def language_info(request: HttpRequest) -> dict:
    """Provide language information to all templates."""
    return {
        'LANGUAGE_CODE': getattr(request, 'LANGUAGE_CODE', None) or get_language() or settings.LANGUAGE_CODE,
        'LANGUAGES': settings.LANGUAGES,
    }
