---
name: django-app-learning
description: "Guide a user through building and refining a Django app in this workspace. Use when the project was created with django-admin startproject src and the shop app was created with django-admin startapp shop src/."
user-invocable: true
---

# Django App Learning Skill

Use this skill to build, extend, and validate the Django application inside the current `open-garage` workspace.

## When to use
- I want step-by-step guidance for the Django project in this repo.
- I need help wiring up the `shop` app, models, views, URLs, admin, templates, or tests.
- I created the project with `django-admin startproject src` and the app with `django-admin startapp shop src/`.

## What this skill does
- Confirms the Django project structure and app registration.
- Helps design models in `src/shop/models/` and register them in `src/shop/admin.py`.
- Guides adding views in `src/shop/views.py` and URL routes in `src/shop/urls.py` plus `src/urls.py`.
- Suggests templates under `src/shop/templates/shop/` and form handling patterns.
- Walks through migrations, test creation, and running the development server.

## Recommended workflow
1. Verify `src/settings.py` has `shop` listed in `INSTALLED_APPS` and that `BASE_DIR` is correct.
2. Define or refine the app models in `src/shop/models/`, using clear fields and relationships.
3. Register models in `src/shop/admin.py` so the admin site can manage them.
4. Add views in `src/shop/views.py`, choosing between function-based views and generic/class-based views.
5. Create `src/shop/urls.py` and include it from `src/urls.py`.
6. Add templates under `src/shop/templates/shop/` and use `render()` or `TemplateView` if needed.
7. Run `python manage.py makemigrations` and `python manage.py migrate` to update the database.
8. Create a superuser and verify the admin interface with `python manage.py createsuperuser`.
9. Add or update tests in `src/shop/tests.py` and run them with `python manage.py test shop`.

## Decision points
- Use the default SQLite database or configure a different database backend.
- Choose whether the app should expose HTML pages, forms, or API endpoints.
- Prefer Django generic views for CRUD or custom views for business-specific logic.
- Add static/media handling if the app needs file uploads or assets.

## Example prompts
- "Help me wire up the `shop` app URLs and views."
- "Create a Django model for a car repair job and register it in the admin."
- "Write tests for `shop` views and forms."
