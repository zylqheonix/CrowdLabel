"""
Django settings for CrowdLabel.

Secrets and environment-specific values are loaded from environment variables.
Copy `.env.example` to `.env` for local development.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
    except ImportError:
        pass


_load_dotenv()


def _env_bool(name, *, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name, *, default=None):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_int(name, *, default=0):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


DEBUG = _env_bool("DJANGO_DEBUG", default=True)

_secret_key = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if _secret_key:
    SECRET_KEY = _secret_key
elif DEBUG:
    SECRET_KEY = "django-insecure-dev-only-not-for-production"
else:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is False."
    )

if DEBUG:
    ALLOWED_HOSTS = _env_list(
        "DJANGO_ALLOWED_HOSTS",
        default=["localhost", "127.0.0.1", "[::1]"],
    )
else:
    ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS")
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            "DJANGO_ALLOWED_HOSTS must be set when DJANGO_DEBUG is False."
        )

CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# HTTPS / browser hardening. Off by default in DEBUG; on when DJANGO_DEBUG=False
# unless explicitly disabled with DJANGO_SECURE_HTTPS=False.
SECURE_HTTPS = _env_bool("DJANGO_SECURE_HTTPS", default=not DEBUG)

if SECURE_HTTPS:
    SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = _env_int("DJANGO_SECURE_HSTS_SECONDS", default=31_536_000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool(
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True
    )
    SECURE_HSTS_PRELOAD = _env_bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False

# Trust X-Forwarded-Proto from a reverse proxy (nginx, load balancer) in HTTPS mode.
if _env_bool("DJANGO_USE_PROXY_SSL_HEADER", default=SECURE_HTTPS):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = os.environ.get("DJANGO_SECURE_REFERRER_POLICY", "same-origin").strip()
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = os.environ.get("DJANGO_SESSION_COOKIE_SAMESITE", "Lax").strip()
CSRF_COOKIE_SAMESITE = os.environ.get("DJANGO_CSRF_COOKIE_SAMESITE", "Lax").strip()

# Built-in auth (+ its required apps); admin enabled for PointsSpend testing.
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "anymail",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves static files in production (DEBUG=False) without a separate web
    # server. Must sit directly after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "crowdlabel.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
            ],
        },
    },
]

WSGI_APPLICATION = "crowdlabel.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_CONN_MAX_AGE = _env_int("DJANGO_DB_CONN_MAX_AGE", default=600)

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=DB_CONN_MAX_AGE,
            ssl_require=not DEBUG,
        )
    }
else:
    # Local fallback: SQLite.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Enforced everywhere a user picks a password (registration, reset, change) via
# core.security.password_error(). CommonPasswordValidator supplies Django's
# ~20k common-password blocklist.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True

LANGUAGES = [
    ("en", "English"),
    ("ar", "العربية"),
]

LOCALE_PATHS = [BASE_DIR / "locale"]
USE_TZ = True

STATIC_URL = "static/"
# collectstatic gathers everything here for WhiteNoise to serve in production.
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    # Hashed, compressed static files in production for long-lived caching.
    # Plain storage in DEBUG so local `runserver` needs no collectstatic/manifest.
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "crowdlabel.storage.ResilientManifestStaticFilesStorage"
        ),
    },
}

# CSV upload limits (also mirrored in Django's request body cap below).
CSV_UPLOAD_MAX_BYTES = _env_int("CSV_UPLOAD_MAX_BYTES", default=2_621_440)
CSV_UPLOAD_MAX_ROWS = _env_int("CSV_UPLOAD_MAX_ROWS", default=10_000)
CSV_CHOICES_MAX_BYTES = _env_int("CSV_CHOICES_MAX_BYTES", default=8_192)
DATA_UPLOAD_MAX_MEMORY_SIZE = CSV_UPLOAD_MAX_BYTES
FILE_UPLOAD_MAX_MEMORY_SIZE = CSV_UPLOAD_MAX_BYTES

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Rate limiting (shared cache recommended in multi-worker production).
CACHES = {
    "default": {
        "BACKEND": os.environ.get(
            "DJANGO_CACHE_BACKEND",
            "django.core.cache.backends.locmem.LocMemCache",
        ).strip(),
        "LOCATION": os.environ.get("DJANGO_CACHE_LOCATION", "crowdlabel-ratelimit").strip(),
    }
}

RATE_LIMITS = {
    "login_ip": (_env_int("RATE_LIMIT_LOGIN_IP", default=30), 900),
    "login_fail": (_env_int("RATE_LIMIT_LOGIN_FAIL", default=5), 900),
    "register": (_env_int("RATE_LIMIT_REGISTER", default=10), 3600),
    "otp_send_ip": (_env_int("RATE_LIMIT_OTP_SEND_IP", default=10), 3600),
    "otp_send_user": (_env_int("RATE_LIMIT_OTP_SEND_USER", default=5), 3600),
    "otp_verify_fail": (_env_int("RATE_LIMIT_OTP_VERIFY_FAIL", default=5), 900),
    "forgot_password": (_env_int("RATE_LIMIT_FORGOT_PASSWORD", default=5), 3600),
    "forgot_password_email": (_env_int("RATE_LIMIT_FORGOT_PASSWORD_EMAIL", default=3), 3600),
    "reset_password": (_env_int("RATE_LIMIT_RESET_PASSWORD", default=10), 3600),
    "task_submit": (_env_int("RATE_LIMIT_TASK_SUBMIT", default=120), 60),
    "activity_month": (_env_int("RATE_LIMIT_ACTIVITY_MONTH", default=60), 60),
    "analytics": (_env_int("RATE_LIMIT_ANALYTICS", default=30), 60),
    "csv_upload": (_env_int("RATE_LIMIT_CSV_UPLOAD", default=5), 3600),
    "store_buy": (_env_int("RATE_LIMIT_STORE_BUY", default=20), 60),
    "invite_create": (_env_int("RATE_LIMIT_INVITE_CREATE", default=10), 3600),
    "review_resolve": (_env_int("RATE_LIMIT_REVIEW_RESOLVE", default=60), 60),
}

# Custom user model carries the worker/admin role.
AUTH_USER_MODEL = "core.User"

# Unauthenticated users hitting a protected view are sent here.
LOGIN_URL = "login"

# Prototype testing flag: visible timer only. Recording still runs when hidden.
SHOW_ANSWER_TIMER = True

# Review-queue thresholds (can become admin-configurable later).
REVIEW_AGREEMENT_THRESHOLD = 0.6
REVIEW_GOLD_FAIL_THRESHOLD = 0.6
REVIEW_LOW_COVERAGE = 3

# Question distribution (admin-controlled project serving weights).
TARGET_COVERAGE = 3
MIN_DAYS_FLOOR = 1.0
NO_DEADLINE_URGENCY = 5

# Admin analytics defaults.
ANALYTICS_ACTIVE_DAYS_DEFAULT = 7
ANALYTICS_MIN_WORKER_VOLUME = 5

# Email / OTP settings.
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
).strip()
DEFAULT_FROM_EMAIL = os.environ.get(
    "DJANGO_DEFAULT_FROM_EMAIL",
    "CrowdLabel <noreply@crowdlabel.local>",
).strip()
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "").strip()
EMAIL_PORT = _env_int("DJANGO_EMAIL_PORT", default=587)
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "").strip()
EMAIL_USE_TLS = _env_bool("DJANGO_EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = _env_bool("DJANGO_EMAIL_USE_SSL", default=False)

# Alternative to raw SMTP: set DJANGO_EMAIL_BACKEND=anymail.backends.resend.EmailBackend
# to send over Resend's HTTPS API instead. Needed on hosts (e.g. Render) that block
# outbound SMTP — the SMTP settings above are simply unused when this backend is active.
ANYMAIL = {
    "RESEND_API_KEY": os.environ.get("RESEND_API_KEY", "").strip(),
}

# Django's default logging silently drops unhandled request exceptions when
# DEBUG=False (no console output, no email unless ADMINS is configured) — so
# 500s are otherwise invisible on a host with no other log aggregation. Force
# them to stderr, which platforms like Render capture in their log stream.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
