from django.http import HttpRequest


def theme(request: HttpRequest) -> dict[str, str]:
    return {'theme': 'dark'}
