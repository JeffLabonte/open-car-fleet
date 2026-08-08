from django.http import HttpRequest


def theme(request: HttpRequest) -> dict[str, str]:
    theme_cookie = request.COOKIES.get('theme')
    if theme_cookie in {'light', 'dark'}:
        theme = theme_cookie
    else:
        theme = 'light'

    return {'theme': theme}
