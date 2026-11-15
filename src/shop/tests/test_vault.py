from unittest.mock import Mock, patch

import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from settings.vault import load_vault_secrets


class VaultAppRoleTests(SimpleTestCase):
    def setUp(self):
        self.config = {
            "address": "https://vault.example.com",
            "role_id": "role-id",
            "secret_id": "secret-id",
            "mount": "secret",
            "secret_path": "open-car-fleet/production",
            "require_tls": True,
        }

    def test_requires_approle_credentials(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "VAULT_ADDR, VAULT_ROLE_ID, and VAULT_SECRET_ID"):
            load_vault_secrets(**{**self.config, "secret_id": ""})

    def test_requires_tls_when_configured_for_production(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "valid HTTPS URL"):
            load_vault_secrets(**{**self.config, "address": "http://vault.example.com"})

    @patch("settings.vault.requests.post")
    def test_rejects_denied_approle_authentication_without_leaking_response(self, post):
        post.return_value = Mock(status_code=403, text="sensitive denial detail")

        with self.assertRaisesMessage(ImproperlyConfigured, "Vault AppRole authentication failed (HTTP 403)"):
            load_vault_secrets(**self.config)

    @patch("settings.vault.requests.post", side_effect=requests.ConnectionError("network down"))
    def test_fails_with_safe_diagnostic_when_vault_is_unavailable(self, _post):
        with self.assertRaisesMessage(ImproperlyConfigured, "Unable to reach Vault for AppRole authentication"):
            load_vault_secrets(**self.config)

    @patch("settings.vault.requests.get")
    @patch("settings.vault.requests.post")
    def test_loads_only_allowlisted_secrets_from_kv_v2(self, post, get):
        post.return_value = Mock(status_code=200, json=lambda: {"auth": {"client_token": "vault-token"}})
        get.return_value = Mock(
            status_code=200,
            json=lambda: {
                "data": {
                    "data": {
                        "DJANGO_SECRET_KEY": "production-key",
                        "MAILERSEND_API_TOKEN": "mail-token",
                        "UNEXPECTED_SETTING": "ignored",
                    },
                },
            },
        )

        secrets = load_vault_secrets(**self.config)

        self.assertEqual(
            secrets,
            {
                "DJANGO_SECRET_KEY": "production-key",
                "MAILERSEND_API_TOKEN": "mail-token",
            },
        )
        post.assert_called_once_with(
            "https://vault.example.com/v1/auth/approle/login",
            json={"role_id": "role-id", "secret_id": "secret-id"},
            timeout=5,
            allow_redirects=False,
        )
        get.assert_called_once_with(
            "https://vault.example.com/v1/secret/data/open-car-fleet/production",
            headers={"X-Vault-Token": "vault-token"},
            timeout=5,
            allow_redirects=False,
        )
        self.assertEqual(secrets["MAILERSEND_API_TOKEN"], "mail-token")

    @patch("settings.vault.requests.get")
    @patch("settings.vault.requests.post")
    def test_fails_when_vault_denies_secret_read(self, post, get):
        post.return_value = Mock(status_code=200, json=lambda: {"auth": {"client_token": "vault-token"}})
        get.return_value = Mock(status_code=403, text="sensitive denial detail")

        with self.assertRaisesMessage(ImproperlyConfigured, "Vault secret retrieval failed (HTTP 403)"):
            load_vault_secrets(**self.config)

    @patch("settings.vault.requests.get", side_effect=requests.Timeout("timed out"))
    @patch("settings.vault.requests.post")
    def test_fails_safely_when_secret_read_times_out(self, post, _get):
        post.return_value = Mock(status_code=200, json=lambda: {"auth": {"client_token": "vault-token"}})

        with self.assertRaisesMessage(ImproperlyConfigured, "Unable to retrieve application secrets from Vault"):
            load_vault_secrets(**self.config)

    @patch("settings.vault.requests.get")
    @patch("settings.vault.requests.post")
    def test_requires_django_secret_key(self, post, get):
        post.return_value = Mock(status_code=200, json=lambda: {"auth": {"client_token": "vault-token"}})
        get.return_value = Mock(status_code=200, json=lambda: {"data": {"data": {"MAILERSEND_API_TOKEN": "token"}}})

        with self.assertRaisesMessage(ImproperlyConfigured, "missing the required DJANGO_SECRET_KEY"):
            load_vault_secrets(**self.config)
