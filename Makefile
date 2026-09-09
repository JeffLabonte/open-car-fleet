.PHONY: install db-up db-wait db-stop db-reset db-snapshot migrate run test test-fast test-bdd test-coverage test-e2e translations

POETRY ?= poetry
PYTHON ?= $(POETRY) run python
HOST ?= 0.0.0.0
PORT ?= 8000
DB_WAIT_SECONDS ?= 60
E2E_HOST ?= 127.0.0.1
E2E_PORT ?= 8000
E2E_BASE_URL ?= http://$(E2E_HOST):$(E2E_PORT)
E2E_WAIT_SECONDS ?= 60

install:
	$(POETRY) install --no-root --with test

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

test-bdd:
	$(POETRY) run pytest -q tests/bdd

test-coverage:
	$(POETRY) run pytest -q --cov=src/shop --cov=src/car_docs --cov=src/settings --cov-branch --cov-report=term-missing

test-e2e:
	$(POETRY) install --no-root --with test,e2e
	$(PYTHON) src/manage.py migrate --noinput
	@server_pid=''; \
	cleanup() { if [ -n "$$server_pid" ]; then kill "$$server_pid" 2>/dev/null || true; fi; }; \
	trap cleanup EXIT INT TERM; \
	HANKO_API_URL='' $(PYTHON) src/manage.py runserver $(E2E_HOST):$(E2E_PORT) --noreload > /tmp/open-car-fleet-e2e.log 2>&1 & \
	server_pid=$$!; \
	for attempt in $$(seq 1 $(E2E_WAIT_SECONDS)); do \
		if curl --fail --silent $(E2E_BASE_URL)/login/ >/dev/null; then break; fi; \
		if [ "$$attempt" -eq "$(E2E_WAIT_SECONDS)" ]; then cat /tmp/open-car-fleet-e2e.log; exit 1; fi; \
		sleep 1; \
	done; \
	HANKO_API_URL='' E2E_BASE_URL=$(E2E_BASE_URL) $(POETRY) run pytest -q tests/e2e

db-snapshot: db-up db-wait
	@mkdir -p db_backups
	@timestamp=$$(date +%Y%m%d_%H%M%S); \
	outfile="db_backups/db_snapshot_$$timestamp.sql"; \
	docker compose exec -T db sh -c 'pg_dump -U "$${POSTGRES_USER:-open_garage_user}" -d "$${POSTGRES_DB:-open_garage}"' > "$$outfile"; \
	echo "Database snapshot written to $$outfile"

translations: install
	$(POETRY) run python src/manage.py makemessages -l en_CA -l fr_CA
