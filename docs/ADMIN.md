# CrowdLabel — Admin documentation

Guide for **platform operators** (admin role): projects, task uploads, analytics, review queue, worker-pool distribution, and **customer project handover**. Includes the full **customer** lifecycle from an admin perspective.

Worker-facing features are documented in [WORKER.md](WORKER.md). Shared architecture, models, and file index: [../DOCUMENTATION.md](../DOCUMENTATION.md).

---

## Table of contents

1. [Getting started](#getting-started)
2. [Admin URLs](#admin-urls)
3. [Dashboard](#dashboard)
4. [Projects](#projects)
5. [Customer projects (upload → activation)](#customer-projects-upload--activation)
6. [Task upload (admin CSV)](#task-upload-admin-csv)
7. [Analytics](#analytics)
8. [Review queue & resolution](#review-queue--resolution)
9. [Question distribution](#question-distribution)
10. [Project deadlines](#project-deadlines)
11. [Rate limiting](#rate-limiting)
12. [Handover & customization](#handover--customization)
13. [Production checklist](#production-checklist)

---

## Getting started

### Admin account

Seeded via management command (not self-registration):

```bash
python manage.py seed_admin
```

Default prototype credentials:

| Username | Password | Email | Role |
|----------|----------|-------|------|
| `admin` | `admin123` | `admin@example.com` | admin |

Running `seed_admin` again is safe — if the user already exists it backfills a missing email and leaves everything else untouched. Change the username/password/email before any real deployment (`core/management/commands/seed_admin.py`).

### Log in

- URL: `/login` — username + password
- On success, admins are emailed a **6-digit OTP code** and redirected to `/login/verify` (login 2FA applies to admin and customer roles on **every** login; workers are exempt — see [DOCUMENTATION.md — Auth & verification](../DOCUMENTATION.md#auth--verification))
- In dev, OTP codes print to the console (`DJANGO_EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`) — check the `runserver` terminal
- After OTP verification, admins land on `/dashboard`
- Admins **cannot** register via the UI (`admin` is rejected if submitted on `/register`)
- Login attempts are rate-limited per IP (30/15min) and failures per IP+username (5/15min); OTP sends and verify attempts are separately throttled

### Roles overview

| Role | Registration | Primary landing |
|------|--------------|-----------------|
| Worker | `/register` (Worker toggle) | `/worker` |
| Customer | `/register` (Customer toggle) | `/customer/` |
| Admin | `seed_admin` only | `/dashboard` |

---

## Admin URLs

| URL | Description |
|-----|-------------|
| `/dashboard` | Overview, alerts, project progress, embedded review queue |
| `/admin-tools/projects/` | Project list |
| `/admin-tools/projects/create/` | New project (admin-created) |
| `/admin-tools/projects/<id>/edit/` | Edit / activate customer uploads |
| `/admin-tools/projects/<id>/delete/` | Delete empty projects |
| `/admin-tools/analytics/` | Task + worker analytics (project-scoped) |
| `/admin-tools/question-distribution/` | Manual/auto serving weights |
| `/admin-tools/review-queue/` | Flagged tasks, filters, resolve links |
| `/admin-tools/review-queue/<id>/resolve/` | Per-task resolution |
| `/admin-tools/tasks/<id>/` | Task preview (worker-like UI) |
| `/upload-tasks` | Admin CSV bulk upload to a project |

---

## Dashboard

**Route:** `/dashboard`

### Alerts (top of page)

1. **Project deadlines** — overdue / due today / approaching (sticky styling removed; scrolls with page)
2. **Customer projects need setup** — pending customer uploads with **Review & activate** links

### Projects overview

- Total tasks, active project count
- **Project progress** table: name, customer, deadline (`dd/mm/yyyy`), progress bar, completed/total

### Review queue panel

Embedded review queue table with filters (same data as full review queue page). Task IDs link to worker-style task preview.

### Upload shortcut

Link to `/upload-tasks` for admin CSV imports.

---

## Projects

**Route:** `/admin-tools/projects/`

### Project model (key fields)

| Field | Purpose |
|-------|---------|
| `name`, `customer`, `slug` | Identity; slug auto-generated |
| `owner` | FK to customer user (null for admin-created projects) |
| `status` | `pending` (customer upload) or `active` |
| `is_active` | Worker pool gate (with `status` and per-task `is_active`) |
| `deadline`, `alert_lead_days`, `is_complete` | Deadline alerts |
| `serving_weight`, `serving_boost` | Question distribution |
| `requested_deadline`, `deadline_request_note`, `deadline_request_status` | Customer deadline change requests |

### Admin-created projects

- Created via **New project** → saved as `status=active`, `is_active` toggled on edit
- Tasks uploaded via `/upload-tasks` are `is_active=True` immediately

### List columns

Name, customer, **status** (Needs setup / Active), active flag, task/gold counts, deadline, links to analytics / review queue / edit / delete.

Pending customer uploads are sorted to the top and highlighted.

### Delete

Blocked when tasks exist (`PROTECT` on Task → Project).

---

## Customer projects (upload → activation)

Customers are a third role. They **upload** projects; admins **configure and activate** them. Customers have **read-only** access after upload (except deadline change requests).

### Customer URLs (for reference)

| URL | Customer action |
|-----|-----------------|
| `/register` | Register with **Customer** role |
| `/customer/` | List own projects + progress |
| `/customer/upload/` | Submit project name, deadline, task CSV |
| `/customer/projects/<id>/` | Read-only analytics + deadline request |

Customers cannot access admin or worker pages.

### Customer upload flow

1. Customer fills **project name**, **proposed deadline**, **CSV file**
2. System creates:
   - `Project`: `owner=customer`, `status=pending`, `is_active=False`
   - `Task` rows: `is_active=False`, `project` FK set
3. Customer sees **Pending review** on dashboard

### Customer CSV columns

Expected columns (system columns ignored):

`task_id` (optional/auto), `lang`, `category`, `type`, `topic`, `complexity`, `image`, `task`, `choices`, `correct_answer` (optional → gold task)

Parsed in `core/csv_import.py` → `parse_customer_task_row()`.

### Admin activation workflow

1. Dashboard banner: **Customer projects need setup**
2. Open **Review & activate** → `/admin-tools/projects/<id>/edit/`
3. Review activation hero: customer, task count, proposed deadline, submitted date
4. Adjust settings if needed (name, deadline, lead days)
5. Click **Activate project**

Activation sets:

- `Project.status = active`
- `Project.is_active = True`
- All project tasks: `is_active = True`

Tasks then enter the **shared worker pool**.

Alternatively, checking **Active** on save for a pending project also activates tasks.

### Customer read-only analytics

On `/customer/projects/<id>/`, customers see task-level metrics only:

- Progress (% tasks with ≥1 answer)
- Coverage status, volume by category, complexity, coverage distribution
- Submissions over time, answers by complexity

**Excluded:** worker analytics, gold pass rates, review queue, LLM stats, other customers’ data.

### Deadline change requests

1. Customer submits **requested deadline** + optional note on project detail page
2. `deadline_request_status = pending`
3. Admin sees panel on project edit: **Approve** (sets `deadline`, clears request) or **Dismiss**

---

## Task upload (admin CSV)

**Route:** `/upload-tasks`

1. Select **target project** (required)
2. Upload UTF-8 CSV

### Admin CSV columns

`task_id`, `language`, `category`, `format`, `region_tag`, `complexity`, `num_choices`, `image`, `task`, `choices`, `correct_answer`

Plus optional gold flags: `is_goldtask`, `goldtask`, etc.

Rows upsert on `task_id`. New/updated tasks default to `is_active=True`.

Parser: `core/csv_import.py` → `parse_admin_task_row()`.

---

## Analytics

**Route:** `/admin-tools/analytics/?project=<id>`

Project dropdown at top (defaults to first active project; **All projects** optional).

### Task analytics

- KPIs: total tasks, gold tasks, tasks needing attention (review queue link)
- Coverage status breakdown (derived from answer counts)
- Volume by category / topic / complexity / type (selectable)
- Complexity and coverage distributions
- Gold pass rate by complexity

### Worker analytics

- Total / active workers (configurable active window: 7 or 30 days)
- Accuracy distribution (with low-sample warning)
- Submissions over time (day/week)
- Answers by complexity
- Worker volume table (sortable)

### AJAX filtering

Filter/sort updates partial content without full page reload.

### Not included yet

**AI Analytics** — placeholder in template; `llm_info` exists in sample data but no admin charts yet.

---

## Review queue & resolution

**Route:** `/admin-tools/review-queue/?project=<id>`

### Flags (live-computed)

| Flag | Meaning |
|------|---------|
| Crowd vs truth | Majority disagrees with ground truth |
| Crowd disagreement | Low agreement among workers |
| Gold failure | Gold task accuracy below threshold |

Thresholds in `crowdlabel/settings.py`: `REVIEW_AGREEMENT_THRESHOLD`, `REVIEW_GOLD_FAIL_THRESHOLD`, `REVIEW_LOW_COVERAGE`.

### Filters

Project, category, topics, type, complexity, gold, **resolution** (resolved/unresolved), coverage, flags, sort.

### Resolve view

**Route:** `/admin-tools/review-queue/<id>/resolve/`

- **Crowd stats:** choice distribution, coverage, agreement
- **LLM stats** (non-gold): answer + confidence from `llm_info.probs`
- **Non-gold:** ground truth hidden until **Reveal**; admin selects answer → **Save**
- **Gold:** correct answer shown; no admin input

Resolution persisted on `Task`:

- `admin_resolved_answer`, `resolved_by`, `resolved_at`
- Resolved non-gold rows: green highlight + pill in queue
- **Clear** removes resolution

---

## Question distribution

**Route:** `/admin-tools/question-distribution/`

Controls what share of **non-gold** tasks each **active** project receives in the worker pool.

### Modes (`PlatformConfig.distribution_mode`)

| Mode | Behavior |
|------|----------|
| **Manual** | Admin sets integer `serving_weight` per project (0 = excluded) |
| **Auto** | Weight = `(remaining_tasks / effective_days) × serving_boost` |

### Deficit-based serving

Worker task selection applies weights after difficulty/topic/already-answered filters. Falls back to unweighted selection if no weights apply.

### Settings (`crowdlabel/settings.py`)

- `TARGET_COVERAGE` — task “remaining” if answer count &lt; this (default 3)
- `MIN_DAYS_FLOOR` — minimum days divisor for overdue projects
- `NO_DEADLINE_URGENCY` — baseline weight for projects without deadline

Gold tasks are **not** counted in project split logic.

---

## Project deadlines

| Field | Purpose |
|-------|---------|
| `deadline` | Target date |
| `alert_lead_days` | Days before deadline when status becomes “approaching” |
| `is_complete` | Manual flag — never alerts when true |

`deadline_status`: complete, no_deadline, overdue, due_today, approaching, on_track.

Dashboard shows deadline alert banner for urgent projects only.

---

## Rate limiting

Admin-facing write/AJAX endpoints are throttled per IP (and per user where authenticated), backed by `core/ratelimit.py` and the `CACHES["default"]` backend (LocMem in dev — switch to Redis/Memcached if running multiple app workers, so limits apply across processes):

| Action | Default limit |
|--------|----------------|
| CSV upload (`/upload-tasks`, customer upload) | 5 / hour |
| Analytics AJAX filter (`/admin-tools/analytics/`) | 30 / min |
| Review queue resolve (`/admin-tools/review-queue/<id>/resolve/`) | 60 / min |

Hitting a limit returns HTTP 429 with a retry-after message. Override any scope via `RATE_LIMIT_<SCOPE>` env vars — see `.env.example` and [DOCUMENTATION.md — Auth & verification](../DOCUMENTATION.md#auth--verification) for the full table.

CSV imports are also capped by size/row count regardless of rate limit: `CSV_UPLOAD_MAX_BYTES` (2.5 MB default), `CSV_UPLOAD_MAX_ROWS` (10,000), `CSV_CHOICES_MAX_BYTES` (8 KB per `choices` cell) — configurable in `.env`.

---

## Handover & customization

After handover, operators tune behavior by editing Python modules and settings — there is **no admin UI** for most gamification knobs today.

### 1. Achievement badges (`core/badges.py`)

Edit the `BADGES` dict:

```python
BADGES = {
    "tasks_completed": {
        "label": _("Tasks Completed"),
        "bronze": 10,
        "silver": 25,
        "gold": 50,
        "points_reward": {"bronze": 25, "silver": 50, "gold": 100},
    },
    # ...
}
```

| Key per badge | Meaning |
|---------------|---------|
| `label` | Display name (translatable) |
| `bronze` / `silver` / `gold` | Threshold to earn tier |
| `points_reward` | One-time points granted per tier |

**To add a new achievement badge:**

1. Add entry to `BADGES`
2. Extend `badge_metrics()` if the metric is new
3. Add tier reconciliation in `reconcile_badges()` loop
4. Run server — existing users earn new tiers on next dashboard/trophy visit

**Note:** Changing thresholds does **not** remove already-earned `EarnedBadge` rows.

### 2. Points store (`core/store.py`)

Edit `STORE_BADGES`:

```python
STORE_BADGES = {
    "early_bird": {
        "label": _("Early Bird"),
        "cost": 50,
        "emoji": "🌅",
        "desc": _("..."),
    },
}
```

Add keys freely; `buy_badge()` validates against this dict. Purchases stored in `PurchasedBadge`.

### 3. Points earning (`core/points.py`)

| Constant | Default | Effect |
|----------|---------|--------|
| `COMPLETION_POINTS` | 5 | Per distinct task completed |
| `DIFFICULTY_POINTS` | 1→5, 2/3→10, 4→15 | Correctness bonus by complexity |
| `REFERRAL_REWARD_POINTS` | 30 | Per successful invite |
| `REFERRAL_REWARD_CAP` | 10 | Max referral rewards |
| `POINTS_LEADERBOARD_SIZE` | 5 | Dashboard leaderboard rows |

### 4. Reputation (`core/reputation.py`)

| Constant | Default |
|----------|---------|
| `STARTING_REPUTATION` | 100 |
| `REPUTATION_GAIN` | {1:2, 2:3, 3:3, 4:5} |
| `REPUTATION_LOSS` | {1:1, 2:1, 3:1, 4:2} |
| `REPUTATION_FLOOR` | 0 |

### 5. Streaks (`core/streaks.py`)

| Constant | Default |
|----------|---------|
| `STREAK_FREEZE_THRESHOLD` | 5 | Days before earning a freeze |

### 6. Review & analytics thresholds (`crowdlabel/settings.py`)

```python
REVIEW_AGREEMENT_THRESHOLD = 0.6
REVIEW_GOLD_FAIL_THRESHOLD = 0.6
REVIEW_LOW_COVERAGE = 3
ANALYTICS_ACTIVE_DAYS_DEFAULT = 7
ANALYTICS_MIN_WORKER_VOLUME = 5
TARGET_COVERAGE = 3
MIN_DAYS_FLOOR = 1.0
NO_DEADLINE_URGENCY = 5
SHOW_ANSWER_TIMER = True
```

Restart the server after changing settings.

### 6a. Rate limits & email delivery (`.env`)

Everything below has a safe dev-mode default (console email backend, generous rate limits, in-process cache) and is overridden per-deployment via `.env` — see `.env.example` for the full annotated list:

```env
# OTP delivery — switch from console to SMTP for real inboxes
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_DEFAULT_FROM_EMAIL=CrowdLabel <noreply@yourdept.edu>
DJANGO_EMAIL_HOST=smtp.your-provider.com
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_HOST_USER=your-user
DJANGO_EMAIL_HOST_PASSWORD=your-password

# Rate limits — override any scope, e.g. to loosen login attempts for a pilot
RATE_LIMIT_LOGIN_IP=30
RATE_LIMIT_CSV_UPLOAD=5

# Shared cache across multiple app workers (required for rate limits to be effective)
DJANGO_CACHE_BACKEND=django.core.cache.backends.redis.RedisCache
DJANGO_CACHE_LOCATION=redis://127.0.0.1:6379/1
```

Without SMTP configured, admin/customer login OTP codes and worker signup/reset codes only appear in the server console — fine for a pilot on one machine, not for a real multi-admin deployment.

### 7. Translations (badges, labels, UI copy)

Badge labels and templates use `gettext` / `{% trans %}`.

After editing strings:

```bash
python manage.py makemessages -l ar
# edit locale/ar/LC_MESSAGES/django.po
python manage.py compilemessages
```

Requires GNU `gettext` (`msgfmt`). Arabic translations need native-speaker review for production.

### 8. Styling & theme

| File | Purpose |
|------|---------|
| `core/static/core/style.css` | Global styles, dark/light theme tokens |
| `core/templates/core/base.html` | Bump `?v=` on CSS link after style changes |

Theme toggle stores preference in `localStorage` (`data-theme` on `<html>`).

### 9. Admin account & security

| Item | Location |
|------|----------|
| Seed admin | `python manage.py seed_admin` |
| `SECRET_KEY` | `crowdlabel/settings.py` — replace for production |
| `DEBUG`, `ALLOWED_HOSTS` | `crowdlabel/settings.py` |

### 10. Database migrations

After model changes:

```bash
python manage.py makemigrations
python manage.py migrate
```

Current app migrations: `0001`–`0021` (includes Project, customer role, resolution, distribution, email OTP, unique email, email verification flags). See [DOCUMENTATION.md — Migrations](../DOCUMENTATION.md#migrations) for the per-migration breakdown.

### 11. Sample data

| File | Content |
|------|---------|
| `sample_data/tasks_table.csv` | Pipeline tasks |
| `sample_data/goldtasks_table.csv` | Gold tasks |

Upload via `/upload-tasks` or use customer upload format for customer testing.

---

## Production checklist

- [ ] Change `DJANGO_SECRET_KEY`, set `DJANGO_DEBUG=False`, restrict `DJANGO_ALLOWED_HOSTS` (`.env`)
- [ ] Change admin username/password/email (`seed_admin` or Django shell); admin has no self-service password reset
- [ ] Set `DJANGO_CSRF_TRUSTED_ORIGINS` if serving over a custom domain
- [ ] Configure real SMTP delivery (`DJANGO_EMAIL_*`) — without it, OTP codes only reach the server console
- [ ] Point `DJANGO_CACHE_BACKEND`/`DJANGO_CACHE_LOCATION` at Redis/Memcached if running more than one app worker (rate limits are cache-backed)
- [ ] Consider PostgreSQL instead of SQLite (`DATABASE_URL`)
- [ ] Review Arabic translations (`locale/ar/`)
- [ ] Tune badges, points, thresholds, and rate limits for your pilot
- [ ] Document customer CSV format for your clients
- [ ] Process: customer upload → admin review → activate → monitor review queue

---

## Customer ↔ admin responsibility split

| Step | Customer | Admin |
|------|----------|-------|
| Register | ✓ | — |
| Upload project + CSV | ✓ | — |
| Review task content | — | ✓ |
| Set distribution weights | — | ✓ |
| Activate project | — | ✓ |
| Monitor progress | ✓ (read-only) | ✓ (full analytics) |
| Resolve disputed labels | — | ✓ |
| Request deadline change | ✓ | Approve/dismiss |
| Label tasks | — | Workers (separate role) |
