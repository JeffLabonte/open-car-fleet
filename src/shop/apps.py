from django.apps import AppConfig


class ShopConfig(AppConfig):
    name = "shop"

    def ready(self) -> None:
        from shop import activity_signals  # noqa: F401
