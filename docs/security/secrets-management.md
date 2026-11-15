# Secrets management

The application supports HashiCorp Vault KV v2 with AppRole. The default
`SECRETS_BACKEND=environment` keeps the local `.env` workflow unchanged.
Production preparation sets `SECRETS_BACKEND=vault`, and Ansible requires it
and `DEBUG=False`, so Django fetches application secrets at startup.

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

Keep the production env file owner-readable only (mode `0600`); the Ansible
env role uploads it with that mode without logging its contents. Never put AppRole credentials in
source control, issue text, shell command arguments, or build arguments. In
Vault, store `DJANGO_SECRET_KEY` and, when email delivery is enabled,
`MAILERSEND_API_TOKEN` as string values at the configured path. The app ignores
unrecognized keys and fails startup with a value-free diagnostic if Vault is
unavailable, denies authentication/read access, or omits `DJANGO_SECRET_KEY`.
An absent MailerSend token becomes empty, never an environment fallback.
Production requires HTTPS for `VAULT_ADDR` with a certificate trusted by the
container. Compose injects AppRole credentials into the web container's
environment: host administrators and users with Docker access can inspect
them, so restrict both. The image build receives no production env file.

The Postgres service is started independently by Compose and still uses
`POSTGRES_PASSWORD` from the owner-only deployment env file. Its bootstrap
credential is not currently loaded from Vault; do not remove it from that file
until database startup and rotation are migrated together.

## Rotation and revocation

1. Write the new application secret value to the same KV path using an
   authorized operator workflow and confirm the active AppRole can read it
   without printing it to shared logs. Rotating `DJANGO_SECRET_KEY` invalidates
   existing sessions and signed values unless an appropriate Django key
   rollover is separately planned.
2. Deploy/restart the web service so all workers load the new values. The
   application reads secrets at process startup; it does not refresh its Vault
   token or values during requests.
3. Generate a new SecretID through Vault, update the protected production
   env file, deploy again, then destroy the old SecretID using its accessor
   and revoke outstanding tokens where needed. For suspected compromise,
   revoke affected credentials and tokens immediately, then issue replacements.
   Remove the role and policy when decommissioning.
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

The image build's `collectstatic` command explicitly uses build-only environment
settings and does not contact Vault. All runtime management commands, including
`collectstatic`, and web workers require Vault when the backend is enabled.
Existing processes retain their loaded secrets during an outage, but a new or
restarted process fails closed rather than using environment-file secrets.
Restore Vault access before restarting, scaling, or running migrations.

## Deployment verification

Before deploying, verify that:

- The KV v2 path contains a non-empty `DJANGO_SECRET_KEY` and the optional
  `MAILERSEND_API_TOKEN`.
- The AppRole policy grants read access only to the configured path.
- `VAULT_ADDR` uses HTTPS and is reachable from the application host.
- `src/.env.production` contains the current AppRole values, `DEBUG=False`,
  and `SECRETS_BACKEND=vault`, has mode `0600`, and contains no Django key or
  MailerSend token.
- A deployment with valid credentials starts successfully; missing credentials,
  denied reads, and unavailable Vault fail startup without exposing values.
- Migrations complete and the web service responds; verify email delivery when
  configured without displaying the token. Check restricted Vault audit logs
  for expected AppRole logins and reads.
- The database bootstrap password is protected and matches the existing
  Postgres role; an env-file change alone does not rotate that role.
- After rotation, the web service is restarted and the old SecretID is revoked.
