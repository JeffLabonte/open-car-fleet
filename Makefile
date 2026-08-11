.PHONY: install db-up db-wait db-stop db-reset db-snapshot migrate run test test-fast

POETRY ?= poetry
PYTHON ?= $(POETRY) run python
HOST ?= 0.0.0.0
PORT ?= 8000
DB_WAIT_SECONDS ?= 60

install:
	$(POETRY) install --no-root

db-up:
	docker compose up -d db

db-wait:
	@elapsed=0; \
	while [ $$elapsed -lt $(DB_WAIT_SECONDS) ]; do \
		container_id=$$(docker compose ps -q db); \
		if [ -n "$$container_id" ]; then \
			health=$$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $$container_id); \
			if [ "$$health" = "healthy" ] || [ "$$health" = "running" ]; then \
				echo "Database is ready ($$health)."; \
				exit 0; \
			fi; \
			echo "Waiting for database ($$health)..."; \
		else \
			echo "Waiting for database container..."; \
		fi; \
		sleep 2; \
		elapsed=$$((elapsed + 2)); \
	done; \
	echo "Database did not become ready within $(DB_WAIT_SECONDS)s."; \
	docker compose ps db; \
	exit 1

db-stop:
	docker compose stop db

db-reset:
	# Destructive: removes the Postgres container and named volume data.
	docker compose down -v --remove-orphans
	docker compose up -d db
	$(MAKE) db-wait

migrate: db-up db-wait
	$(PYTHON) src/manage.py migrate

run: install db-up migrate
	$(PYTHON) src/manage.py runserver $(HOST):$(PORT)

test:
	$(POETRY) run pytest -q

test-fast:
	$(POETRY) run pytest -q src/shop/tests.py -k FormEditableFieldsCoverageTests

db-snapshot: db-up db-wait
	@mkdir -p db_backups
	@timestamp=$$(date +%Y%m%d_%H%M%S); \
	outfile="db_backups/db_snapshot_$$timestamp.sql"; \
	docker compose exec -T db sh -c 'pg_dump -U "$${POSTGRES_USER:-open_garage_user}" -d "$${POSTGRES_DB:-open_garage}"' > "$$outfile"; \
	echo "Database snapshot written to $$outfile"
