from django.http import HttpRequest


def theme(request: HttpRequest) -> dict[str, str]:
    cookie_theme = request.COOKIES.get('theme', '').lower()
    theme_value = cookie_theme if cookie_theme in {'light', 'dark'} else 'light'
    return {'theme': theme_value}
