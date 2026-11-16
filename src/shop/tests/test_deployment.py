import os
import subprocess
import tempfile
from pathlib import Path

from django.test import TestCase

from settings.settings import load_environment_files

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class TestDeploymentHardening(TestCase):
    """Regression tests for deployment configuration hardening."""

    def test_environment_file_precedence_keeps_the_first_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / ".env"
            fallback = Path(tmp) / ".env.template"
            primary.write_text("SHARED=from-primary\nPRIMARY_ONLY=yes\n")
            fallback.write_text("SHARED=from-fallback\nFALLBACK_ONLY=yes\n")

            values = load_environment_files([primary, fallback])

        self.assertEqual(values["SHARED"], "from-primary")
        self.assertEqual(values["PRIMARY_ONLY"], "yes")
        self.assertEqual(values["FALLBACK_ONLY"], "yes")

    def test_make_run_uses_local_development_security_settings(self):
        makefile = REPO_ROOT / "Makefile"
        text = makefile.read_text()

        self.assertIn("DEV_DJANGO_ENV = DEBUG=True SECURE_SSL_REDIRECT=False", text)
        self.assertIn("$(DEV_DJANGO_ENV) $(PYTHON) src/manage.py migrate", text)
        self.assertIn("$(DEV_DJANGO_ENV) $(PYTHON) src/manage.py runserver", text)

    def test_production_requires_rate_limit_cache_url(self):
        env = os.environ.copy()
        env.update(
            {
                "DEBUG": "False",
                "DJANGO_SECRET_KEY": "test-production-cache-key",
                "RATELIMIT_CACHE_URL": "",
                "SECURE_SSL_REDIRECT": "False",
            }
        )
        result = subprocess.run(
            ["python", "-c", "import settings.settings"],
            cwd=str(REPO_ROOT / "src"),
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("RATELIMIT_CACHE_URL must be set", result.stderr)

    def test_production_uses_shared_redis_cache_and_fails_closed(self):
        env = os.environ.copy()
        env.update(
            {
                "DEBUG": "False",
                "DJANGO_SECRET_KEY": "test-production-cache-key",
                "RATELIMIT_CACHE_URL": "redis://cache:6379/0",
                "SECURE_SSL_REDIRECT": "False",
            }
        )
        result = subprocess.run(
            [
                "python",
                "-c",
                (
                    "from settings.settings import CACHES, RATELIMIT_FAIL_OPEN, RATELIMIT_USE_CACHE; "
                    "assert CACHES['ratelimit']['BACKEND'] == "
                    "'django.core.cache.backends.redis.RedisCache'; "
                    "assert CACHES['ratelimit']['LOCATION'] == 'redis://cache:6379/0'; "
                    "assert RATELIMIT_USE_CACHE == 'ratelimit'; "
                    "assert RATELIMIT_FAIL_OPEN is False"
                ),
            ],
            cwd=str(REPO_ROOT / "src"),
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_development_uses_local_cache_without_redis_url(self):
        env = os.environ.copy()
        env.update(
            {
                "DEBUG": "True",
                "DJANGO_SECRET_KEY": "test-development-cache-key",
                "RATELIMIT_CACHE_URL": "",
            }
        )
        result = subprocess.run(
            [
                "python",
                "-c",
                (
                    "from settings.settings import CACHES; "
                    "assert CACHES['ratelimit']['BACKEND'] == "
                    "'django.core.cache.backends.locmem.LocMemCache'"
                ),
            ],
            cwd=str(REPO_ROOT / "src"),
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ansible_cfg_does_not_disable_host_key_checking(self):
        cfg = REPO_ROOT / "ansible" / "ansible.cfg"
        self.assertTrue(cfg.exists())
        text = cfg.read_text()
        self.assertNotIn("host_key_checking = False", text)
        self.assertNotIn("StrictHostKeyChecking=no", text)

    def test_inventory_setup_does_not_disable_strict_host_key_checking(self):
        script = REPO_ROOT / "scripts" / "setup-ansible-inventory.sh"
        self.assertTrue(script.exists())
        text = script.read_text()
        self.assertNotIn("StrictHostKeyChecking=no", text)

    def test_docker_compose_db_uses_dedicated_database_env_file(self):
        compose = REPO_ROOT / "docker-compose.prod.yml"
        self.assertTrue(compose.exists())
        text = compose.read_text()
        lines = text.splitlines()
        in_db_service = False
        db_env_file = None
        web_env_file = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("db:"):
                in_db_service = True
            elif stripped.startswith("web:"):
                in_db_service = False
            elif stripped.startswith("- ./src/.env"):
                if in_db_service:
                    db_env_file = stripped
                else:
                    web_env_file = stripped

        self.assertEqual(db_env_file, "- ./src/.env.database")
        self.assertEqual(web_env_file, "- ./src/.env")

    def test_rsync_excludes_ansible_and_env_files(self):
        tasks = REPO_ROOT / "ansible" / "roles" / "app" / "tasks" / "main.yml"
        self.assertTrue(tasks.exists())
        text = tasks.read_text()
        # Excludes must be anchored to the project root so nested app directories
        # (e.g. src/shop/static/shop/js/) are not accidentally skipped.
        self.assertIn("'--exclude=/ansible/'", text)
        self.assertIn("'--exclude=/.env.*'", text)
        self.assertIn("'--exclude=/src/.env.*'", text)
        self.assertNotIn("'--exclude=static/'", text)
        self.assertNotIn("'--exclude=media/'", text)
        self.assertIn("'--exclude=/static/'", text)
        self.assertIn("'--exclude=/media/'", text)

    def test_env_role_derives_database_env_from_deployed_env(self):
        env_role = REPO_ROOT / "ansible" / "roles" / "env" / "tasks" / "main.yml"
        self.assertTrue(env_role.exists())
        text = env_role.read_text()
        self.assertIn("src/.env", text)
        self.assertIn("src/.env.database", text)
        self.assertIn("grep -E '^POSTGRES_'", text)

    def test_production_env_is_validated_on_controller_before_sync_and_upload(self):
        playbook = (REPO_ROOT / "ansible" / "playbook.yml").read_text()
        env_role = (REPO_ROOT / "ansible" / "roles" / "env" / "tasks" / "main.yml").read_text()

        self.assertLess(playbook.index("    - env"), playbook.index("    - app"))
        upload_index = env_role.index("- name: Upload production env file to server")
        for check in (
            "- name: Require Django secret key for production deployment",
            "- name: Require DEBUG=False for production deployment",
        ):
            check_index = env_role.index(check)
            task_end = env_role.find("\n- name:", check_index + 1)
            if task_end == -1:
                task_end = len(env_role)
            self.assertLess(check_index, upload_index)
            self.assertIn("delegate_to: localhost", env_role[check_index:task_end])

    def test_database_env_file_contains_only_postgres_variables(self):
        db_env = REPO_ROOT / "src" / ".env.database"
        if not db_env.exists():
            self.skipTest("src/.env.database is generated during deployment and is not checked in.")
        for line in db_env.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            self.assertTrue(
                stripped.startswith("POSTGRES_"),
                f"src/.env.database must only contain POSTGRES_* variables, found: {stripped!r}",
            )

    def test_prepare_env_defaults_set_trusted_proxy(self):
        script = REPO_ROOT / "scripts" / "prepare-env.sh"
        self.assertTrue(script.exists())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / ".env.production"
            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    "--output",
                    str(output),
                    "--template",
                    str(REPO_ROOT / "src" / ".env.template"),
                    "--hanko-api-url",
                    "https://hanko.example.com",
                    "--allowed-hosts",
                    "test.example.com",
                    "--csrf-trusted-origins",
                    "https://test.example.com",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            content = output.read_text()
            self.assertIn("DJANGO_TRUSTED_PROXY=True", content)
            self.assertIn("SECURE_SSL_REDIRECT=True", content)
            self.assertIn("DJANGO_SECRET_KEY=\n", content)
            self.assertIn("MAILERSEND_API_TOKEN=\n", content)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_prepare_env_replaces_duplicate_production_assignments(self):
        script = REPO_ROOT / "scripts" / "prepare-env.sh"
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / ".env.template"
            template.write_text(
                "DEBUG=True\n"
                "DEBUG=True\n"
                "DJANGO_SECRET_KEY=first-secret\n"
                "DJANGO_SECRET_KEY=second-secret\n"
                "MAILERSEND_API_TOKEN=first-token\n"
                "MAILERSEND_API_TOKEN=second-token\n"
            )
            output = Path(tmp) / ".env.production"
            result = subprocess.run(
                ["bash", str(script), "--output", str(output), "--template", str(template)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            content = output.read_text()

        self.assertEqual(content.count("DEBUG=False\n"), 2)
        self.assertEqual(content.count("DJANGO_SECRET_KEY=\n"), 2)
        self.assertEqual(content.count("MAILERSEND_API_TOKEN=\n"), 2)
        self.assertNotIn("first-secret", content)
        self.assertNotIn("second-secret", content)
        self.assertNotIn("first-token", content)
        self.assertNotIn("second-token", content)

    def test_production_deploy_requires_secret_key_and_build_excludes_credentials(self):
        env_role = (REPO_ROOT / "ansible" / "roles" / "env" / "tasks" / "main.yml").read_text()
        dockerfile = (REPO_ROOT / "Dockerfile").read_text()
        compose = (REPO_ROOT / "docker-compose.prod.yml").read_text()
        self.assertIn("Require Django secret key for production deployment", env_role)
        self.assertIn('exit value == ""', env_role)
        self.assertIn("no_log: true", env_role)
        self.assertNotIn("SECRETS_BACKEND", dockerfile)
        self.assertNotIn("--mount=type=secret", dockerfile)
        self.assertNotIn("env_file:\n    file:", compose)

    def test_security_logger_uses_console_locally_and_syslog_in_production(self):
        from settings.settings import DEBUG, LOGGING

        self.assertTrue(DEBUG)
        self.assertEqual(LOGGING["loggers"]["security"]["handlers"], ["security_console"])
        self.assertNotIn("security_syslog", LOGGING["handlers"])

        env = os.environ.copy()
        env.update(
            {
                "DEBUG": "False",
                "DJANGO_SECRET_KEY": "test-production-logging-key",
                "RATELIMIT_CACHE_URL": "redis://cache:6379/0",
                "SECURE_SSL_REDIRECT": "False",
            }
        )
        result = subprocess.run(
            [
                "python",
                "-c",
                (
                    "from settings.settings import LOGGING; "
                    "logger = LOGGING['loggers']['security']; "
                    "handler = LOGGING['handlers']['security_syslog']; "
                    "assert logger['handlers'] == ['security_syslog']; "
                    "assert handler['class'] == 'settings.settings.SecuritySysLogHandler'; "
                    "assert handler['address'] == '/dev/log'; "
                    "assert handler['facility'] == 'local0'"
                ),
            ],
            cwd=str(REPO_ROOT / "src"),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_audit_logs_use_persistent_restricted_journald(self):
        compose = (REPO_ROOT / "docker-compose.prod.yml").read_text()
        deploy = (REPO_ROOT / "ansible" / "roles" / "deploy" / "tasks" / "main.yml").read_text()
        audit_docs = (REPO_ROOT / "docs" / "security" / "audit-logging.md").read_text()

        self.assertIn("- /dev/log:/dev/log", compose)
        self.assertIn("Storage=persistent", deploy)
        self.assertIn("MaxRetentionSec=90day", deploy)
        self.assertIn("SystemMaxUse=2G", deploy)
        self.assertIn("systemd-journal", deploy)
        self.assertIn("mode: '2750'", deploy)
        self.assertIn("mode: '0700'", deploy)
        self.assertIn("mode: '0600'", deploy)
        self.assertIn("Review security events at least daily", audit_docs)

    def test_ssl_redirect_without_trusted_proxy_raises(self):
        env = os.environ.copy()
        env["DJANGO_SECRET_KEY"] = "test-secret-key-for-subprocess"
        env["DEBUG"] = "False"
        env["SECURE_SSL_REDIRECT"] = "True"
        env["DJANGO_TRUSTED_PROXY"] = "False"
        # Clear any postgres vars that might be set by the test runner.
        for key in list(env.keys()):
            if key.startswith("POSTGRES_"):
                del env[key]
        result = subprocess.run(
            [
                "python",
                "-c",
                "import django; from django.conf import settings; django.setup()",
            ],
            cwd=str(REPO_ROOT / "src"),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("DJANGO_TRUSTED_PROXY", result.stderr)

    def test_environment_file_loads_production_secrets(self):
        env = os.environ.copy()
        env.update(
            {
                "DEBUG": "False",
                "DJANGO_SECRET_KEY": "environment-key",
                "MAILERSEND_API_TOKEN": "mail-token",
                "SECURE_SSL_REDIRECT": "False",
            }
        )
        script = """
import settings.settings as configured
assert configured.SECRET_KEY == "environment-key"
assert configured.MAILERS["default"]["OPTIONS"]["api_token"] == "mail-token"
"""
        result = subprocess.run(
            ["python", "-c", script],
            cwd=str(REPO_ROOT / "src"),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_collectstatic_uses_environment_secret(self):
        env = os.environ.copy()
        env.update(
            {
                "DEBUG": "False",
                "DJANGO_SECRET_KEY": "build-only-secret",
                "SECURE_SSL_REDIRECT": "False",
            }
        )

        result = subprocess.run(
            [
                "python",
                "-c",
                "import settings.settings; assert settings.settings.SECRET_KEY == 'build-only-secret'",
            ],
            cwd=str(REPO_ROOT / "src"),
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
