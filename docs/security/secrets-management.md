# Secrets management

The application reads secrets from the process environment, falling back to
local `.env` files. Production uses the owner-only `src/.env.production` file,
which Ansible uploads as `src/.env` with mode `0600`. The file is never copied
into the image or committed to source control.

## Required production values

Set these values in `src/.env.production` before deploying:

```dotenv
DJANGO_SECRET_KEY=<long-random-django-secret>
MAILERSEND_API_TOKEN=<optional-mailersend-token>
```

`DJANGO_SECRET_KEY` must be non-empty and must not use a development
placeholder. `MAILERSEND_API_TOKEN` is required only when email delivery is
enabled. The Postgres service remains separate and receives only the
`POSTGRES_*` values from the derived `src/.env.database` file.

Keep both environment files owner-readable only. Never put secrets in source
control, issue text, shell command arguments, Docker build arguments, or shared
logs. Restrict server and Docker access to operators who are authorized to
read the deployment secrets.

## Rotation

1. Generate a new secret value using an authorized operator workflow and update
   the protected production env file.
2. Deploy or restart the web service so all workers load the new value.
   Rotating `DJANGO_SECRET_KEY` invalidates existing sessions and signed values
   unless a Django key rollover is separately planned.
3. For MailerSend rotation, create the replacement token with the minimum
   required permissions, deploy it, verify delivery, then revoke the old token.
4. For a database password change, coordinate the Postgres role password and
   `POSTGRES_PASSWORD` env-file update; rotating only one side interrupts
   database connections.

## Deployment verification

Before deploying, verify that:

- `DJANGO_SECRET_KEY` is non-empty, random, and not a development placeholder.
- `src/.env.production` has mode `0600` and contains no committed or logged
  copies of its values.
- `DEBUG=False` and the expected HTTPS and trusted-proxy settings are enabled.
- The database env file contains only `POSTGRES_*` variables.
- Migrations complete and the web service responds; verify email delivery when
  configured without displaying the token.
- After rotation, the old application or MailerSend credentials are revoked
  where applicable.

The image build uses a temporary build-only Django secret for `collectstatic`;
it does not read or require the production env file.
