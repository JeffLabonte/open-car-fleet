# Development guide

Local development workflow, database lifecycle, and test suites.

## Prerequisites

You need Python >= 3.12, Poetry, and a container runtime (Docker with the Compose plugin) to run the full stack.

Install them automatically with:

```bash
make install-prereqs
```

This runs `scripts/install-prereqs.sh`, which supports:

- **macOS** via Homebrew (`brew install python@3.12`, `poetry`, Docker Desktop cask).
- **Linux** via `apt` (Ubuntu/Debian), `dnf` (Fedora/RHEL), or `pacman` (Arch).
- **Windows Subsystem for Linux (WSL2)** using the same `apt` path.
- **Native Windows** prints manual `winget` instructions.

If you already have Python, Poetry, and Docker installed, you can skip this step.

## Makefile targets

Use the Makefile to install dependencies, run migrations, start the app, and run tests:

```bash
make install
make migrate
make run
make db-stop
make db-reset
make test
make test-fast
```

`make run` starts Django on `127.0.0.1:8000` after applying migrations. Override the host or port if needed:

```bash
make run HOST=0.0.0.0 PORT=8080
```

### Local Postgres lifecycle via docker-compose

- `make run` automatically starts `db` with `docker compose up -d db`, waits for readiness, runs migrations, then starts Django.
- `make db-stop` gracefully stops the Postgres container.
- `make db-reset` is destructive: it removes containers and volumes, recreates `db`, and waits for readiness.
- `make db-snapshot` writes a `pg_dump` snapshot to `db_backups/`.

Troubleshooting:
- If `db` fails to become ready, run `docker compose ps` and `docker compose logs db`.
- If port `5432` is busy on the host, change `POSTGRES_PORT` and adjust the compose port mapping.
- If migrations fail with authentication errors, verify `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_HOST` in `src/.env`.

## Environment and database

- `settings/settings.py` loads `src/.env` → falls back to checked-in `src/.env.template` → root `.env`/`.env.template` (first value per variable wins). The template has working defaults, so no `.env` is needed for dev or tests.
- DB: Postgres when `POSTGRES_DB` is set (docker-compose `db` service, postgres:18), else sqlite at `src/db.sqlite3`. Dev server uses Postgres via `make run`.
- `HANKO_API_URL` is required for real logins; `MAILERSEND_API_TOKEN` for invitation emails (django-anymail MailerSend backend via `EMAIL_BACKEND`/`ANYMAIL` settings; not SMTP). `DEFAULT_FROM_EMAIL` must be an address on the verified MailerSend domain. Django 6.1 deprecates `EMAIL_BACKEND` in favour of its new `MAILERS` framework — Anymail 15.x still targets the classic backend API; revisit when Anymail supports `MAILERS`.

## Test suites

| Target | What it runs |
| --- | --- |
| `make test` | Full unit suite (`pytest -q`), parallel with xdist. No Postgres or Docker needed: pytest-env clears `POSTGRES_*` so pytest-django uses SQLite. |
| `make test-serial` | Unit suite without xdist parallelism (`-n0`), useful to reproduce ordering issues. |
| `make test-profile` | Serial run with the 25 slowest tests listed (`--durations=25`). |
| `make test-fast` | Quick smoke subset: form/model editable-field coverage tests only. |
| `make test-bdd` | pytest-bdd scenarios in `tests/bdd`. |
| `make test-coverage` | Unit suite with branch coverage for `src/shop`, `src/car_docs`, `src/settings`. |
| `make test-e2e` | Selenium (headless Firefox) end-to-end suite against a live dev server. |

Focused runs:

```bash
poetry run pytest src/shop/tests/test_auth.py -k NameFragment          # by test name
poetry run pytest src/shop/tests/test_auth.py::TestClass::test_name    # single test
```

### Unit test conventions

- pytest-django is configured through `pytest.ini`; tests collect from `src` and `tests/bdd`.
- Shop unit tests live in the `src/shop/tests/` package, one module per domain: `test_auth`, `test_garage_sharing`, `test_shops`, `test_cars`, `test_forms`, `test_attachments`, `test_importers`, `test_exporters`, `test_views`, `test_security`. Shared fakes and file signatures are in `src/shop/tests/helpers.py`.
- Auth mocking: `@patch('shop.auth.requests.get', ...)` for the Hanko API; authenticate test clients via `self.client.session['hanko_session_token'] = '...'` + `.save()`.
- Email mocking: `@patch('shop.models.garage.send_mail')` for invitations, `@patch('anymail.backends.base_requests.requests.Session', return_value=fake_session)` for the MailerSend/Anymail backend (see `src/shop/tests/test_email.py`).
- `settings/test_settings.py` adds fast password hashing (MD5), a per-process temporary `MEDIA_ROOT`, and forces `django.core.mail.backends.locmem.EmailBackend` so no test reaches the MailerSend API.

### End-to-end suite (`make test-e2e`)

The e2e suite drives a real dev server with headless Firefox:

1. Installs the `test,e2e` dependency groups.
2. Deletes and re-creates a **dedicated SQLite database** at `/tmp/open-car-fleet-e2e-<port>.sqlite3` (override with `E2E_DB=`), running migrations on it.
3. Starts the server with `DJANGO_SETTINGS_MODULE=settings.test_settings`, `E2E_DB_PATH`, `DEBUG=True`, `HANKO_API_URL=''`, and cleared `POSTGRES_*` variables, then waits for `/login/` to respond.
4. Runs `pytest -q -n0 tests/e2e` with the same environment, so the pytest process and the server **share the same database**. Fixture data created through the ORM is visible to the server.

The server and pytest must never use different databases: fixtures that create users, garages, or cars via the ORM are invisible to the server otherwise, and every browser navigation 404s or times out.

Browser setup:

- Firefox is launched headless; override the binary with `FIREFOX_BIN=/path/to/firefox` (CI installs Firefox with `browser-actions/setup-firefox@v1`).
- Sessions are signed in through the DEBUG-only `/set-test-session/?email=...` helper, which creates a session without a Hanko token so the auth middleware skips revalidation.

### CI

CI is `.github/workflows/test.yml`: the unit suite runs in Fedora and a separate PR job installs Firefox with `browser-actions/setup-firefox@v1` before running `make test-e2e`.

## Translations (en-ca / fr-ca)

Templates use `{% translate %}`. After adding user-facing strings:

```bash
poetry run python src/manage.py makemessages -l en_CA -l fr_CA
poetry run python src/manage.py compilemessages
```

Update `src/locale/*/LC_MESSAGES/django.po` with the new translations.

## Migrations guard

```bash
make check-migrations
```

Fails when model changes are missing migrations. Data migrations that query `ContentType` must use `get_or_create` (not `get`): content type rows are only created by `post_migrate` after all migrations run, so `get` crashes on fresh databases.
