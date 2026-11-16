# Deployment

Ansible-driven deployment for a single remote server over Tailscale.

## Prerequisites

Local machine:

- Python >= 3.12, Poetry, Docker (`make install-prereqs`)
- Ansible
- Tailscale client and tailnet access

Remote server:

- Ubuntu, Debian, Fedora, RHEL, or a RHEL derivative
- Passwordless `sudo` for the Ansible user

## 1. Connect to Tailscale

```bash
tailscale up
```

## 2. Configure inventory

```bash
scripts/setup-ansible-inventory.sh
```

This creates the gitignored `ansible/inventory.yml`. Edit it directly if needed:

```yaml
all:
  children:
    production:
      hosts:
        xps-server.kanyu-bluegill.ts.net:
          ansible_user: deploy
          app_dir: /opt/open-car-fleet
          env_file: ./src/.env.production
```

> **SSH host-key verification:** Tailscale authenticates network membership, but it is not a substitute for SSH host-key verification. Ensure the deployment host's key is present in your `~/.ssh/known_hosts`, use an SSH CA, or pin fingerprints in the inventory. Do not disable `StrictHostKeyChecking`.

## 3. Prepare environment values

```bash
scripts/prepare-env.sh \
  --hanko-api-url https://your-hanko-api-url.hanko.io \
  --allowed-hosts "fleet.example.com" \
  --csrf-trusted-origins "https://fleet.example.com"
```

This writes `src/.env.production` with a generated Postgres password,
`DJANGO_TRUSTED_PROXY=True`, and blank application secret fields. Django trusts
the `X-Forwarded-Proto` header from Tailscale (or another reverse proxy).
During deploy, Ansible derives `src/.env.database` from this file on the
server, so the DB container receives only `POSTGRES_*` variables and stays in
sync with the web container.

Using a secure editor, set a strong `DJANGO_SECRET_KEY` and, when email delivery
is enabled, `MAILERSEND_API_TOKEN` in the generated env file. The Ansible env
role requires `DJANGO_SECRET_KEY` and `DEBUG=False`, uploads the file with mode
`0600`, and Compose passes the environment file to the web service. Never
commit the production env file or expose its values in command arguments or
logs. See [Secrets management](security/secrets-management.md) for the
required values, rotation procedure, and verification checklist.

## 4. Test connectivity

```bash
make ansible-ping
```

## 5. Deploy

```bash
make ansible-deploy
```

The playbook installs Docker, syncs the project source, uploads the env file, builds the production image, starts services, runs migrations, fixes media ownership, and configures hourly backups.

> **Database secrets:** `docker-compose.prod.yml` mounts a dedicated `src/.env.database` file into the Postgres container. Ansible generates this file on the server from `src/.env` during deploy, so it contains only `POSTGRES_*` variables and the password always matches the web container.
>
> **Reverse proxy:** Production deploys are behind Tailscale HTTPS. `prepare-env.sh` sets `DJANGO_TRUSTED_PROXY=True` by default so Django trusts `X-Forwarded-Proto` and `SECURE_SSL_REDIRECT` does not create a redirect loop. If you disable the proxy, set `DJANGO_TRUSTED_PROXY=False` and `SECURE_SSL_REDIRECT=False`.

## Rate-limit cache and staged uploads

Production Compose runs a Redis cache shared by all Gunicorn workers and sets
`RATELIMIT_CACHE_URL=redis://cache:6379/0`. If you use an external Redis
service, update that value in `docker-compose.prod.yml`. With `DEBUG=False`,
Django refuses to start when `RATELIMIT_CACHE_URL` is missing; if Redis becomes
unavailable, rate-limited requests fail closed rather than bypassing limits.
Development and tests use a local-memory cache.

Staged uploads are subject to a per-user size quota. On PostgreSQL, each
upload checks the user's unclaimed staged files and saves the new file in one
transaction while locking that user's row, so concurrent uploads by the same
user cannot both pass the quota check.

Ansible schedules `purge_staged_attachments` hourly through the running web
container. It removes unclaimed uploads after the 12-hour retention window;
upload requests do not scan or purge the global staged-file set.

## Media

Uploaded files live in a Docker named volume mounted at `/app/src/media`. During deploy, any existing `src/media/` directory on the host is archived into `/opt/backups/media` and copied into the container volume.

## Backups

Hourly cron jobs back up media and the Postgres database to `/opt/backups/{media,database}`. A new snapshot is created only when the content has changed (sha512 comparison). The 10 most recent snapshots are kept.

Run backups manually:

```bash
make backup          # both
make backup-media
make backup-database
```

Snapshot names:

- Media: `snapshot-YYYYMMDD-HHMMSS.tar.gz`
- Database: `snapshot-YYYYMMDD-HHMMSS.sql.gz`

## Registry-based deploys (future)

When you move to a registry workflow, update the `deploy` role to pull a prebuilt image instead of building on the server.
