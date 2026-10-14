from django.http import HttpRequest

VALID_THEMES = {"light", "dark"}
DEFAULT_THEME = "light"


def normalize_theme(theme: object) -> str:
    """Return a valid theme name, falling back to the default."""
    if isinstance(theme, str):
        normalized = theme.lower()
        if normalized in VALID_THEMES:
            return normalized
    return DEFAULT_THEME


def get_theme_from_request(request: HttpRequest) -> str:
    """Read and validate the theme cookie from a request."""
    return normalize_theme(request.COOKIES.get("theme"))
