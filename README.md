# Murang'a County Public Service Request System (MPRS / MINI-ecitizen)

A Django portal for residents to submit county service requests, attach evidence, and track progress. County staff can review requests, filter the work queue, and update statuses.

## Purpose

The portal gives residents a consistent way to report issues involving public services and infrastructure, while giving authorised county staff a central queue for follow-up.

## Features

- Citizen registration, sign-in and CSRF-protected sign-out.
- Request submission with category, location, description and an optional image.
- Server-side image type, integrity and 5 MB size validation.
- Unique request references, timestamps, ownership-protected details and status progress.
- Citizen history with search, status/category filters, pagination and status totals.
- Staff-only dashboard with database-backed metrics, charts, validated search/category/status/date filters, newest/oldest ordering, pagination and status updates.
- Citizen feedback for resolved requests: one editable 1–5 star rating per request, optional comment and improvement suggestion, ownership protection and an audit trail.
- Staff-only feedback review, validated status transitions, private notes, planned actions and publishable citizen responses.
- Service-quality summaries with rating distribution, category averages, monthly feedback totals, response/resolution timing statistics and resolved requests without feedback.
- Staff can track multi-feedback improvement actions with responsible officers, priorities, status, target dates and completion timestamps.
- Uploaded images served only to the owner or authorised staff.

## Technology

- Python 3.11 or 3.12 (the pinned Django 5.0.14 release supports this range alongside Pillow 13.0.0).
- Django 5.0.14.
- Pillow 13.0.0.
- SQLite for local development.
- `Africa/Nairobi` timezone for displayed dates and calendar-day filters.
- Bootstrap 5, Bootstrap Icons and Chart.js via CDN.

## Project Structure

```text
manage.py                 Django management entry point
county_portal/            Settings and top-level URL configuration
service_requests/         Models, forms, views, tests and templates
service_requests/migrations/  Database schema history
static/css/               Application styles
media/                    Local uploaded request images (gitignored)
requirements.txt          Runtime Python dependencies
```

The `src/mprs` package is a separate scaffold and is not required to run the Django application. Use `manage.py` for application commands.

## Prerequisites

- Python 3.11 or 3.12 for the current dependency pins.
- PowerShell on Windows, or a compatible shell on other platforms.

## Install

From the project root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If `.venv` already exists, activate it and install the pinned requirements. Django settings do not automatically load `.env` files; set variables in the process environment or your hosting platform.

The default is fail-closed (`DEBUG=False`): the application requires a secret and allowed hosts unless explicitly in test mode. For local development, set `DEBUG=True` and local hosts in the current PowerShell session; an ephemeral process secret is generated if none is supplied:

```powershell
$env:DJANGO_DEBUG = "true"
$env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1"
```

## Database and Run

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Register a resident account to submit a request. Grant an existing account `is_staff=True` through Django admin or the management shell to access the staff dashboard.

## Environment Configuration

See [.env.example](.env.example) for variable names. It is a reference template, not an automatically loaded file.

For production, set all of the following through the host's secret/environment manager:

- `DJANGO_DEBUG=false`.
- `DJANGO_SECRET_KEY` to a unique, randomly generated secret of at least 50 characters.
- `DJANGO_ALLOWED_HOSTS` to a comma-separated list of the real hostnames.

With `DEBUG=False`, startup fails if the secret or allowed hosts are missing. HTTPS redirects, secure session/CSRF cookies and one-year HSTS for the configured host are enabled in that mode. HSTS subdomains and preload are intentionally disabled until an approved production domain and full subdomain HTTPS policy exist. If TLS terminates at a trusted reverse proxy, set `DJANGO_TRUST_X_FORWARDED_PROTO=true` only when that proxy removes incoming forwarded-proto headers and sets its own. Run `python manage.py collectstatic` during production packaging, then configure a production static-file server and backup/retention policy before deployment. SQLite and Django's development server are for local assessment/testing, not production hosting.

Uploaded request images are private to their owner and staff through the application route. Do not expose `MEDIA_ROOT` through a public web-server alias. The local `media/` directory is ignored by Git and should be handled as private user data.

## Tests and Checks

Run from the activated virtual environment:

```powershell
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pip check
```

Tests use isolated Django test databases and temporary media storage. They cover registration/login/logout, CSRF, request validation and uploads, ownership, staff permissions/status changes, dashboard totals/date filtering/sorting, feedback ownership/eligibility/review/publication, improvement-action workflows and recorded response-time calculations.

## Known Limitations

- The original assessment brief/rubric was not present in the workspace; see [ASSESSMENT_AUDIT.md](ASSESSMENT_AUDIT.md).
- Historical request timestamps are not backfilled; response and resolution metrics include only records with actual captured timestamps. Requests created before status-history tracking cannot be assigned an invented response/resolution time.
- Service-level targets are not configured. Improvement-action due dates are set by staff as operational targets and are not represented as official service commitments.
- Submitted feedback remains attached if a request is reopened; citizens may view it then edit only after the request is resolved again.
- Bootstrap, icons, fonts and Chart.js are loaded from CDNs; charts have a text fallback, but a fully offline interface requires local static assets.
- Django 5.0.14 is pinned for the existing project and is outside its upstream support window. Upgrade to a supported Django LTS release and rerun the full suite before any public deployment.
- Email verification, notifications and production hosting/storage are not implemented.

## Submission Checklist

- [ ] Use Python 3.11+ and install `requirements.txt` in a virtual environment.
- [ ] Run migrations, create a staff user, then start the app with `python manage.py runserver`.
- [ ] Run the full test suite, Django system check, migration drift check and `pip check`.
- [ ] Confirm the assessment-specific deliverables against the original rubric when available; it was not found in this workspace.
- [ ] Do not submit `.env`, local database files, private uploads, or real credentials.
- [ ] Before production deployment, upgrade Django, configure secret/host values, HTTPS, static/media hosting, backups and an operational data-retention policy.
