"""Settings used by the pytest suite.

Extends ``settings.settings`` with two test-only overrides:

* Fast password hashing. Django's default PBKDF2 runs ~1,500,000 iterations,
  which costs seconds per ``create_user`` call and dominates suite runtime.
  No test asserts on hashing behaviour, so tests use MD5.
* A per-process temporary ``MEDIA_ROOT``. Upload tests write real files;
  a unique directory per run (and per xdist worker, via PYTEST_XDIST_WORKER)
  prevents cross-process storage races and keeps the source tree clean.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

from settings.settings import *  # noqa: F401,F403

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

MEDIA_ROOT = Path(
    tempfile.mkdtemp(
        prefix=f'open-car-fleet-media-{os.environ.get("PYTEST_XDIST_WORKER") or "main"}-'
    )
)
atexit.register(shutil.rmtree, MEDIA_ROOT, ignore_errors=True)
