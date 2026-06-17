# CrowdLabel — Prototype

A minimal Django prototype for a crowd-labeling platform:

- **Real authentication** built on Django's auth system: registration, login,
  logout, and hashed passwords, using a custom user model with a `role`
  (`worker` / `admin`).
- A **role-based redirect** after login: workers → `/tasks`, admins →
  `/dashboard` (decided by reading the user's role, never the username).
- A **worker task screen** showing image questions with radio answers and
  correct/incorrect feedback (hardcoded questions, no models).
- An **admin dashboard** that ranks all workers by accuracy, backed by a small
  SQLite database (`WorkerScore`).

> The database-backed Django admin site (`/admin`) is intentionally not enabled
> — it isn't needed for this prototype.

## Accounts

- **Workers** create their own accounts via the **Register** page (all
  registrations get `role = worker`).
- **Admin** is seeded by a management command, never through registration:

| Username | Password   | Role    | Lands on     |
| -------- | ---------- | ------- | ------------ |
| `admin`  | `admin123` | admin   | `/dashboard` |

Admin credentials are prototype-only — change them before any real deployment.

## Run it locally

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create the database tables (auth, sessions, custom user, scores)
python manage.py migrate

# 4. Seed the admin user (idempotent — safe to run more than once)
python manage.py seed_admin

# 5. Start the dev server
python manage.py runserver
```

Then open http://127.0.0.1:8000/.

> Re-run `migrate` only after changing a model (run `makemigrations` first).
> Re-run `seed_admin` any time; it skips creation if the admin already exists.

### Try the full flow

1. **Register** a worker, answer a few questions at `/tasks`.
2. In another tab, **log in as `admin`** and open `/dashboard`; refresh to see
   the worker's accuracy update. Workers ranked best-to-worst.
3. Confirm access control: while logged in as a worker, visiting `/dashboard`
   returns a "Not authorized" (403) page.

## Folder structure

```
CrowdLabel/
├── manage.py              # Django CLI entry point (runserver, etc.)
├── requirements.txt       # Single dependency: Django
├── README.md              # This file
│
├── db.sqlite3             # Created by `migrate`; users, sessions, scores
│
├── crowdlabel/            # Project config package
│   ├── __init__.py
│   ├── settings.py        # Auth apps/middleware, AUTH_USER_MODEL, SQLite
│   ├── urls.py            # Root URLs; includes the core app's URLs
│   └── wsgi.py            # WSGI entry point
│
└── core/                  # The one app that holds everything
    ├── __init__.py
    ├── apps.py            # App config
    ├── auth_data.py       # role -> route map for the post-login redirect
    ├── tasks_data.py      # Hardcoded labeling questions
    ├── models.py          # User (custom, with role) + WorkerScore
    ├── migrations/        # Migration for User + WorkerScore
    ├── management/
    │   └── commands/
    │       └── seed_admin.py  # `manage.py seed_admin` — creates the admin
    ├── urls.py            # Routes: / register login logout tasks dashboard
    ├── views.py           # register, login, logout, tasks, dashboard
    ├── static/core/
    │   └── style.css      # Minimal shared styling
    └── templates/core/
        ├── base.html          # Base layout (+ logged-in topbar with log out)
        ├── landing.html       # "/"            intro with Log In / Register
        ├── register.html      # "/register"    create a worker account
        ├── login.html         # "/login"       auth form + error message
        ├── tasks.html         # "/tasks"       worker task screen (login req.)
        ├── dashboard.html     # "/dashboard"   admin-only worker ranking
        └── not_authorized.html # 403 page for non-admins hitting /dashboard
```

## How auth and roles work

- **Registration** (`register` view) validates a unique username and a
  6+ character password, then calls `User.objects.create_user(...)` — Django
  hashes the password. New users always get `role = worker`, are logged in, and
  sent to `/tasks`.
- **Login** (`login` view) uses Django's `authenticate()` + `login()`. On
  success it reads the user's `role` and redirects via the `role -> route` map
  in `core/auth_data.py` (never branching on username). On failure it shows
  "Invalid credentials, try again".
- **Access control**: `/tasks` requires login (`@login_required`); `/dashboard`
  additionally checks `role == "admin"` in the view and returns a 403
  "Not authorized" page otherwise — enforced server-side, not by hiding links.

## How scores are recorded

Each worker has a **single** `WorkerScore` row tied to their user account.
Submitting the first question of a quiz resets that row; later questions in the
same run accumulate (via `update_or_create`), so the dashboard always reflects
the worker's **most recent** quiz run. The dashboard lists every worker —
including those who haven't attempted anything (shown as `—` and ranked last).
