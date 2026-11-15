# Secrets management

The application supports HashiCorp Vault KV v2 with AppRole. The default
`SECRETS_BACKEND=environment` keeps the local `.env` workflow unchanged. Set
`SECRETS_BACKEND=vault` in the production env file to fetch application secrets
at Django startup.

## AppRole and policy

Configure a dedicated AppRole for this deployment. Its policy should allow only
reading the one KV v2 path used by the app; do not grant list, write, or access
to other paths:

```hcl
path "secret/data/open-car-fleet/production" {
  capabilities = ["read"]
}
```

Configure the role for short-lived tokens and a short-lived SecretID. Each
Gunicorn worker authenticates separately, so the SecretID must allow enough
logins for all workers and deployment management commands; do not make it
single-use unless a Vault Agent supplies a per-process token. At startup, the
application sends `VAULT_ROLE_ID` and `VAULT_SECRET_ID` to
`POST /v1/auth/approle/login`, then reads
`GET /v1/<VAULT_KV_MOUNT>/data/<VAULT_SECRET_PATH>` using the returned token.
The token is held only in memory and is not logged or returned to the app
environment.

Configure these values in `src/.env.production`:

```dotenv
SECRETS_BACKEND=vault
VAULT_ADDR=https://vault.example.com
VAULT_ROLE_ID=<deployment-role-id>
VAULT_SECRET_ID=<deployment-secret-id>
VAULT_KV_MOUNT=secret
VAULT_SECRET_PATH=open-car-fleet/production
```

Keep the production env file owner-readable only (mode `0600`); the existing
Ansible env role uploads it with that mode. Never put AppRole credentials in
source control, issue text, shell command arguments, or build arguments. In
Vault, store `DJANGO_SECRET_KEY` and, when email delivery is enabled,
`MAILERSEND_API_TOKEN` as string values at the configured path. The app ignores
unrecognized keys and fails startup with a value-free diagnostic if Vault is
unavailable, denies authentication/read access, or omits `DJANGO_SECRET_KEY`.
Production requires HTTPS for `VAULT_ADDR`.

The Postgres service is started independently by Compose and still uses
`POSTGRES_PASSWORD` from the owner-only deployment env file. Its bootstrap
credential is not currently loaded from Vault; do not remove it from that file
until database startup and rotation are migrated together.

## Rotation and revocation

1. Write the new application secret value to the same KV path and confirm the
   active AppRole can read it.
2. Deploy/restart the web service so all workers load the new values. The
   application reads secrets at process startup; it does not refresh its Vault
   token or values during requests.
3. Rotate the AppRole SecretID through Vault, update the protected production
   env file, deploy again, then revoke the old SecretID. Revoke the AppRole if
   the deployment is decommissioned or its credentials may be exposed.
4. For a database password change, coordinate the Postgres role password and
   `POSTGRES_PASSWORD` env-file update; rotating only one side will interrupt
   database connections.

Vault audit logging should be enabled and reviewed by Vault operators. Restrict
access to the Vault policy, AppRole credentials, and deployment env file to
operators responsible for the service; investigate denied reads and unexpected
authentication attempts. For outages or denied access, verify Vault
availability, the configured address/mount/path, role policy, and credential
rotation. The application intentionally does not print secret values or
provider response bodies in startup errors.

The image build's `collectstatic` command does not contact Vault; it uses the
build-only Django settings already supplied to the image build. Runtime
management commands and web workers do require Vault when the backend is
enabled.

## Deployment verification

Before deploying, verify that:

- The KV v2 path contains a non-empty `DJANGO_SECRET_KEY` and the optional
  `MAILERSEND_API_TOKEN`.
- The AppRole policy grants read access only to the configured path.
- `VAULT_ADDR` uses HTTPS and is reachable from the application host.
- `src/.env.production` contains the current AppRole values and has mode `0600`.
- A deployment with valid credentials starts successfully; missing credentials,
  denied reads, and unavailable Vault fail startup without exposing values.
- After rotation, the web service is restarted and the old SecretID is revoked.
