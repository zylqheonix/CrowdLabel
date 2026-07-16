# CrowdLabel — Technical documentation

Server-rendered Django crowd-labeling platform with three roles: **workers** (label tasks), **customers** (upload projects), and **admins** (operate the platform).

**Stack:** Django 6, SQLite, HTML templates, single CSS file, minimal JavaScript. English + Arabic (RTL) via gettext.

---

## Documentation map

| Document | Audience | Contents |
|----------|----------|----------|
| **[docs/WORKER.md](docs/WORKER.md)** | Workers / crowd labelers | Registration, tasks, points, badges, store, streaks, profile, referrals |
| **[docs/ADMIN.md](docs/ADMIN.md)** | Platform operators | Dashboard, projects, customer handover, analytics, review queue, distribution, **customization guide** |
| **This file** | Developers | Architecture, models, migrations, module index |

---

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py compilemessages   # Arabic UI
python manage.py seed_admin
python manage.py runserver
```

Open http://127.0.0.1:8000/

| Account | Password | Role | Lands on |
|---------|----------|------|----------|
| `admin` | `admin123` | admin | `/login/verify` (email OTP) → `/dashboard` |
| Register → Worker | — | worker | `/register/verify-worker` (email OTP) → `/setup/` → `/worker` |
| Register → Customer | — | customer | `/register/verify-customer` (email OTP) → `/customer/` |

Prototype credentials are **not** production-safe. OTP codes print to the console in dev (no SMTP configured by default).

---

## Architecture

```
Browser
   │
   ▼
crowdlabel/urls.py  →  core/urls.py  →  core/views.py
                                              │
        ┌─────────────────────────────────────┼──────────────────────────┐
        ▼                 ▼                 ▼                          ▼
  core/models.py   core/projects.py   core/analytics.py          templates/
  core/review_queue   core/distribution   core/customer_analytics
  points, badges, streaks, reputation, history, topics, store, csv_import
  security, two_factor, ratelimit, context_processors
```

### Design principles

- **Server-rendered templates** — no SPA; AJAX only where noted (analytics filters, activity calendar).
- **Append-only answers** — `WorkerAnswer` rows are never updated; latest row per task used for display metrics.
- **Live-computed admin metrics** — analytics, review queue, distribution weights computed on request.
- **Role gating** — `@worker_required`, `@customer_required`, `@admin_required` on views.
- **Project scoping** — `core/projects.py` is the single source for admin/worker queryset filters.
- **Worker pool** — active tasks require `task.is_active`, `project.is_active`, `project.status=active`, and `project.is_active` on distribution-eligible projects.
- **Email-verified accounts** — every user has a unique email; workers and customers verify it via OTP once at signup. Admins and customers additionally verify via OTP on every login (`core/two_factor.py`).
- **Rate limiting** — auth and write-heavy endpoints are throttled per IP/user via a shared cache (`core/ratelimit.py`).

---

## Roles

| Role | Value | Registration | Redirect after login |
|------|-------|--------------|----------------------|
| Worker | `worker` | `/register` (default) | `worker_dashboard` |
| Customer | `customer` | `/register` | `customer_dashboard` |
| Admin | `admin` | `seed_admin` only | `dashboard` |

Registration allowlist: `REGISTERABLE_ROLES = {worker, customer}` in `core/auth_data.py`. Admin cannot self-register.

---

## URL index

### Public / shared

| URL | Access |
|-----|--------|
| `/` | Landing |
| `/register` | Self-registration (worker or customer, role toggle) |
| `/register/verify-worker` | Worker signup email OTP verification |
| `/register/verify-customer` | Customer signup email OTP verification |
| `/customer/register` | Legacy alias — redirects to `/register?role=customer` |
| `/login` | All roles (username + password) |
| `/login/verify` | Login email OTP verification (admin, customer) |
| `/forgot-password` | Worker password reset request (email) |
| `/forgot-password/verify` | Worker password reset OTP verification |
| `/forgot-password/reset` | Worker password reset form |
| `/logout` | Authenticated |
| `/settings/` | Generic settings landing — redirects by role (worker → security tab, customer → dashboard, admin → dashboard) |

See [Auth & verification](#auth--verification) for the full signup/login/reset flow.

### Worker

See [docs/WORKER.md](docs/WORKER.md) for full list (`/worker`, `/tasks`, `/profile/*`, `/store/`, etc.). Notably also `/settings/username`, `/settings/password` (POST-only, backing `/profile/security/`) and `/worker/activity-month/` (AJAX calendar nav).

### Customer

| URL | Access |
|-----|--------|
| `/customer/` | Customer dashboard |
| `/customer/upload/` | Project + CSV upload |
| `/customer/projects/<id>/` | Read-only analytics + deadline request |

### Admin

| URL | Access |
|-----|--------|
| `/dashboard` | Admin dashboard |
| `/admin-tools/projects/` | Project CRUD |
| `/admin-tools/analytics/` | Analytics |
| `/admin-tools/review-queue/` | Review queue |
| `/admin-tools/question-distribution/` | Serving weights |
| `/upload-tasks` | Admin CSV upload |

Full admin guide: [docs/ADMIN.md](docs/ADMIN.md).

---

## Auth & verification

All roles require a unique email address (`User.email`, enforced unique from migration `0018`).

### Signup verification (once per account)

- **Worker**: registers → `worker_email_verified=False` → OTP sent → `/register/verify-worker` → verified → redirected to onboarding (`/setup/`)
- **Customer**: registers → `customer_email_verified=False` → OTP sent → `/register/verify-customer` → verified → redirected to `/customer/`
- If an unverified user later logs in with correct credentials, `login` re-triggers the same signup OTP flow instead of completing login

### Login 2FA (every login)

- `core/two_factor.py` → `roles_requiring_login_2fa()` returns `{admin, customer}`
- After password check, admins and customers are sent an OTP and redirected to `/login/verify`
- Workers skip this — they only verify email once at signup, not on every login

### Password reset (workers & customers)

- Which roles may self-recover is defined by `core/two_factor.py` → `roles_allowing_password_reset()` (currently `{worker, customer}`)
- `/forgot-password` accepts an email, looks up a matching **worker or customer** account by email, and — if found — emails a reset OTP
- Response is intentionally generic ("if an account exists...") and no email is sent for non-eligible/absent emails, so admin existence and account existence are never revealed
- `/forgot-password/verify` → `/forgot-password/reset` completes the reset; on success all of that user's other sessions are invalidated (`invalidate_user_sessions`)
- **Admins are excluded on purpose** — they are seeded, not self-registered; reset them via Django shell or `seed_admin`

### OTP mechanics (`core/two_factor.py`, `EmailOTP` model)

- 6-digit numeric code, hashed with `SECRET_KEY` before storage (`code_hash`), 10-minute TTL
- Sent via `send_mail` using `DEFAULT_FROM_EMAIL` (console backend in dev, SMTP in production — see `.env.example`)
- Resend available with a cooldown (`_resend_otp_with_cooldown`); verify attempts are rate-limited (`otp_verify_fail`)

### Rate limiting (`core/ratelimit.py`)

Cache-backed, cache key = scope + hashed (IP, user, etc.) parts. Default scopes and limits (requests / window seconds), all overridable via env vars (`RATE_LIMIT_*`) or `settings.RATE_LIMITS`:

| Scope | Default | Purpose |
|-------|---------|---------|
| `login_ip` | 30 / 900s | Login attempts per IP |
| `login_fail` | 5 / 900s | Failed logins per IP+username |
| `register` | 10 / 3600s | Registrations per IP |
| `otp_send_ip` / `otp_send_user` | 10 / 3600s, 5 / 3600s | OTP email sends |
| `otp_verify_fail` | 5 / 900s | Failed OTP verification attempts |
| `forgot_password` / `forgot_password_email` | 5 / 3600s, 3 / 3600s | Reset requests per IP / per email |
| `reset_password` | 10 / 3600s | Reset submissions |
| `task_submit` | 120 / 60s | Worker task answers |
| `activity_month` | 60 / 60s | Profile calendar AJAX |
| `analytics` | 30 / 60s | Admin analytics AJAX filters |
| `csv_upload` | 5 / 3600s | Admin + customer CSV imports |
| `store_buy` | 20 / 60s | Points store purchases |
| `invite_create` | 10 / 3600s | Referral invite creation |
| `review_resolve` | 60 / 60s | Review queue resolutions |

Exceeding a limit returns HTTP 429 with a translated retry-after message (`too_many_requests_message`).

### Password policy

Enforced by `AUTH_PASSWORD_VALIDATORS` (min length 8, common-password blocklist, no all-numeric, no similarity to username/email). Every entry point that sets a user-chosen password routes through `core/security.py` → `password_error()` so the rules are identical across registration, worker password reset, and the logged-in password change (which uses Django's `PasswordChangeForm`). The seeded prototype admin (`seed_admin`) is created via `create_user()` and intentionally bypasses these validators — change its credentials before deployment.

### Other security helpers (`core/security.py`)

- `password_error(password, *, user=None)` — runs the configured validators; returns a single error string or `None`
- `safe_next_url()` — validates `?next=` redirect targets against the current host before use
- `invalidate_user_sessions()` — deletes all stored sessions for a user (used after password/username changes)

---

## Data models (`core/models.py`)

### `User`

Extends `AbstractUser`. Field `role`: `worker` | `admin` | `customer`. `email` is required and unique (case-insensitive; normalized to lowercase on save). `worker_email_verified` / `customer_email_verified` gate the post-signup OTP flow (see [Auth & verification](#auth--verification)) — default `True` so existing/seeded users aren't locked out retroactively.

### `Project`

Customer labeling project. Tasks belong to one project.

Key fields: `name`, `customer`, `slug`, `owner` (FK, nullable), `status` (`pending`|`active`), `is_active`, `deadline`, `alert_lead_days`, `is_complete`, `serving_weight`, `serving_boost`, deadline request fields (`requested_deadline`, `deadline_request_note`, `deadline_request_status`), `activated_at`, `customer_activation_seen_at`, `created_at`.

### `Task`

| Field | Notes |
|-------|-------|
| `project` | FK → Project (PROTECT) |
| `task_id` | Unique business key |
| `region_tag` | Topic for worker preferences |
| `complexity` | 1=easy, 2/3=medium, 4=hard |
| `choices` | JSON dict |
| `correct_answer` | Nullable — unscored if null |
| `is_goldtask` | Validation task |
| `is_active` | Worker pool gate (False until customer project activated) |
| `admin_resolved_answer`, `resolved_by`, `resolved_at` | Review resolution |

### `WorkerAnswer`

Append-only: `user`, `task`, `selected_answer`, `is_correct`, `verified`, `time_taken_seconds`, `created_at`.

### Gamification models

`WorkerScore` (quiz run stats + `preferred_topics`), `WorkerStreak`, `EarnedBadge`, `PointsSpend`, `Invite`, `PurchasedBadge`.

### `PlatformConfig`

Singleton (`pk=1`): `distribution_mode` (`manual`|`auto`).

### `EmailOTP`

One-time codes for signup verification, login 2FA, and worker password reset. Fields: `user`, `purpose` (`login_2fa`|`worker_signup`|`customer_signup`|`password_reset`), `code_hash` (SHA-256, never stores the raw code), `created_at`, `expires_at`, `used_at`. See [Auth & verification](#auth--verification).

---

## Migrations

`core/migrations/0001` – `0021`:

| Migration | Summary |
|-----------|---------|
| 0001 | User, WorkerScore |
| 0002 | Task |
| 0003 | WorkerAnswer |
| 0004 | Rename honeypot → goldtask, complexity |
| 0005–0010 | Badges, streaks, points spend, invite, purchased badges, preferred topics |
| 0011 | Project + Task.project FK |
| 0012 | Project deadlines |
| 0013 | Task resolution fields |
| 0014 | Question distribution (serving weights, PlatformConfig) |
| 0015 | Customer role, Project owner/status, Task.is_active |
| 0016 | Project activation notice fields (`activated_at`, `customer_activation_seen_at`) |
| 0017 | `EmailOTP` model |
| 0018 | `User.email` unique constraint |
| 0019 | `User.worker_email_verified` |
| 0020 | `User.customer_email_verified` |
| 0021 | `WorkerAnswer` unique constraint on (user, task) |

---

## Business logic modules

| Module | Purpose |
|--------|---------|
| `core/points.py` | Points earning, balance, spend, leaderboard |
| `core/badges.py` | Achievement badges (`BADGES` config) |
| `core/store.py` | Points store catalog (`STORE_BADGES`) |
| `core/streaks.py` | Daily streak + freeze |
| `core/reputation.py` | Quality score (read-only) |
| `core/history.py` | Answer history grids |
| `core/topics.py` | Topic preference filter |
| `core/projects.py` | Project scoping querysets |
| `core/analytics.py` | Admin analytics builders |
| `core/customer_analytics.py` | Customer-safe project analytics |
| `core/review_queue.py` | Review queue + resolve context |
| `core/distribution.py` | Project serving weights + deficit picker |
| `core/csv_import.py` | Admin + customer CSV parsers (row parsing, size/row caps) |
| `core/context_processors.py` | `build_admin_deadline_alerts()` — injected into every admin template context |
| `core/two_factor.py` | Email OTP generation, sending, and verification |
| `core/ratelimit.py` | Cache-backed rate limiting (decorator + manual helpers) |
| `core/security.py` | Safe redirect validation, session invalidation |
| `core/admin.py` | Django admin registrations (`Project`, `WorkerScore`, `PointsSpend`, `Invite`, `PurchasedBadge`) |

**Customization after handover:** see [docs/ADMIN.md — Handover & customization](docs/ADMIN.md#handover--customization).

---

## Configuration (`crowdlabel/settings.py`)

Secrets and environment-specific values load from `.env` (see `.env.example`); everything below has a code default so the app runs with no `.env` in dev.

### Feature/behavior settings

| Setting | Default | Used by |
|---------|---------|---------|
| `SHOW_ANSWER_TIMER` | `True` | Worker task UI |
| `REVIEW_AGREEMENT_THRESHOLD` | `0.6` | Review queue |
| `REVIEW_GOLD_FAIL_THRESHOLD` | `0.6` | Review queue |
| `REVIEW_LOW_COVERAGE` | `3` | Review queue, analytics |
| `TARGET_COVERAGE` | `3` | Distribution auto-mode |
| `MIN_DAYS_FLOOR` | `1.0` | Distribution auto-mode |
| `NO_DEADLINE_URGENCY` | `5` | Distribution auto-mode |
| `ANALYTICS_ACTIVE_DAYS_DEFAULT` | `7` | Analytics |
| `ANALYTICS_MIN_WORKER_VOLUME` | `5` | Analytics |

### Environment-driven settings (`DJANGO_*` env vars, see `.env.example`)

The app-relevant knobs. (Additional HTTPS/cookie-hardening variables exist in `settings.py` for when the app is served over TLS — see `.env.example` — but they are not needed for local development.)

| Setting | Env var | Default | Purpose |
|---------|---------|---------|---------|
| `DEBUG` | `DJANGO_DEBUG` | `True` | Dev vs. production mode |
| `SECRET_KEY` | `DJANGO_SECRET_KEY` | dev-only fallback | Django signing key, also used to hash OTP codes |
| `DATABASES` | `DATABASE_URL`, `DJANGO_DB_CONN_MAX_AGE` | empty → local SQLite | Postgres via `dj_database_url` when set |
| `CSV_UPLOAD_MAX_BYTES` / `CSV_UPLOAD_MAX_ROWS` / `CSV_CHOICES_MAX_BYTES` | same names | 2,621,440 / 10,000 / 8,192 | CSV import caps (`core/csv_import.py`) |
| `CACHES["default"]` | `DJANGO_CACHE_BACKEND`, `DJANGO_CACHE_LOCATION` | LocMem | Backing store for rate-limit counters |
| `RATE_LIMITS` | `RATE_LIMIT_*` (one per scope) | see [Auth & verification](#auth--verification) | Per-scope request throttling |
| `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `EMAIL_HOST*` | `DJANGO_EMAIL_*` | console backend in dev | OTP email delivery |

---

## Key templates

| Template | Role |
|----------|------|
| `base.html` | Shell, header, theme toggle |
| `landing.html`, `login.html`, `register.html`, `not_authorized.html` | Public / shared |
| `verify_worker_signup_otp.html`, `verify_customer_signup_otp.html`, `verify_login_otp.html` | Signup / login OTP verification |
| `forgot_password.html`, `verify_reset_otp.html`, `reset_password.html` | Worker password reset |
| `worker_dashboard.html`, `tasks.html`, `task_detail.html`, `worker_setup.html`, `history.html` | Worker |
| `profile_base.html`, `profile_activity.html`, `profile_preferences.html`, `profile_security.html`, `profile_wallet.html` | Worker profile tabs |
| `trophy_room.html`, `store.html` | Worker badges / points store |
| `customer_dashboard.html`, `customer_upload.html`, `customer_project_detail.html` | Customer |
| `dashboard.html`, `projects.html`, `project_form.html`, `project_delete.html` | Admin |
| `analytics.html`, `review_queue.html`, `review_queue_resolve.html`, `question_distribution.html`, `upload_tasks.html` | Admin |
| `partials/review_queue_panel.html` | Admin dashboard embed |
| `partials/admin_deadline_banner.html` | Dashboard deadlines |
| `partials/admin_pending_setup_banner.html` | Dashboard customer setup alert |

Static: `core/static/core/style.css`

---

## Sample data

- `sample_data/tasks_table.csv` — pipeline tasks with LLM metadata
- `sample_data/goldtasks_table.csv` — gold tasks

---

## Tests (`core/tests/`)

```bash
python manage.py test core.tests
```

| File | Covers |
|------|--------|
| `test_auth.py` | Registration, login, OTP verification, password reset |
| `test_admin.py` | Admin dashboard, projects, deadlines |
| `test_customer.py` | Customer upload, activation, deadline requests |
| `test_csv_import.py` | Admin + customer CSV parsing |
| `test_distribution.py` | Question distribution weighting |
| `test_points.py` | Points earning/spending |
| `test_ratelimit.py` | Rate limit decorator/helpers |
| `test_review_queue.py` | Review queue flags + resolution |
| `test_security_hardening.py`, `test_security_settings.py` | Redirect safety, session invalidation, secure settings toggles |
| `test_worker_pool.py` | Worker task pool eligibility/filters |
| `helpers.py` | Shared test fixtures/factories |

---

## Future work & roadmap

Things that are **not built yet**, and where a future developer would start.

### AI / LLM analytics — not implemented

The single biggest gap. The sample data (`sample_data/tasks_table.csv`) already carries per-task model metadata in an `llm_info` column (model answer + confidence probabilities), and the admin analytics template has a placeholder **"AI Analytics"** area — but **no LLM-driven charts, scoring, or model-vs-crowd comparison exist in the Django app today.** Nothing calls an LLM at runtime.

Where to start:
- The standalone Streamlit sandbox (`app.py`) already prototypes what's *possible* from this metadata (model confidence vs. crowd accuracy, disagreement, etc.) — a good reference for which charts to port into the admin analytics page.
- `core/analytics.py` builds the admin analytics context; new AI charts would be added there and surfaced in `templates/core/analytics.html`.
- `Task.correct_answer` / `WorkerAnswer` already give the crowd side of any model-vs-crowd comparison.

### Other suggested next steps

- **Registration hygiene** — a failed OTP send at signup currently leaves an unverified user row (email gets claimed even though verification never completed). Consider deleting the user on send failure, or letting a re-registration reclaim an unverified account.
- **Admin password recovery** — admins have no self-service reset by design; a future admin-initiated reset (or making a second admin) would remove the reliance on `seed_admin`/shell.
- **Bulk worker onboarding** — for closed pilots, a management command that creates pre-verified worker accounts from a list would beat manual Django-admin entry.
- **Move gamification knobs into the admin UI** — badges, store items, and points rules are Python config today (see customization below); a future admin screen could make them editable without code.

**Customizing existing behavior** (badges, points store, points, streaks, reputation, review thresholds) does **not** require new development — it's config editing, fully documented in **[docs/ADMIN.md — Handover & customization](docs/ADMIN.md#handover--customization)**.

---

## Related files

| Path | Purpose |
|------|---------|
| `README.md` | Short quick start |
| `app.py` | Streamlit research sandbox (separate from Django app) — reads `sample_data/*.csv` directly; prototypes possible LLM/analytics visuals, no dependency on the Django app |
| `manage.py` | Django CLI |
| `core/management/commands/seed_admin.py` | Create admin user (username `admin`, email `admin@example.com`) |
| `locale/ar/` | Arabic translations |
| `.env.example` | Template for local `.env`; documents every environment variable above |
| `core/tests/` | Automated test suite (`python manage.py test core.tests`) |

*Last updated: reflects email verification (OTP) at signup, login 2FA for admin/customer, worker & customer password reset, and rate limiting. AI/LLM analytics are not yet implemented (see Future work & roadmap).*
