# Open Car Fleet — Agent Instructions

Open Car Fleet is a Django 6 vehicle maintenance management system. Users track cars, plan work jobs, and record maintenance reports across shared garages.

## Build & Test

```bash
# Install dependencies
poetry install

# Run development server (from project root)
poetry run python src/manage.py runserver

# Run migrations
poetry run python src/manage.py migrate

# Run tests
poetry run pytest src/

# Bulk import data
poetry run python src/manage.py import_json Car src/imports/cars.json --app shop
poetry run python src/manage.py import_json WorkJob src/imports/workjobs.json --app shop
poetry run python src/manage.py import_json Report src/imports/reports_FMG3809.json --app shop

# Promote a user to mechanic
poetry run python src/manage.py convert_user_to_mechanic <email>
```

## Architecture

```
src/
  settings/         # Django settings, URLs, ASGI/WSGI
  shop/
    models/         # One file per model (car, garage, job, report, user)
    views.py        # All views (function-based)
    forms.py        # ModelForms
    auth.py         # Hanko sync helpers
    middleware.py   # Hanko session validation
    management/commands/  # import_json, convert_user_to_mechanic
    templates/shop/ # HTML templates
    migrations/
```

## Authentication

All protected views use `@hanko_login_required` (not Django's `login_required`). Auth flow:
1. Hanko JS frontend → POST `/auth/hanko/callback/` → `sync_hanko_user()` → Django session
2. `HankoAuthenticationMiddleware` validates `hanko_session_token` on every request via `HANKO_API_URL`
3. `PUBLIC_PATHS` in middleware bypass auth (login, logout, static)

`HANKO_API_URL` must be set in `.env` (project root or `src/`).

## Data Access Conventions

**Always scope queries to the requesting user.** Use the view-level helpers:
- `_user_cars_queryset(user)` — cars in garages the user is a member of
- `_user_garages_queryset(user)` — garages where the user has a membership

Never query `Car.objects.all()` or `Garage.objects.all()` in views.

## Key Model Gotchas

- **UUID PKs**: `Car`, `Garage`, `GarageInvitation` use `UUIDField(primary_key=True)`; other models use default integer PKs.
- **Mutual exclusion**: `WorkJob` and `Report` can be assigned to a `ShopUser` (mechanic) **or** a `KnownShop`, never both. This is enforced at the model `clean()` level.
- **JSON fields**: `required_items`, `documents`, `photos` are stored as JSON lists. Forms use a `<textarea>` with `clean_<field>()` to serialize/deserialize.
- **VIN validation**: 11–17 chars, no letters I/O/Q, must be unique.
- **Mechanic flag**: Check `ShopUser.is_mechanic` before exposing mechanic assignment in forms/views.

## Adding New Features

| Task | Where to start |
|------|---------------|
| New model | `src/shop/models/<name>.py`, export from `models/__init__.py`, create migration |
| New view | `views.py` with `@hanko_login_required`, add URL in `shop/urls.py`, filter with `_user_*_queryset()` |
| New form | `forms.py` as a `ModelForm`; list-valued fields use `<textarea>` + `clean_*()` |
| New management command | `src/shop/management/commands/<name>.py` extending `BaseCommand` |
| New bulk import type | Extend `import_json.py` or add a model-specific handler |

## Testing

- Tests live in `src/shop/tests.py` using Django `TestCase`.
- Mock the Hanko API with `@patch('shop.middleware.requests.get')`.
- Use `RequestFactory` for middleware unit tests.
- Manipulate sessions via `self.client.session['hanko_session_token']` + `.save()`.
- See [src/shop/tests.py](src/shop/tests.py) for established patterns.
