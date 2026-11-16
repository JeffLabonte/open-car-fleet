import os

from settings.test_settings import *  # noqa: F401,F403

DATABASES["default"] = {  # noqa: F405
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ["TEST_POSTGRES_DB"],
    "USER": os.environ["TEST_POSTGRES_USER"],
    "PASSWORD": os.environ["TEST_POSTGRES_PASSWORD"],
    "HOST": os.environ["TEST_POSTGRES_HOST"],
    "PORT": os.environ["TEST_POSTGRES_PORT"],
}
