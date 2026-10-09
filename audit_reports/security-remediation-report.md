# Open Car Fleet — Security Remediation Report

**Date:** 2026-10-08  
**Branch:** `main` (security/remediation-2026-10)  
**Auditor / Implementer:** OpenCode agent  
**Scope:** All 18 findings from the security audit, implemented in 5 mergeable phases.

## Executive Summary

This report documents the complete remediation of 18 security findings in the Open Car Fleet Django application. Changes were delivered in five phases, each committed independently and verified with the full test suite (`make test`) and end-to-end suite (`make test-e2e`).

| Phase | Theme | Findings | Commit |
|---|---|---|---|
| 1 | Safe hardening | SEC-001, SEC-014, SEC-016, SEC-017, SEC-018 | `4daedf3` |
| 2 | Deployment hygiene | SEC-008, SEC-009, SEC-015 | `8c3b6a9` |
| 3 | Hanko identity | SEC-004, SEC-005, SEC-006 | `b5081a4` |
| 4 | Transport / input safety | SEC-002, SEC-003 | `0b4fb15` |
| 5 | CSP, scope, admin, uploads, rate limiting | SEC-007, SEC-010, SEC-011, SEC-012, SEC-013 | `be4fa69` |

**Verification status:**

```text
make test
# 244 passed, 19 warnings, 2 subtests passed in 4.34s

make test-e2e
# 16 passed, 17 warnings in 53.63s
```

---

## Phase 1 — Safe Hardening

### SEC-001: World-readable credential files

**Risk:** Setup scripts created `src/.env.production` and `ansible/inventory.yml` with default permissions, potentially readable by other users.

**Fix:** Added `umask 077` and explicit `chmod 600` to both setup scripts.

```bash
# scripts/prepare-env.sh
umask 077
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

# scripts/setup-ansible-inventory.sh
umask 077
touch "$OUTPUT_FILE"
chmod 600 "$OUTPUT_FILE"
```

### SEC-014: Backup directories/files world-readable

**Risk:** Backup role created directories with `0755` and log files with default permissions.

**Fix:** Changed directory mode to `0700` and log file mode to `0600`.

```yaml
# ansible/roles/backup/tasks/main.yml
- name: Ensure backup directories exist
  ansible.builtin.file:
    path: "{{ item }}"
    state: directory
    mode: '0700'

- name: Create backup log file
  ansible.builtin.file:
    path: "{{ backup_log_file }}"
    state: touch
    mode: '0600'
```

### SEC-016: Admin changelist crash on staged attachments

**Risk:** `AttachmentAdmin.parent_label` called `obj.content_type.name` without a null check, crashing the admin when staged attachments had no parent.

**Fix:** Added null-safe fallback.

```python
# src/shop/admin.py
@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    def parent_label(self, obj: Attachment) -> str:
        if obj.content_type_id is None:
            return _('Staged upload')
        return f"{obj.content_type.name} / {obj.object_id}"
```

### SEC-017: `.gitignore` ignores required Ansible role

**Risk:** Unanchored `env/` pattern also matched `ansible/roles/env/`, causing the required role to be untracked.

**Fix:** Anchored virtual-env rules and tracked the Ansible role.

```gitignore
# .gitignore
/env/
/venv/
```

### SEC-018: `is_valid` loose truthiness

**Risk:** `fetch_hanko_userinfo` used a truthy check (`if data.get('is_valid'):`), so a string `"false"` would be treated as valid.

**Fix:** Strict boolean comparison.

```python
# src/shop/auth.py
if data.get('is_valid') is not True:
    raise HankoAuthenticationError('Hanko session is not valid.')
```

---

## Phase 2 — Deployment Hygiene

### SEC-008: Ansible rsync copies inventory to host

**Risk:** `rsync_opts` excluded env files but not the `ansible/` directory or wildcard credential files.

**Fix:** Excluded `ansible/`, `.env.*`, and `src/.env.*`.

```yaml
# ansible/roles/app/tasks/main.yml
rsync_opts:
  - '--exclude=.git'
  - '--exclude=.env'
  - '--exclude=.env.*'
  - '--exclude=src/.env'
  - '--exclude=src/.env.*'
  - '--exclude=ansible/'
```

### SEC-009: SSH host-key verification disabled

**Risk:** `ansible/ansible.cfg` set `host_key_checking = False`, and the inventory setup script injected `-o StrictHostKeyChecking=no`.

**Fix:** Removed both overrides and documented host-key pinning in `docs/deployment.md`.

```ini
# ansible/ansible.cfg
[defaults]
inventory = inventory.yml
retry_files_enabled = True
```

### SEC-015: Database container receives app secrets

**Risk:** `docker-compose.prod.yml` mounted the full `src/.env` into the Postgres container, exposing Hanko and MailerSend secrets.

**Fix:** Created dedicated `src/.env.database` for the `db` service. During deploy, Ansible derives it on the server from the uploaded `src/.env` so the DB password stays in sync with the web container.

```yaml
# docker-compose.prod.yml
services:
  db:
    env_file:
      - ./src/.env.database
  web:
    env_file:
      - ./src/.env
```

```yaml
# ansible/roles/env/tasks/main.yml
- name: Derive database-only env file from deployed env
  ansible.builtin.shell: |
    set -euo pipefail
    grep -E '^POSTGRES_' "{{ app_dir }}/src/.env" > "{{ app_dir }}/src/.env.database"
    chmod 600 "{{ app_dir }}/src/.env.database"
  changed_when: true
```

---

## Phase 3 — Hanko Identity Hardening

### SEC-004: Disabled users re-authenticated

**Risk:** `complete_hanko_login` called `login()` without checking `is_active`.

**Fix:** Reject inactive users before login; `hanko_callback` wraps both fetch and login in the same error handler.

```python
# src/shop/auth.py
def complete_hanko_login(request, user_data):
    user = sync_hanko_user(...)
    if not user.is_active:
        raise HankoAuthenticationError('Account is disabled.')
    login(request, user, ...)
```

### SEC-005: Email-based Hanko account takeover

**Risk:** `sync_hanko_user` matched existing users by email and overwrote `hanko_id`, allowing a Hanko identity to take over a local account.

**Fix:** Refuse to link when the email exists without a matching `hanko_id`.

```python
# src/shop/auth.py
def sync_hanko_user(...):
    if email:
        user = ShopUser.objects.filter(email__iexact=email).first()
        if user:
            existing_hanko_id = (user.hanko_id or '').strip()
            if existing_hanko_id and existing_hanko_id != hanko_id:
                raise HankoAuthenticationError(
                    'Hanko identity does not match the account linked to this email.'
                )
            if not existing_hanko_id and hanko_id:
                raise HankoAuthenticationError(
                    'An account with this email already exists. '
                    'Please contact an administrator to link Hanko sign-in.'
                )
```

### SEC-006: Hanko session not bound to local identity

**Risk:** Middleware validated the token but ignored the returned `sub`, so swapping Hanko identities would not log the user out.

**Fix:** Compare remote `sub` to `user.hanko_id` on every recheck and after rehydration.

```python
# src/shop/middleware.py
if request.user.is_authenticated:
    ...
    user_info = fetch_hanko_userinfo(hanko_session_token)
    local_hanko_id = getattr(request.user, 'hanko_id', None)
    remote_hanko_id = user_info.get('id')
    if local_hanko_id and remote_hanko_id != local_hanko_id:
        logout(request)
        return redirect_to_login(...)
```

---

## Phase 4 — Transport Security and Input Safety

### SEC-002: HTTPS/HSTS not enforced

**Risk:** `SECURE_SSL_REDIRECT` defaulted to off and `SECURE_HSTS_SECONDS` to 0.

**Fix:** Default to secure behavior when `DEBUG=False`, and require `DJANGO_TRUSTED_PROXY=True` when SSL redirect is enabled to avoid infinite redirect loops behind a reverse proxy.

```python
# src/settings/settings.py
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', str(not DEBUG)).strip().lower() in ('1', 'true', 'yes')
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '31536000' if not DEBUG else '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

if SECURE_SSL_REDIRECT and not trusted_proxy:
    raise ImproperlyConfigured(
        'SECURE_SSL_REDIRECT is enabled but DJANGO_TRUSTED_PROXY is not set. '
        'Set DJANGO_TRUSTED_PROXY=True when running behind a reverse proxy, '
        'or explicitly disable SECURE_SSL_REDIRECT.'
    )
```

`prepare-env.sh` now defaults `DJANGO_TRUSTED_PROXY=True`.

### SEC-003: Reflected XSS in login page

**Risk:** `hanko_api_url`, `next_url`, and `logged_out` were rendered into inline JavaScript using HTML escaping, not JS escaping.

**Fix:** Moved all inline JS to external modules and passed dynamic values via `json_script`.

```html
<!-- src/shop/templates/shop/login.html -->
{{ hanko_api_url|json_script:'hanko-api-url' }}
{{ next_url|default:'/'|json_script:'hanko-next-url' }}
{{ logged_out|json_script:'hanko-logged-out' }}

<script type="module" src="{% static 'shop/js/login.js' %}"></script>
```

```javascript
// src/shop/static/shop/js/login.js
const apiUrl = JSON.parse(document.getElementById('hanko-api-url').textContent);
const nextUrl = JSON.parse(document.getElementById('hanko-next-url').textContent);
const loggedOut = JSON.parse(document.getElementById('hanko-logged-out').textContent);
```

---

## Phase 5 — CSP, Scope, Admin, Uploads, Rate Limiting

### SEC-007: Unpinned Hanko JS from CDN

**Risk:** Login and profile pages loaded Hanko SDKs from a public CDN with no version pinning, SRI, or CSP.

**Fix:**
1. Downloaded bundled SDKs to `src/shop/static/shop/vendor/hanko/`.
2. Moved inline scripts to `src/shop/static/shop/js/login.js` and `profile.js`.
3. Added a CSP middleware.

```python
# src/shop/middleware.py
class ContentSecurityPolicyMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        hanko_api = getattr(settings, 'HANKO_API_URL', '') or ''
        connect_src = "'self'"
        if hanko_api:
            parsed = urlparse(hanko_api)
            connect_src += f" {parsed.scheme}://{parsed.netloc}"
        response['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            f"connect-src {connect_src}; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response
```

### SEC-010: CSV import bypasses KnownShop scope

**Risk:** `CSVImporter._resolve_shop` used `KnownShop.objects.all()`, allowing users to reference private shops created by others.

**Fix:** Added `user` to `ImportContext` and scoped the queryset.

```python
# src/shop/importers.py
@dataclass(slots=True)
class ImportContext:
    garage: Garage | None = None
    car: Car | None = None
    user: Any = None

def _resolve_shop(self, raw_value, context=None):
    queryset = KnownShop.objects.all()
    if context and context.user is not None:
        queryset = queryset.filter(
            models.Q(created_by__isnull=True) | models.Q(created_by=context.user)
        )
```

### SEC-011: Unbounded staged uploads

**Risk:** Attachments allowed 500 MB per file with no per-user quota.

**Fix:** Lowered ceiling to 100 MB and added a 1 GB per-user staged quota.

```python
# src/shop/forms/base.py
ATTACHMENT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
ATTACHMENT_USER_STAGED_QUOTA_BYTES = 1024 * 1024 * 1024
```

```python
# src/shop/views.py
staged_bytes = sum(
    attachment.file.size
    for attachment in Attachment.objects.filter(
        uploaded_by=request.user,
        content_type__isnull=True,
    ).iterator()
    if attachment.file
)
if staged_bytes + upload.size > ATTACHMENT_USER_STAGED_QUOTA_BYTES:
    return JsonResponse({'error': _('Upload quota exceeded.')}, status=413)
```

### SEC-012: No rate limiting

**Risk:** Authentication and upload endpoints had no throttling.

**Fix:** Added `django-ratelimit` to sensitive endpoints and a middleware to return 429.

```python
# src/shop/views.py
from django_ratelimit.decorators import ratelimit

@ratelimit(key='ip', rate='10/m', method='POST')
def hanko_callback(request):
    ...

@hanko_login_required
@require_POST
@ratelimit(key='user', rate='30/m', method='POST')
def attachment_upload(request):
    ...
```

```python
# src/shop/middleware.py
class RatelimitMiddleware(MiddlewareMixin):
    def process_exception(self, request, exception):
        if isinstance(exception, Ratelimited):
            return HttpResponse('Too Many Requests', status=429)
```

### SEC-013: Django admin bypasses Hanko

**Risk:** `/admin/` was in `PUBLIC_PREFIXES`, so the Hanko middleware skipped it entirely.

**Fix:** Removed `/admin/` from public prefixes.

```python
# src/shop/middleware.py
PUBLIC_PREFIXES = (
    '/static/',
)
```

---

## Verification Commands

Run these commands to verify the remediation state:

```bash
# Unit and integration tests
make test

# End-to-end tests
make test-e2e

# Production compose configuration sanity check
docker compose -f docker-compose.prod.yml config
```

## Remaining / Future Work

- **Vault integration (decision made):** The team decided to use HashiCorp Vault via AppRole for secrets. This was not implemented in this remediation because it requires infrastructure outside the application repository.
- **Traefik TLS:** Tailscale HTTPS is used now; Traefik will be introduced later.
- **Anymail `MAILERS` migration:** Django 6.1 deprecates `EMAIL_BACKEND`; revisit when Anymail supports the new `MAILERS` framework.

## Files Changed

A full list of changed files is available via:

```bash
git log --oneline --name-only 4daedf3..be4fa69
```

Key files include:

- `src/shop/auth.py`
- `src/shop/middleware.py`
- `src/shop/views.py`
- `src/shop/importers.py`
- `src/shop/forms/base.py`
- `src/shop/admin.py`
- `src/settings/settings.py`
- `src/settings/test_settings.py`
- `src/shop/templates/shop/login.html`
- `src/shop/templates/shop/profile.html`
- `src/shop/static/shop/js/login.js`
- `src/shop/static/shop/js/profile.js`
- `src/shop/static/shop/vendor/hanko/*`
- `ansible/ansible.cfg`
- `ansible/roles/app/tasks/main.yml`
- `ansible/roles/backup/tasks/main.yml`
- `docker-compose.prod.yml`
- `scripts/prepare-env.sh`
- `scripts/setup-ansible-inventory.sh`
- `docs/security/vulnerability-log.md`
- `pyproject.toml` / `poetry.lock`
- `src/shop/tests/test_*.py` (new and updated regression tests)
