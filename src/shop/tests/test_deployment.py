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
