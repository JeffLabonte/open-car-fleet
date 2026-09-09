# Open Car Fleet — Agent Instructions

Django 6 vehicle maintenance app (Poetry, Python ≥3.12) with two apps: `shop` (garages, cars, work jobs, reports) and `car_docs` (PDF car documents). Custom user model `shop.ShopUser`.

## Commands

Run everything from the project root. `manage.py` lives at `src/manage.py`; Python imports are `shop.*` / `settings.*` (root `conftest.py` puts `src/` on `sys.path`).

```bash
poetry install --no-root        # plain `poetry install` FAILS: no package root is defined
make run                        # start Postgres (docker compose), wait, migrate, runserver
make test                       # pytest -q
poetry run pytest src/shop/tests.py -k NameFragment          # focused run
poetry run pytest src/shop/tests.py::TestClass::test_name    # single test

# Management commands
poetry run python src/manage.py import_csv Car src/imports/cars.csv --garage <garage-uuid>  # --garage REQUIRED for Car
poetry run python src/manage.py import_csv WorkJob src/imports/workjobs.csv
poetry run python src/manage.py import_csv Report src/imports/reports_FMG3809.csv
poetry run python src/manage.py export_garage <garage-uuid> [--output path.xlsx]
poetry run python src/manage.py convert_user_to_mechanic <email>

# Translations (en-ca / fr-ca)
poetry run python src/manage.py makemessages -l en_CA -l fr_CA
poetry run python src/manage.py compilemessages
```

`make translations` is currently broken (typo in the Makefile) — call `makemessages` directly. Other useful targets: `make db-snapshot` (pg_dump to `db_backups/`), `make db-reset` (destructive: drops the Postgres volume).

## Testing

- **`make test` / bare `pytest` / CI only collect `src/shop/tests.py`** — `pytest.ini` sets `testpaths = src/shop`. `src/car_docs/tests.py` is silently skipped; run it explicitly: `poetry run pytest src/car_docs/tests.py`.
- Tests need no Postgres or Docker: root `conftest.py` clears `POSTGRES_*` env vars (forcing sqlite) and sets up Django databases via a `DiscoverRunner` session fixture — not pytest-django.
- Auth mocking: `@patch('shop.middleware.requests.get', ...)` for the Hanko API; authenticate test clients via `self.client.session['hanko_session_token'] = '...'` + `.save()`.
- Email mocking: `@patch('shop.models.garage.send_mail')` for invitations, `@patch('shop.mailgun_backend.requests.post')` for the Mailgun backend.
- CI is `.github/workflows/test.yml`: Fedora container, `poetry install --no-root`, `pytest -q` (same car_docs blind spot).

## Environment & Database

- `settings/settings.py` loads `src/.env` → falls back to checked-in `src/.env.template` → root `.env`/`.env.template` (first value per variable wins). The template has working defaults, so no `.env` is needed for dev or tests.
- DB: Postgres when `POSTGRES_DB` is set (docker-compose `db` service, postgres:18), else sqlite at `src/db.sqlite3`. Dev server uses Postgres via `make run`.
- `HANKO_API_URL` is required for real logins; `MAILGUN_API_KEY` / `MAILGUN_SANDBOX_DOMAIN` for invitation emails (custom HTTP backend `shop/mailgun_backend.py`, not SMTP).

## Authentication

All protected views in both apps use `@hanko_login_required` from `shop.middleware` — never Django's `login_required`:

1. Hanko JS frontend POSTs `/auth/hanko/callback/` → `complete_hanko_login()` (`src/shop/auth.py`) → Django session gains `hanko_session_token`.
2. `HankoAuthenticationMiddleware` revalidates that token against `HANKO_API_URL` (`GET <api>/userinfo`) on every unauthenticated request; API failure logs the user out.
3. `PUBLIC_PATHS` (`/login`, `/theme`, `/auth/hanko/callback/`) and `PUBLIC_PREFIXES` (`/static/`, `/admin/`) bypass auth.

## Data access

Scope all queries to the requesting user via `src/shop/view_helpers.py`: `user_cars_queryset`, `user_garages_queryset`, `user_car_docs_queryset`, `user_can_manage_garage`. Never `Car.objects.all()` / `Garage.objects.all()` in views.

## Model gotchas

- **UUID PKs**: `Car`, `Garage`, `GarageInvitation` (other models use integer PKs).
- **Assignment mutual exclusion**: `WorkJob`/`Report` take `assigned_to` (mechanic user) OR `assigned_shop` (`KnownShop`), never both. Enforced by DB CheckConstraints (`workjob_single_assignment_target`, `report_single_assignment_target`) plus `AssignedToShopFormMixin.clean()` — saving both via the ORM raises IntegrityError. Model `clean()` additionally requires `assigned_to.is_mechanic`.
- **VIN rules (11–17 alphanumerics, no I/O/Q, unique) live in `CarBaseForm.clean_vin` and `shop/importers.py`, NOT the model** — the model field is just `max_length=50, unique=True, nullable`, so ORM-created cars bypass VIN validation.
- **JSON list fields** (`required_items`, `documents`, `photos`): edited as `<textarea>` (one item per line) via `LineListFieldMixin` in `src/shop/forms/base.py`.
- `ShopUser.is_mechanic` gates mechanic assignment; forms restrict `assigned_to` to mechanics and CSV imports require it.

## Structure

```
src/
  settings/         # Django settings, root urls.py
  shop/
    models/         # one file per model: car, garage, job, report, user
    forms/          # forms package: base.py (mixins), car, garage, job, report, shop, import_data
    views.py        # all shop views (function-based)
    view_helpers.py, middleware.py, auth.py
    importers.py    # CSV import logic (import_csv command + web UI)
    exporters.py    # Excel garage export (export_garage command + web UI)
    management/commands/  # import_csv, export_garage, convert_user_to_mechanic
  car_docs/         # CarDoc PDF uploads; reuses shop's middleware and view_helpers
  imports/          # sample CSVs for import_csv
```

## Conventions

- Templates use `{% translate %}` (en-ca/fr-ca). After adding user-facing strings, run `makemessages` + `compilemessages`, and update `src/locale/*/LC_MESSAGES/django.po`.
- CSV import is all-or-nothing: any invalid row aborts the whole import; unknown fields are warned and ignored; `car` references resolve by UUID, VIN, license plate, or usual name.
- Deploy: `scripts/prepare-env.sh` (writes `src/.env.production`) then `scripts/deploy-ssh.sh` (uploads full source over SSH, `docker compose up -d --build`, migrates).
