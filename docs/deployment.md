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
          ansible_ssh_extra_args: -o StrictHostKeyChecking=no
          app_dir: /opt/open-car-fleet
          env_file: ./src/.env.production
```

## 3. Prepare environment values

```bash
scripts/prepare-env.sh \
  --hanko-api-url https://your-hanko-api-url.hanko.io \
  --allowed-hosts "fleet.example.com" \
  --csrf-trusted-origins "https://fleet.example.com"
```

This writes `src/.env.production` with a generated secret key and Postgres password.

## 4. Test connectivity

```bash
make ansible-ping
```

## 5. Deploy

```bash
make ansible-deploy
```

The playbook installs Docker, syncs the project source, uploads the env file, builds the production image, starts services, runs migrations, fixes media ownership, and configures hourly backups.

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
