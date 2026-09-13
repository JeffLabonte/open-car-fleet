# Deployment

SSH + Docker deployment for a single remote server.

This repository includes simple deployment scripts:

- `scripts/prepare-env.sh`: prepares a production env file from `src/.env.template`.
- `scripts/deploy-ssh.sh`: uploads the project over SSH and deploys it with Docker Compose.

## Prerequisites

- Local machine: `bash`, `python`, `ssh`, `tar`.
- Remote server: Docker Engine + Docker Compose plugin.
- SSH access to the remote machine.

## 1) Prepare production env values

Generate a deploy-ready file:

```bash
scripts/prepare-env.sh \
  --hanko-api-url https://your-hanko-api-url.hanko.io \
  --allowed-hosts "fleet.example.com" \
  --csrf-trusted-origins "https://fleet.example.com"
```

By default this writes `src/.env.production`, generates a strong `DJANGO_SECRET_KEY`, and generates a random `POSTGRES_PASSWORD`.

## 2) Deploy over SSH

```bash
scripts/deploy-ssh.sh \
  --host user@your-server \
  --env-file /absolute/path/to/src/.env.production \
  --remote-dir /opt/open-car-fleet
```

The deploy script uploads sources, uploads env values as `src/.env` on the server, runs `docker compose up -d --build`, applies migrations, and prints service status.

## Ideas, pros and cons

**Current approach (included scripts):**
- Pros: very simple, no CI dependency, no registry required, easy to run manually.
- Cons: uploads full source every deploy, slower than prebuilt image deploys, relies on direct SSH access.

**Alternative approach (future improvement):**
- Build/push Docker images in CI and deploy by pulling versioned images on the server.
- Pros: faster, reproducible image artifacts, easier rollback with image tags.
- Cons: requires registry setup, CI/CD pipeline management, and secret management in CI.
