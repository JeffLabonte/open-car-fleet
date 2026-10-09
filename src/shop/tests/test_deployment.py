import os
import subprocess
import tempfile
from pathlib import Path

from django.test import TestCase


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class TestDeploymentHardening(TestCase):
    """Regression tests for deployment configuration hardening."""

    def test_ansible_cfg_does_not_disable_host_key_checking(self):
        cfg = REPO_ROOT / 'ansible' / 'ansible.cfg'
        self.assertTrue(cfg.exists())
        text = cfg.read_text()
        self.assertNotIn('host_key_checking = False', text)
        self.assertNotIn('StrictHostKeyChecking=no', text)

    def test_inventory_setup_does_not_disable_strict_host_key_checking(self):
        script = REPO_ROOT / 'scripts' / 'setup-ansible-inventory.sh'
        self.assertTrue(script.exists())
        text = script.read_text()
        self.assertNotIn('StrictHostKeyChecking=no', text)

    def test_docker_compose_db_uses_dedicated_database_env_file(self):
        compose = REPO_ROOT / 'docker-compose.prod.yml'
        self.assertTrue(compose.exists())
        text = compose.read_text()
        lines = text.splitlines()
        in_db_service = False
        db_env_file = None
        web_env_file = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('db:'):
                in_db_service = True
            elif stripped.startswith('web:'):
                in_db_service = False
            elif stripped.startswith('- ./src/.env'):
                if in_db_service:
                    db_env_file = stripped
                else:
                    web_env_file = stripped

        self.assertEqual(db_env_file, '- ./src/.env.database')
        self.assertEqual(web_env_file, '- ./src/.env')

    def test_rsync_excludes_ansible_and_env_files(self):
        tasks = REPO_ROOT / 'ansible' / 'roles' / 'app' / 'tasks' / 'main.yml'
        self.assertTrue(tasks.exists())
        text = tasks.read_text()
        self.assertIn("'--exclude=ansible/'", text)
        self.assertIn("'--exclude=.env.*'", text)
        self.assertIn("'--exclude=src/.env.*'", text)

    def test_env_role_derives_database_env_from_deployed_env(self):
        env_role = REPO_ROOT / 'ansible' / 'roles' / 'env' / 'tasks' / 'main.yml'
        self.assertTrue(env_role.exists())
        text = env_role.read_text()
        self.assertIn('src/.env', text)
        self.assertIn('src/.env.database', text)
        self.assertIn("grep -E '^POSTGRES_'", text)

    def test_database_env_file_contains_only_postgres_variables(self):
        db_env = REPO_ROOT / 'src' / '.env.database'
        self.assertTrue(db_env.exists())
        for line in db_env.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            self.assertTrue(
                stripped.startswith('POSTGRES_'),
                f"src/.env.database must only contain POSTGRES_* variables, found: {stripped!r}",
            )

    def test_prepare_env_defaults_set_trusted_proxy(self):
        script = REPO_ROOT / 'scripts' / 'prepare-env.sh'
        self.assertTrue(script.exists())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / '.env.production'
            result = subprocess.run(
                [
                    'bash',
                    str(script),
                    '--output', str(output),
                    '--template', str(REPO_ROOT / 'src' / '.env.template'),
                    '--hanko-api-url', 'https://hanko.example.com',
                    '--allowed-hosts', 'test.example.com',
                    '--csrf-trusted-origins', 'https://test.example.com',
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            content = output.read_text()
            self.assertIn('DJANGO_TRUSTED_PROXY=True', content)
            self.assertIn('SECURE_SSL_REDIRECT=True', content)

    def test_ssl_redirect_without_trusted_proxy_raises(self):
        env = os.environ.copy()
        env['DJANGO_SECRET_KEY'] = 'test-secret-key-for-subprocess'
        env['DEBUG'] = 'False'
        env['SECURE_SSL_REDIRECT'] = 'True'
        env['DJANGO_TRUSTED_PROXY'] = 'False'
        # Clear any postgres vars that might be set by the test runner.
        for key in list(env.keys()):
            if key.startswith('POSTGRES_'):
                del env[key]
        result = subprocess.run(
            [
                'python', '-c',
                'import django; from django.conf import settings; django.setup()',
            ],
            cwd=str(REPO_ROOT / 'src'),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('DJANGO_TRUSTED_PROXY', result.stderr)
