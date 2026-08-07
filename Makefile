.PHONY: install test test-fast

POETRY ?= poetry
PYTHON ?= $(POETRY) run python

install:
	$(POETRY) install

test:
	$(PYTHON) src/manage.py test shop.tests

test-fast:
	$(PYTHON) src/manage.py test shop.tests.FormEditableFieldsCoverageTests
