# Create Django App Skill

This skill automates the creation of a new Django application within the current project using the `manage.py startapp` command. It is designed to be workspace‑scoped and can be invoked from the VS Code chat or any custom workflow that supports Copilot skills.

## Purpose
Create a fully‑configured Django app (including migrations, tests, admin registration, and an initial URL configuration) without manually running shell commands or creating directories by hand.

## Usage
```text
# In the chat:
Create a new Django app called `blog`.
```

The skill will:
1. Prompt for the app name if not provided.
2. Run `poetry run python src/manage.py startapp <app_name>`.
3. Add the new app to `INSTALLED_APPS` in `settings/settings.py`.
4. Create an empty `urls.py` and include it in the project’s root URL configuration.
5. Generate a basic test file (`tests.py`) with a placeholder test case.

## Implementation Details
- The skill is implemented as a Python script that uses the VS Code API to execute terminal commands.
- It relies on the existing `poetry` environment and expects `src/manage.py` to be present.
- Error handling includes checking for duplicate app names and command failures.

## Example Prompts
- "Create a new Django app called `vehicles`"
- "Add an app named `maintenance`"

## Related Customizations
- Combine with the **Project Setup** skill to scaffold additional boilerplate (models, views, serializers).
- Add a post‑creation hook that automatically registers the app in the admin site.