# Verification record

Checks were run on 13 October 2026 with Python 3.12.14 and Django 5.2.18.

- SQLite development run: 18 tests passed, 2 PostgreSQL-only concurrency tests skipped; combined statement/branch coverage was 93.67% and exceeded the 80% gate.
- Django system checks passed.
- `makemigrations` produced the committed initial migration for six domain models.
- OpenAPI generation with `--validate --fail-on-warn` passed.
- Flake8 passed after formatting source and generated migration files.

The two locally skipped tests use independent PostgreSQL connections to test simultaneous buyers of the same seat and cancellation racing a new claim. [GitHub Actions run #10](https://github.com/theZoid9/halcyon-event-ticketing-api/actions/runs/38375351193) passed its PostgreSQL test job, including these concurrency tests, and then built the Docker image and passed the container health, OpenAPI, and Swagger smoke checks. Docker is not installed in the authoring workspace; the hosted workflow verifies the container.

The workflow does not publish a DockerHub image or deploy the service.
