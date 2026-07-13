# CrowdLabel

Django server-rendered crowd-labeling platform with worker gamification, multi-project admin tools, and customer project uploads.

## Documentation

| Guide | For |
|-------|-----|
| **[docs/WORKER.md](docs/WORKER.md)** | Workers — tasks, points, badges, profile |
| **[docs/ADMIN.md](docs/ADMIN.md)** | Admins — projects, analytics, review queue, customer handover, **customization** |
| **[DOCUMENTATION.md](DOCUMENTATION.md)** | Developers — architecture, models, migrations |

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional; dev works without it when DJANGO_DEBUG=True
python manage.py migrate
python manage.py seed_admin
python manage.py compilemessages
python manage.py runserver
```

For a shared host, set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, and `DJANGO_ALLOWED_HOSTS` in `.env` (see `.env.example`).

For hosted Postgres, set:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME
DJANGO_DB_CONN_MAX_AGE=600
```

If `DATABASE_URL` is empty, local SQLite is used automatically.

For real OTP email delivery, switch from console backend to SMTP in `.env`:

```env
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_DEFAULT_FROM_EMAIL=CrowdLabel <noreply@yourdept.edu>
DJANGO_EMAIL_HOST=smtp.your-provider.com
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_HOST_USER=your-user
DJANGO_EMAIL_HOST_PASSWORD=your-password
DJANGO_EMAIL_USE_TLS=True
DJANGO_EMAIL_USE_SSL=False
```

`compilemessages` requires GNU **gettext** (`msgfmt`). On macOS: `brew install gettext`.

Open http://127.0.0.1:8000/

| Account | Password | Email | Role |
|---------|----------|-------|------|
| `admin` | `admin123` | `admin@example.com` | admin |
| `/register` → Worker | — | your own | worker |
| `/register` → Customer | — | your own | customer |

Registration requires a unique email — a 6-digit code is sent to verify it (prints to the console in dev unless SMTP is configured). Admins and customers also get an email code on every login; workers only verify once at signup. Workers and customers can self-serve a password reset at `/forgot-password`; admins are reset by an operator (`seed_admin` / Django shell).

## URLs at a glance

**Auth:** `/register` · `/login` · `/forgot-password` (workers & customers)

**Workers:** `/worker` · `/tasks` · `/profile/` · `/trophies/` · `/store/`

**Customers:** `/customer/` · `/customer/upload/`

**Admins:** `/dashboard` · `/admin-tools/projects/` · `/admin-tools/analytics/` · `/admin-tools/review-queue/` · `/upload-tasks`

Prototype-only credentials — not production-ready.

## Tests

```bash
python manage.py test core.tests
```
