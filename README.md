## Command examples using the manage commands

Import cars from JSON:

```bash
poetry run python ./src/manage.py import_json Car src/cars.json --app shop
```

Import work jobs from JSON:

```bash
poetry run python ./src/manage.py import_json WorkJob src/imports/workjobs.json --app shop
```

Import reports by license plate JSON:

```bash
poetry run python ./src/manage.py import_json Report src/imports/reports_FMG3809.json --app shop
```

## Makefile targets

Use the Makefile to install dependencies and run tests:

```bash
make install
make test
make test-fast
```
