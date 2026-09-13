# Management commands

Project management commands run through `manage.py` at `src/manage.py` with Poetry:

```bash
poetry run python src/manage.py <command>
```

## import_csv

Import normalized CSV datasets into the database.

```bash
poetry run python ./src/manage.py import_csv Car src/imports/cars.csv --garage <garage-uuid>
poetry run python ./src/manage.py import_csv WorkJob src/imports/workjobs.csv
poetry run python ./src/manage.py import_csv Report src/imports/reports_FMG3809.csv
```

- The importer supports normalized UTF-8 CSV files for `Car`, `WorkJob`, and `Report`.
- Automatic dialect detection via Python's `csv.Sniffer` supports comma, semicolon, tab, or pipe delimited CSV files.
- Car imports require a single target garage. In the web UI, use the garage detail page and choose `Import cars`; in the CLI, pass `--garage <garage-uuid>`.
- Work jobs and reports are imported from the selected car page in the web UI. In that flow, the selected car is applied automatically, so the CSV file can omit `car`.
- In the CLI or any non-car-scoped flow, the `car` field can reference an existing car by UUID, VIN, license plate, or usual name.
- List fields such as `required_items`, `documents`, and `photos` accept newline-delimited strings in quoted CSV cells.

## export_garage

Export one garage to an Excel backup workbook.

```bash
poetry run python ./src/manage.py export_garage <garage-uuid>
poetry run python ./src/manage.py export_garage <garage-uuid> --output ./backups/my-garage.xlsx
```

- Garage backups are available from the garage detail page (`Export to Excel`), from the garage list quick action, and from the `export_garage` management command.
- Export requires owner or manager role for the target garage in the web UI.
- The default workbook includes `meta`, `garage`, `memberships`, `cars_import`, `workjobs_import`, and `reports_import` sheets.
- Invitation history is intentionally excluded from the default export.

## convert_user_to_mechanic

Promote an existing user to mechanic:

```bash
poetry run python src/manage.py convert_user_to_mechanic <email>
```

# CSV import schemas

Each import file contains a header row with field names, followed by data rows.

## Car import schema

Use this from a garage page in the web UI or with `import_csv Car ... --garage <garage-uuid>` in the CLI.

Required fields:
- `make`: string
- `model`: string

Optional fields:
- `usual_name`: string
- `colour`: string
- `year`: integer
- `mileage`: integer
- `vin`: string, 11 to 17 chars, no `I`, `O`, or `Q`
- `license_plate`: string

Example:

```csv
usual_name,make,model,colour,year,mileage,vin,license_plate
Daily Driver,Toyota,Corolla,,2018,92450,2T1BURHE5JC512345,ABC 123
,Mazda,CX-5,,2021,,,
```

Notes:
- Do not include `garage` in the CSV for the web flow. The selected garage is applied by the UI.
- The CLI also ignores any `garage` field in the CSV and uses `--garage` instead.

## Work job import schema

Use this from a car page in the web UI or with `import_csv WorkJob ...` in the CLI.

Required fields:
- `title`: string

Optional fields:
- `car`: string or UUID when the import is not already scoped to a selected car
- `maintenance_type`: string
- `assigned_to`: mechanic username, mechanic email, or user id
- `assigned_shop`: known shop name, known shop email, or shop id
- `planned_date`: `YYYY-MM-DD`, `YYYY-MM`, or `YYYY`
- `is_done`: boolean, or `true`/`false`-like string values
- `done_date`: `YYYY-MM-DD`, `YYYY-MM`, or `YYYY`
- `required_items`: newline-delimited string in quoted CSV cell
- `urgency`: `ahead` or `soon`
- `status`: `pending`, `in_progress`, `done`, or `cancelled`
- `notes`: string

Example for car-scoped web import:

```csv
title,maintenance_type,planned_date,required_items,urgency,status,notes
Oil change,Routine,2026-08-15,"5W-30 oil
Oil filter",soon,pending,Use OEM filter.
```

Example for CLI or non-car-scoped import:

```csv
car,title,planned_date,required_items
2T1BURHE5JC512345,Brake inspection,2026-09,"Brake cleaner
Shop towels"
```

Notes:
- `assigned_to` and `assigned_shop` are mutually exclusive.
- `assigned_to` must resolve to an existing mechanic user.

## Report import schema

Use this from a car page in the web UI or with `import_csv Report ...` in the CLI.

Required fields:
- `job_name`: string
- `date_done`: `YYYY-MM-DD`, `YYYY-MM`, or `YYYY`

Optional fields:
- `car`: string or UUID when the import is not already scoped to a selected car
- `mileage`: integer
- `assigned_to`: mechanic username, mechanic email, or user id
- `assigned_shop`: known shop name, known shop email, or shop id
- `documents`: newline-delimited string in quoted CSV cell
- `photos`: newline-delimited string in quoted CSV cell
- `note`: string

Example for car-scoped web import:

```csv
job_name,date_done,mileage,documents,photos,note
Front brake service,2026-08-03,93120,invoice-2026-08-03.pdf,"before.jpg
after.jpg",Pads and rotors replaced.
```

Example for CLI or non-car-scoped import:

```csv
car,job_name,date_done,note
Daily Driver,Battery replacement,2026-07-01,Installed AGM battery.
```

Notes:
- `assigned_to` and `assigned_shop` are mutually exclusive.
- `assigned_to` must resolve to an existing mechanic user.

# Import behavior summary

- Unknown fields are ignored and reported as warnings.
- If any row has validation errors, the whole import is treated as invalid and nothing is written.
- `dry_run` validates records without saving them.
- In the web flow, garage pages import cars only, and car pages import work jobs or reports only.
