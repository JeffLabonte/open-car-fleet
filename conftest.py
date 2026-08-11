import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'src'

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ['POSTGRES_DB'] = ''
os.environ.pop('POSTGRES_USER', None)
os.environ.pop('POSTGRES_PASSWORD', None)
os.environ.pop('POSTGRES_HOST', None)
os.environ.pop('POSTGRES_PORT', None)
os.environ.setdefault('DJANGO_ALLOWED_HOSTS', 'testserver localhost 127.0.0.1 [::1]')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings.settings')

import django
from django.test.utils import setup_test_environment

django.setup()
setup_test_environment()


def pytest_sessionstart(session):
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=0)
    session._django_db_config = runner.setup_databases()
    session._django_runner = runner


def pytest_sessionfinish(session, exitstatus):
    if hasattr(session, '_django_db_config'):
        session._django_runner.teardown_databases(session._django_db_config)
