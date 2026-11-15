from urllib.parse import quote, urlparse

import requests
from django.core.exceptions import ImproperlyConfigured

VAULT_SECRET_KEYS = frozenset({"DJANGO_SECRET_KEY", "MAILERSEND_API_TOKEN"})


def load_vault_secrets(
    *,
    address: str,
    role_id: str,
    secret_id: str,
    mount: str,
    secret_path: str,
    require_tls: bool,
) -> dict[str, str]:
    """Authenticate with Vault AppRole and read an allowlisted KV v2 secret map."""
    if not address or not role_id or not secret_id:
        raise ImproperlyConfigured("Vault backend requires VAULT_ADDR, VAULT_ROLE_ID, and VAULT_SECRET_ID.")

    parsed_address = urlparse(address)
    allowed_schemes = {"https"} if require_tls else {"http", "https"}
    if (
        parsed_address.scheme not in allowed_schemes
        or not parsed_address.netloc
        or parsed_address.username
        or parsed_address.password
        or parsed_address.query
        or parsed_address.fragment
    ):
        requirement = "HTTPS" if require_tls else "HTTP or HTTPS"
        raise ImproperlyConfigured(f"VAULT_ADDR must be a valid {requirement} URL.")

    mount = mount.strip("/")
    secret_path = secret_path.strip("/")
    if (
        not mount
        or not secret_path
        or any(part in {"", ".", ".."} for part in mount.split("/"))
        or any(part in {"", ".", ".."} for part in secret_path.split("/"))
    ):
        raise ImproperlyConfigured("VAULT_KV_MOUNT and VAULT_SECRET_PATH must be configured.")

    base_url = address.rstrip("/")
    try:
        login_response = requests.post(
            f"{base_url}/v1/auth/approle/login",
            json={"role_id": role_id, "secret_id": secret_id},
            timeout=5,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise ImproperlyConfigured("Unable to reach Vault for AppRole authentication.") from None
    if login_response.status_code != 200:
        raise ImproperlyConfigured(f"Vault AppRole authentication failed (HTTP {login_response.status_code}).")

    try:
        login_data = login_response.json()
    except ValueError:
        raise ImproperlyConfigured("Vault returned an invalid AppRole response.") from None
    auth_data = login_data.get("auth") if isinstance(login_data, dict) else None
    token = auth_data.get("client_token") if isinstance(auth_data, dict) else None
    if not isinstance(token, str) or not token:
        raise ImproperlyConfigured("Vault AppRole response did not contain a client token.")

    endpoint = f"{base_url}/v1/{quote(mount, safe='/')}/data/{quote(secret_path, safe='/')}"
    try:
        secret_response = requests.get(
            endpoint,
            headers={"X-Vault-Token": token},
            timeout=5,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise ImproperlyConfigured("Unable to retrieve application secrets from Vault.") from None
    if secret_response.status_code != 200:
        raise ImproperlyConfigured(f"Vault secret retrieval failed (HTTP {secret_response.status_code}).")

    try:
        response_data = secret_response.json()
        values = response_data["data"]["data"]
    except (ValueError, KeyError, TypeError):
        raise ImproperlyConfigured("Vault returned an invalid KV v2 secret response.") from None

    if not isinstance(values, dict):
        raise ImproperlyConfigured("Vault KV v2 secret data must be an object.")

    secrets = {
        key: value
        for key, value in values.items()
        if key in VAULT_SECRET_KEYS and isinstance(value, str) and value
    }
    for key in VAULT_SECRET_KEYS:
        secrets.setdefault(key, "")
    if not secrets.get("DJANGO_SECRET_KEY"):
        raise ImproperlyConfigured("Vault secret is missing the required DJANGO_SECRET_KEY.")
    return secrets
