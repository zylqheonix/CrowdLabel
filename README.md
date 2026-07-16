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
python manage.py migrate
python manage.py seed_admin
python manage.py compilemessages
python manage.py runserver
```

Dev runs out of the box on SQLite with no `.env` needed. `compilemessages` requires GNU **gettext** (`msgfmt`). On macOS: `brew install gettext`.

Configuration knobs (email, database, feature thresholds, etc.) are read from environment variables — see [`.env.example`](.env.example) for the full list and [DOCUMENTATION.md — Configuration](DOCUMENTATION.md#configuration-crowdlabelsettingspy).

Open http://127.0.0.1:8000/

| Account | Password | Email | Role |
|---------|----------|-------|------|
| `admin` | `admin123` | `admin@example.com` | admin |
| `/register` → Worker | — | your own | worker |
| `/register` → Customer | — | your own | customer |

Registration requires a unique email — a 6-digit code is sent to verify it (in dev it prints to the `runserver` console). Admins and customers also get an email code on every login; workers only verify once at signup. Workers and customers can self-serve a password reset at `/forgot-password`; admins are reset by an operator (`seed_admin` / Django shell).

## URLs at a glance

**Auth:** `/register` · `/login` · `/forgot-password` (workers & customers)

**Workers:** `/worker` · `/tasks` · `/profile/` · `/trophies/` · `/store/`

**Customers:** `/customer/` · `/customer/upload/`

**Admins:** `/dashboard` · `/admin-tools/projects/` · `/admin-tools/analytics/` · `/admin-tools/review-queue/` · `/upload-tasks`

Prototype-only credentials — change them before sharing the app.

## Customizing the platform

Most behavior is tuned by editing small Python config blocks — badges, the points store, points earning, streaks, reputation, and review thresholds. Start here:
**[docs/ADMIN.md — Handover & customization](docs/ADMIN.md#handover--customization)**.

## Status & roadmap

CrowdLabel is a working prototype. Known not-yet-built areas and suggested next steps are listed in **[DOCUMENTATION.md — Future work & roadmap](DOCUMENTATION.md#future-work--roadmap)**. Most notably, **AI / LLM analytics are not implemented yet** — the sample data carries model metadata (`llm_info`) and the UI has a placeholder, but no LLM-driven charts or scoring exist.

## Tests

```bash
python manage.py test core.tests
```
