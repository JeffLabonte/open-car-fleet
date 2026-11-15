# syntax=docker/dockerfile:1

# Use the official Python image with a slim base for production.
# python:3.13-slim
FROM python:3.13-slim@sha256:48d884813cf44e927cf64c5529dd630dd3b18338c6dc727991eef9b71e934a20 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_STATIC_ROOT=/staticfiles

# Install runtime dependencies and tools.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only dependency declarations first for better caching.
COPY pyproject.toml poetry.lock /app/

# Install dependencies with Poetry in a virtual environment.
RUN pip install --no-cache-dir --only-binary :all: poetry==2.5.1 \
    && poetry config virtualenvs.create false \
    && poetry config installer.no-binary false \
    && poetry install --no-root --no-interaction --no-ansi

# Copy application code.
COPY . /app/

# Collect static files for production.
# Static collection uses build-only settings and never needs runtime credentials.
RUN SECRETS_BACKEND=environment DJANGO_TRUSTED_PROXY=True DJANGO_SECRET_KEY=build-only-secret \
    python src/manage.py collectstatic --noinput

# Use a lean runtime image.
# python:3.13-slim
FROM python:3.13-slim@sha256:48d884813cf44e927cf64c5529dd630dd3b18338c6dc727991eef9b71e934a20 AS final
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DJANGO_STATIC_ROOT=/staticfiles

WORKDIR /app/src

COPY --from=base /usr/local/bin /usr/local/bin
COPY --from=base /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=base /app /app
COPY --from=base /staticfiles /staticfiles

# Install Docker CLI and Compose plugin so management commands can
# self-orchestrate the Compose stack. These tools are only usable when the
# container is explicitly started with the Docker socket and backup directories
# mounted (e.g. for the restore_db command).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg lsb-release \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL --proto "=https" --proto-redir "=https" --tlsv1.2 https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/* /etc/apt/sources.list.d/docker.list /etc/apt/keyrings/docker.asc

RUN addgroup --system django && adduser --system --ingroup django django \
    && mkdir -p /app/src/media \
    && chown -R django:django /app/src/media
USER django

EXPOSE 8000
CMD ["gunicorn", "--chdir", "/app/src", "settings.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
