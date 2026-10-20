# Technical Assessment Audit

**Audit state:** 2026-10-20. The original assessment brief/rubric was not found in the workspace. The known weighted criteria are assessed below; the unprovided final 20% is deliberately not guessed.

## Known Rubric

| Criterion | Weight | Evidence and verification | Gaps and priority |
|---|---:|---|---|
| Functionality | 35% | `service_requests/views.py`, `forms.py`, templates and 34 Django tests cover registration/login/logout, citizen submission/history, filtering/date ranges/sorting/pagination, upload checks, staff workflow, status visibility and database-backed metrics. | No email verification, notifications or status-change audit log. Medium if required by the missing rubric. |
| Code quality and structure | 25% | Django project/app separation, model-backed forms, ownership-filtered queries, existing initial migration, and `makemigrations --check --dry-run`. | `src/mprs` remains a separate package scaffold; it is not the Django run target. Django 5.0.14 is unsupported upstream. High before public deployment; upgrade and retest. |
| UI/UX design | 20% | Shared templates and styles, responsive sweep at 375/430/768/1024/1440, keyboard focus checks, chart/table behavior, and status/error/empty states. | CDN-hosted UI assets need internet access. Medium for offline assessment; vendor static assets if offline operation is required. |
| Remaining rubric criteria | 20% | Not verifiable: the original brief/rubric was unavailable, and no substitute weighting is assumed. | Obtain the official rubric and map its final criteria before submission. |

## Security and Workflow Findings

- Citizen list queries and detail/image access are restricted to the authenticated owner; staff are separately authorised for administrative views and status updates.
- Non-owner detail/image reads return 404. Citizen status writes are rejected. CSRF middleware and tokens protect POST forms; logout is POST-only.
- Request text is rendered through Django template autoescaping. Uploaded images are checked server-side for allowed extension, valid image content and a 5 MB maximum. Private image delivery requires owner or staff access.
- Dashboard metrics and charts are aggregated from request records; no sample/placeholder statistics are used.
- The current schema has no assignee, department, administrator-note, citizen-response, rejected/closed status, or audit-event fields. Those workflows are not represented as functional features and were not fabricated or added without confirmed assessment requirements.
- Production mode defaults to `DEBUG=False` and requires environment-provided `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`; it redirects to HTTPS and enables secure cookies and one-year HSTS without subdomains/preload. Forwarded-proto trust is opt-in and must only be enabled behind a proxy that overwrites that header. Local development explicitly enables debug and uses an ephemeral process secret when none is supplied. Tests use an isolated ephemeral key.
- The workspace is not a Git repository, so Git status/diff could not be inspected. No migration files or runtime dependency pins were changed. `pyproject.toml` metadata was updated to match the verified Python support range.

## Verification Results

- `python manage.py test --verbosity 2`: 34 tests passed in the final landing-page audit run.
- `python manage.py check`: no issues.
- `python manage.py makemigrations --check --dry-run`: no model changes detected.
- `python -m pip check`: no broken requirements after repairing the incompatible Pillow wheel in `.venv` (the project pin was unchanged).
- `python manage.py check --deploy` with production-like environment values: reports only `security.W005` and `security.W021` because HSTS subdomains and preload remain disabled pending an approved domain/subdomain HTTPS policy. These are documented, intentional deployment advisories.
- Browser smoke tests previously covered responsive widths and key citizen/admin pages. Private image access and end-to-end status updates are covered by automated tests.

## Outstanding Items

1. **High before public deployment:** replace Django 5.0.14 with a currently supported Django LTS version and run all checks/tests on that version.
2. **High before deployment:** set production environment variables and configure real TLS termination, static-file hosting, backups and private media storage/retention.
3. **Assessment-dependent:** compare the application with the official rubric once supplied; the final 20% remains unassessed.
4. **Assessment-dependent:** implement email verification, notifications or historical status logging only if the official requirements call for them.