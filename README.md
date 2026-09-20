![Open Car Fleet logo](src/public/logo.png)

# Open Car Fleet

Open Car Fleet is an open-source Django 6 application for automotive maintenance management.
It helps individuals and shared garages organize vehicles, plan maintenance work, and record completed service reports in one place.

## Project description

- Manage garages and memberships with role-based access.
- Track cars with key identity and maintenance context.
- Plan and assign work jobs to mechanics or known shops.
- Record maintenance reports with dates, mileage, notes, and attachments.
- Import normalized CSV datasets and export garage backups to Excel.

## Quick start

On a fresh machine, install the prerequisites once (Python >= 3.12, Poetry, Docker):

```bash
make install-prereqs   # macOS (Homebrew), Linux (apt/dnf/pacman), or WSL
```

Then install project dependencies and run the app:

```bash
make install   # poetry install --no-root --with test
make run       # starts Postgres (docker compose), migrates, runs the dev server
make test      # unit suite (SQLite, no Docker needed)
```

The dev server listens on `127.0.0.1:8000`; override with `make run HOST=0.0.0.0 PORT=8080`.

## Deploy

To deploy to a remote server with Ansible + Docker Compose:

```bash
scripts/setup-ansible-inventory.sh   # create ansible/inventory.yml from the template
scripts/prepare-env.sh --hanko-api-url https://your-hanko-api-url.hanko.io \
  --allowed-hosts "fleet.example.com" \
  --csrf-trusted-origins "https://fleet.example.com"
make ansible-ping                    # verify SSH connectivity
make ansible-deploy                  # install Docker, sync source, build, migrate
```

See [docs/deployment.md](docs/deployment.md) for the full deployment guide.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/management-commands.md](docs/management-commands.md) | `import_csv`, `export_garage`, `convert_user_to_mechanic`; CSV import schemas and import/export workflows. |
| [docs/development.md](docs/development.md) | Makefile targets, environment and database layout, unit/BDD/e2e test suites, translations, migrations guard. |
| [docs/deployment.md](docs/deployment.md) | Ansible + Docker Compose deployment, production env preparation, and trade-offs. |
| [docs/branding.md](docs/branding.md) | Logo-inspired accent colors and their CSS variables. |

## Architecture at a glance

Django 6 vehicle maintenance app (Poetry, Python ≥3.12) with two apps:

- `shop`: garages, cars, work jobs, reports, memberships, and attachments.
- `car_docs`: per-car document notes and files.

Custom user model `shop.ShopUser`; authentication is Hanko-based (passkeys) with a Django session bridge. See [docs/development.md](docs/development.md) for environment variables and database selection.
