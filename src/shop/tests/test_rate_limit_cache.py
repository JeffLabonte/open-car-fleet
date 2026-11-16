import os
import threading
import uuid
from unittest import skipUnless

from django.test import RequestFactory, SimpleTestCase, override_settings
from django_ratelimit.core import get_usage


class SharedRateLimitCacheTests(SimpleTestCase):
    @skipUnless(os.environ.get("RATELIMIT_REDIS_TEST_URL"), "Redis integration URL is not configured.")
    def test_rate_limit_counts_are_shared_between_worker_cache_clients(self):
        location = os.environ["RATELIMIT_REDIS_TEST_URL"]
        caches = {
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            "ratelimit": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": location,
            },
        }
        group = f"shared-cache-test-{uuid.uuid4()}"
        request = RequestFactory().get("/limited/", REMOTE_ADDR="192.0.2.10")
        results = []

        with override_settings(
            CACHES=caches,
            RATELIMIT_USE_CACHE="ratelimit",
            RATELIMIT_ENABLE=True,
        ):
            first = get_usage(request, group=group, key="ip", rate="1/m", method="GET", increment=True)
            worker = threading.Thread(
                target=lambda: results.append(
                    get_usage(request, group=group, key="ip", rate="1/m", method="GET", increment=True)
                )
            )
            worker.start()
            worker.join()

        self.assertEqual(first["count"], 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["count"], 2)
        self.assertTrue(results[0]["should_limit"])
