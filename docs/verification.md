# Verification record

The Event Ticketing API replaces the earlier Inventory assignment. Local checks were run on 13 October 2026 with Python 3.12.14 and Django 5.2.18.

- SQLite development run: 18 tests passed, 2 PostgreSQL-only concurrency tests skipped; combined statement/branch coverage was 93.67% and exceeded the 80% gate.
- Django system checks passed.
- `makemigrations` produced the committed initial migration for six domain models.
- OpenAPI generation with `--validate --fail-on-warn` passed.
- Flake8 passed after formatting source and generated migration files.

The two skipped tests use independent PostgreSQL connections to test simultaneous buyers of the same seat and cancellation racing a new claim. A PostgreSQL CI run must pass before claiming those scenarios are verified for this revision. Docker is not installed in the authoring workspace; the hosted workflow's build job is the container verification path.

The workflow does not publish a DockerHub image or deploy the service.
