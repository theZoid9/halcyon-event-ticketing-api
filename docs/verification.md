# Verification record

Verified on 12 October 2026 using Python 3.12.14 and Django 5.2.18.

## Executed locally

- PostgreSQL 17.11: **41 tests passed**, including all four concurrent transaction tests.
- SQLite initial domain run: **35 passed, 4 PostgreSQL-only tests skipped**; two additional
  platform tests were subsequently added and passed in the PostgreSQL run.
- Coverage includes statements and branches and exceeds the configured 80% minimum;
  the final measured percentage is approximately **98.6%** with generated migrations excluded.
- Django system checks and migration drift checks passed.
- OpenAPI generation passed `--validate --fail-on-warn`.
- Black formatting and flake8 checks are run before packaging.

The PostgreSQL run used a temporary workspace-local database bound to loopback, with isolated test
data and independent connections for concurrent operations. The database process was shut down
after verification. The runtime came from the official
[EDB PostgreSQL binaries distribution](https://www.enterprisedb.com/download-postgresql-binaries).

## Endpoint coverage

`tests/test_inventory.py` exercises list/create/retrieve/PUT/PATCH/delete for supplier, product,
warehouse, stock, and order resources. It checks both roles, unauthenticated requests, ownership,
invalid input, nested line replacement, immutable fields, model constraints, stock rollback,
allocation, cancellation, fulfilment, protected deletion, and retry behavior.

`tests/test_platform.py` exercises user CRUD, login/logout, invalid credentials, throttling,
password/deactivation token revocation, health success/database failure, docs, malformed JSON,
unsupported methods, and standardized errors.

`tests/test_concurrency.py` tests competing orders, repeated simultaneous allocation,
fulfilment racing cancellation, and stock adjustment racing allocation on PostgreSQL.

## Container and hosted checks

Docker is not installed in the authoring workspace; a local Docker image build is not claimed.
The GitHub Actions workflow tests with PostgreSQL 17, validates migrations and the committed schema,
then builds the Docker image and starts Compose to verify health, schema, and documentation endpoints.
Consult the repository's Actions page for the actual hosted run status; committed workflow code
alone is not evidence of a passing hosted build.

No DockerHub publication or production deployment has been performed.
