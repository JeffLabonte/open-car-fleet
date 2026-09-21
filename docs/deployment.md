# Deployment

Ansible-driven deployment for a single remote server. The deployment installs Docker Engine + Compose plugin on the target host, syncs the project source, uploads the production environment file, builds the image on the server, and starts the stack with `docker-compose.prod.yml`.

## Prerequisites

On your local machine:

- Python >= 3.12, Poetry, and Docker for local development (`make install-prereqs` installs these).
- Ansible (`pip install ansible` or your system package manager).
- [Tailscale](https://tailscale.com/download) and an account with access to the server's tailnet.
- SSH access to the remote server (or Tailscale SSH enabled on the server).

On the remote server:

- Ubuntu, Debian, Fedora, RHEL, or a RHEL derivative (Rocky/AlmaLinux/CentOS).
- The Ansible user must have passwordless `sudo` or be root.
- Debian testing/unstable hosts use the `trixie` Docker repository because Docker only publishes packages for stable Debian releases.

## 1) Log into Tailscale

Before touching the remote server, make sure your local machine is on the tailnet:

```bash
tailscale up
```

If you are not already authenticated, this prints a browser link. Open it and log in with your credentials. The deployment targets use Tailscale hostnames/IPs, so Ansible cannot reach the server unless Tailscale is connected.

## 2) Configure your Ansible inventory

A tracked template is provided. Run the helper to create your local, gitignored inventory:

```bash
scripts/setup-ansible-inventory.sh
```

The helper will ask whether you are using Tailscale. If you are, it defaults the hostname prompt to `xps-server.kanyu-bluegill.ts.net` and can optionally use Tailscale SSH (no private key required). It still supports plain IP/hostnames if you answer no.

This creates `ansible/inventory.yml`. Edit it directly if you prefer; it supports one production host by default.

Tailscale example with SSH key over Tailnet:

```yaml
all:
  children:
    production:
      hosts:
        xps-server.kanyu-bluegill.ts.net:
          ansible_user: deploy
          ansible_ssh_private_key_file: ~/.ssh/id_rsa
          ansible_ssh_extra_args: -o StrictHostKeyChecking=no
          app_dir: /opt/open-car-fleet
          env_file: ./src/.env.production
```

Tailscale example with Tailscale SSH (no key):

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

Plain example without Tailscale:

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

## 3) Test connectivity

`make ansible-ping` runs a Tailscale pre-flight check first, then pings the host via Ansible:

```bash
make ansible-ping
```

To check Tailscale connectivity on its own:

```bash
make check-tailscale
```

## 4) Prepare production environment values

Generate a deploy-ready env file:

```bash
scripts/prepare-env.sh \
  --hanko-api-url https://your-hanko-api-url.hanko.io \
  --allowed-hosts "fleet.example.com" \
  --csrf-trusted-origins "https://fleet.example.com"
```

By default this writes `src/.env.production`, generates a strong `DJANGO_SECRET_KEY`, and generates a random `POSTGRES_PASSWORD`.

## 5) Deploy

```bash
make ansible-deploy
```

Like `ansible-ping`, this runs the Tailscale pre-flight check before the playbook.

The playbook performs the following on the remote host:

1. Installs Docker Engine and the Docker Compose plugin.
2. Creates the application directory (`app_dir`).
3. Synchronizes the project source (excluding local artifacts and secrets).
4. Uploads `src/.env.production` as `src/.env`.
5. Builds and starts services with `docker-compose.prod.yml`.
6. Runs Django migrations.
7. Prints the running container status.

## 6) Media persistence

`docker-compose.prod.yml` mounts a named volume `media_volume` at `/app/media`. Uploaded reports, attachments, and other user media persist across deployments. To seed an existing `media/` directory, copy it into the volume manually:

```bash
# Example: copy local media to the server and import it into the volume
rsync -avz ./media/ user@server:/opt/open-car-fleet/media-import/
ssh user@server "cd /opt/open-car-fleet && docker compose -f docker-compose.prod.yml run --rm -v \$(pwd)/media-import:/media-import web cp -r /media-import/. /app/media/"
```

## 7) Production compose file

`docker-compose.prod.yml` differs from the development `docker-compose.yml`:

- The application code comes from the built image, not a host bind mount.
- Postgres is not exposed on the host.
- A named volume persists uploaded media at `/app/media`.

## 8) Legacy SSH deployment

The previous SSH/tar deployment script has been moved to `scripts/deprecated/deploy-ssh.sh` and is no longer the recommended path.

## 9) Future improvement

When you move to a registry-based workflow, the `deploy` role can be updated to pull a prebuilt image instead of building on the server. The current setup intentionally keeps the on-server build so the same source code produces the image locally or in production.
