# Deployment

Ansible-driven deployment for a single remote server. The deployment installs Docker Engine + Compose plugin on the target host, syncs the project source, uploads the production environment file, builds the image on the server, and starts the stack with `docker-compose.prod.yml`.

## Prerequisites

On your local machine:

- Python >= 3.12, Poetry, and Docker for local development (`make install-prereqs` installs these).
- Ansible (`pip install ansible` or your system package manager).
- SSH access to the remote server.

On the remote server:

- Ubuntu, Debian, Fedora, RHEL, or a RHEL derivative (Rocky/AlmaLinux/CentOS).
- The Ansible user must have passwordless `sudo` or be root.

## 1) Configure your Ansible inventory

A tracked template is provided. Run the helper to create your local, gitignored inventory:

```bash
scripts/setup-ansible-inventory.sh
```

This creates `ansible/inventory.yml`. Edit it directly if you prefer; it supports one production host by default.

Example:

```yaml
all:
  children:
    production:
      hosts:
        203.0.113.10:
          ansible_user: deploy
          ansible_ssh_private_key_file: ~/.ssh/id_rsa
          app_dir: /opt/open-car-fleet
          env_file: ./src/.env.production
```

## 2) Test connectivity

```bash
make ansible-ping
```

## 3) Prepare production environment values

Generate a deploy-ready env file:

```bash
scripts/prepare-env.sh \
  --hanko-api-url https://your-hanko-api-url.hanko.io \
  --allowed-hosts "fleet.example.com" \
  --csrf-trusted-origins "https://fleet.example.com"
```

By default this writes `src/.env.production`, generates a strong `DJANGO_SECRET_KEY`, and generates a random `POSTGRES_PASSWORD`.

## 4) Deploy

```bash
make ansible-deploy
```

The playbook performs the following on the remote host:

1. Installs Docker Engine and the Docker Compose plugin.
2. Creates the application directory (`app_dir`).
3. Synchronizes the project source (excluding local artifacts and secrets).
4. Uploads `src/.env.production` as `src/.env`.
5. Builds and starts services with `docker-compose.prod.yml`.
6. Runs Django migrations.
7. Prints the running container status.

## 5) Media persistence

`docker-compose.prod.yml` mounts a named volume `media_volume` at `/app/media`. Uploaded reports, attachments, and other user media persist across deployments. To seed an existing `media/` directory, copy it into the volume manually:

```bash
# Example: copy local media to the server and import it into the volume
rsync -avz ./media/ user@server:/opt/open-car-fleet/media-import/
ssh user@server "cd /opt/open-car-fleet && docker compose -f docker-compose.prod.yml run --rm -v \$(pwd)/media-import:/media-import web cp -r /media-import/. /app/media/"
```

## Production compose file

`docker-compose.prod.yml` differs from the development `docker-compose.yml`:

- The application code comes from the built image, not a host bind mount.
- Postgres is not exposed on the host.
- A named volume persists uploaded media at `/app/media`.

## Legacy SSH deployment

The previous SSH/tar deployment script has been moved to `scripts/deprecated/deploy-ssh.sh` and is no longer the recommended path.

## Future improvement

When you move to a registry-based workflow, the `deploy` role can be updated to pull a prebuilt image instead of building on the server. The current setup intentionally keeps the on-server build so the same source code produces the image locally or in production.
