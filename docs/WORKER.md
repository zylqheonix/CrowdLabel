# CrowdLabel — Worker documentation

Guide for **workers** (the crowd labeling role). Workers answer image-based multiple-choice tasks, earn points, and use profile tools. Workers never see project boundaries, admin tools, or customer uploads.

For platform setup and admin tools, see [ADMIN.md](ADMIN.md). For architecture and shared technical reference, see [../DOCUMENTATION.md](../DOCUMENTATION.md).

---

## Table of contents

1. [Getting started](#getting-started)
2. [URLs & navigation](#urls--navigation)
3. [Onboarding](#onboarding)
4. [Dashboard](#dashboard)
5. [Labeling tasks](#labeling-tasks)
6. [Points economy](#points-economy)
7. [Badges & trophy room](#badges--trophy-room)
8. [Points store](#points-store)
9. [Daily streak](#daily-streak)
10. [Reputation](#reputation)
11. [Profile area](#profile-area)
12. [Topic preferences](#topic-preferences)
13. [Referrals](#referrals)
14. [Language & RTL](#language--rtl)
15. [Forgot password](#forgot-password)

---

## Getting started

### Register

1. Open `/register`
2. Choose **Worker** (default) or **Customer** — workers should select **Worker**
3. Provide a **username**, a **valid, unique email address**, and a password (at least 8 characters, not all-numeric, not a common/breached password, and not too similar to your username or email)
4. Submit → a 6-digit verification code is emailed to you and you land on `/register/verify-worker`
5. Enter the code (10-minute expiry; **Resend** available on a cooldown) → account is marked verified and you are sent to **onboarding** (`/setup/`)

In dev without SMTP configured, the code prints to the server console instead of arriving by email.

Invite links (`/register?invite=<token>`) still work for workers; the invite is accepted on successful registration.

### Log in

- URL: `/login`
- Fields: **username** and **password** only (no role selector)
- After login, workers land on `/worker` (or `/setup/` if onboarding is incomplete)
- Workers do **not** get an email code on every login — only once at signup. (Admins and customers do verify by email code on every login.)
- If you registered but never finished email verification, logging in resumes the verification step instead of signing you in

### Forgot your password?

See [Forgot password](#forgot-password) below.

### Log out

- Header **Log out** button, or `/logout`

---

## URLs & navigation

| URL | Name | Description |
|-----|------|-------------|
| `/worker` | Worker dashboard | Points, streak, leaderboard, difficulty progress |
| `/tasks` | Labeling session | Answer tasks for the selected difficulty tier |
| `/setup/` | Onboarding | Language + topic preferences (first visit) |
| `/profile/` | Activity | Calendar + reputation score |
| `/profile/preferences/` | Preferences | Topic (`region_tag`) filter |
| `/profile/security/` | Security | Username + password |
| `/profile/wallet/` | Wallet | Points earned / spent / balance |
| `/history/` | History | Per-difficulty answer grids |
| `/trophies/` | Trophy room | Earned badges + referral link |
| `/store/` | Store | Spend points on cosmetic badges |
| `/store/buy/` | Buy badge | POST — purchase a store item |
| `/forgot-password` | Forgot password | Request a reset code by email |
| `/settings/username`, `/settings/password` | Security actions | POST-only, back the forms on `/profile/security/` |

Workers **cannot** access `/dashboard`, `/admin-tools/*`, or `/customer/*` (403).

---

## Onboarding

**Route:** `/setup/` (required once after registration)

Workers choose:

1. **Interface language** — English or Arabic (stored in session/cookie via Django i18n)
2. **Topic preferences** — optional checkboxes for `region_tag` values (e.g. `kitchen`, `uae`)

Until onboarding completes, other worker pages redirect back to `/setup/`.

---

## Dashboard

**Route:** `/worker`

Shows:

- **Points balance** and link to wallet
- **Daily streak** chip (hover for status message)
- **Points leaderboard** — top 5 workers by lifetime earned points; your rank if outside top 5
- **Difficulty cards** — Easy / Medium / Hard with progress bars (% of tier completed)

Click a difficulty card to start or continue labeling (`/tasks`). Progress respects topic preferences when set.

**Badge toasts:** Newly earned achievement badges may appear after submissions (via session flash).

---

## Labeling tasks

**Route:** `/tasks` (requires difficulty in session — set from dashboard)

### Difficulty tiers

| Tier | Complexity | Session label |
|------|------------|---------------|
| Easy | 1 | Easy |
| Medium | 2, 3 | Medium |
| Hard | 4 | Hard |

### Flow

1. One task shown at a time: image, question text, multiple-choice options
2. Optional **timer** (controlled by `SHOW_ANSWER_TIMER` in settings)
3. Submit answer → feedback (correct/incorrect if task is scorable)
4. **Next task** or **finished** when tier queue is empty

Submissions are rate-limited (120/min by default) to prevent scripted spam — normal labeling speed never hits this.

### Task pool rules (worker-visible effects only)

- Only tasks from **active** projects enter the pool (workers do not see project names)
- Topic filter applies when preferences are set
- Already-answered tasks are skipped
- Gold tasks appear in the normal queue (validation / honeypot)

### Scoring

- Tasks **with** `correct_answer`: verified right/wrong; affects points bonus and reputation
- Tasks **without** `correct_answer`: recorded but not scored as correct/incorrect

---

## Points economy

Points are **lifetime earned** minus **spends**. Display balance = earned − spent.

### Earning

| Source | Rule |
|--------|------|
| Completion | 5 points × each **distinct** task answered |
| Correctness bonus | Per correct verified answer: easy +5, medium +10, hard +15 |
| Badge rewards | One-time bonus when earning badge tiers (see badges config) |
| Referrals | 30 points per successful invite, max 10 referrals |

### Spending

- Points store cosmetic badges (`/store/`)
- Spend history on `/profile/wallet/`

### Leaderboard

Ranks by **lifetime earned** (`calculate_points`), not current balance — buying store items does not drop rank.

---

## Badges & trophy room

**Route:** `/trophies/`

### Achievement badges (earned)

Three badge tracks, each with bronze / silver / gold:

| Badge | Based on |
|-------|----------|
| Tasks Completed | Distinct tasks answered |
| Daily Streak | Longest streak days |
| Points | Lifetime points earned |

Progress bars show distance to the next tier. Badges are **permanent** once earned (`EarnedBadge` table).

### Reconciliation

Badges are checked on dashboard and trophy room load (`reconcile_badges`). New tiers trigger toast notifications.

---

## Points store

**Route:** `/store/`

Cosmetic badges purchased with spendable balance (separate from earned achievement badges):

| Key | Default cost | Notes |
|-----|--------------|-------|
| `early_bird` | 50 | Cosmetic |
| `night_owl` | 50 | Cosmetic |
| `trailblazer` | 150 | Cosmetic |
| `legend` | 300 | Cosmetic |

Owned items appear in the trophy room. Purchases are recorded in `PointsSpend` and `PurchasedBadge`.

---

## Daily streak

- Complete **at least one task per calendar day** to build a streak
- **5+ day streak** grants a one-time **freeze** (miss one day without losing streak)
- Streak state shown on dashboard; broken streaks reset on next dashboard load if days were missed

---

## Reputation

**Route:** `/profile/` (reputation section)

Quality score starting at **100**, adjusted by latest answer per task:

- **Gain** on correct verified answers (by complexity)
- **Loss** on wrong verified answers
- Floor at 0
- Unscored tasks do not affect reputation

Read-only — no separate reputation table; computed from `WorkerAnswer` on page load.

---

## Profile area

Shared layout: `profile_base.html` with tabs.

| Tab | URL | Content |
|-----|-----|---------|
| Activity | `/profile/` | Month calendar (AJAX nav), reputation |
| Preferences | `/profile/preferences/` | Topic checkboxes |
| Security | `/profile/security/` | Username + password forms |
| Wallet | `/profile/wallet/` | Earned, spent, balance, spend ledger |

---

## Topic preferences

**Route:** `/profile/preferences/`

- Checkboxes populated from distinct `Task.region_tag` values in **active** projects
- **Empty selection** = all topics (no filter)
- **Non-empty** = only tasks matching selected tags appear in `/tasks` and difficulty progress

Also configurable during onboarding.

---

## Referrals

- **Create invite:** header ⤴ button (POST `/invite/create/`) → redirects to trophy room with share URL
- **Register with invite:** `/register?invite=<token>` — inviter earns referral points when invitee registers
- Cap: 10 successful referrals × 30 points

---

## Language & RTL

- Header **EN | عربية** switcher (POST to Django `set_language`)
- Arabic enables RTL layout (`dir="rtl"` on `<html>`) and Arabic font stack in CSS
- After changing translatable strings in code, operators must run `makemessages` / `compilemessages` (see admin handover doc)

---

## Forgot password

**Route:** `/forgot-password` (worker and customer accounts; admins are reset by an operator)

1. Enter your account email → if it matches an eligible account, a 6-digit reset code is emailed (10-minute expiry)
2. The confirmation message is intentionally the same whether or not the email matches an account, so no one can probe which emails are registered
3. `/forgot-password/verify` — enter the code (**Resend** available on a cooldown)
4. `/forgot-password/reset` — set a new password

Reset requests are rate-limited per IP and per email address to prevent abuse.

---

## What workers do not see

- Project names, customer accounts, or upload status
- Admin analytics, review queue, or resolution tools
- Question distribution weights
- Per-project deadlines (admin-only alerts)

All labeling is drawn from a **shared worker pool** across active projects.
