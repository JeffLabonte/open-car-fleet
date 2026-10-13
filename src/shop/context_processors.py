from django.http import HttpRequest
from django.conf import settings
from django.utils.translation import get_language


from shop.theme import get_theme_from_request


def theme(request: HttpRequest) -> dict:
    return {'theme': get_theme_from_request(request)}


def language_info(request: HttpRequest) -> dict:
    """Provide language information to all templates."""
    return {
        'LANGUAGE_CODE': getattr(request, 'LANGUAGE_CODE', None) or get_language() or settings.LANGUAGE_CODE,
        'LANGUAGES': settings.LANGUAGES,
    }
