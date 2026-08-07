# Use the official Python image with a slim base for production.
FROM python:3.14-slim as base

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
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false \
    && poetry install --no-root --no-interaction --no-ansi

# Copy application code.
COPY . /app/

# Collect static files for production.
RUN python src/manage.py collectstatic --noinput

# Use a lean runtime image.
FROM python:3.14-slim as final
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DJANGO_STATIC_ROOT=/staticfiles

WORKDIR /app/src

COPY --from=base /usr/local/bin /usr/local/bin
COPY --from=base /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=base /app /app
COPY --from=base /staticfiles /staticfiles

RUN addgroup --system django && adduser --system --ingroup django django
USER django

EXPOSE 8000
CMD ["gunicorn", "--chdir", "/app/src", "settings.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
