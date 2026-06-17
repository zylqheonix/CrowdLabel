"""
Django settings for the CrowdLabel prototype.

Uses Django's built-in authentication (custom user model with a role field)
plus a small SQLite database for worker scores. The Django admin site is still
intentionally left out — it isn't needed for this prototype.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Prototype-only secret key. Replace before any real deployment.
SECRET_KEY = "django-insecure-prototype-key-not-for-production"

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Built-in auth (+ its required apps); the database-backed admin site is omitted.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "crowdlabel.wsgi.application"

# Default SQLite database — used only to store accumulated worker scores.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Custom user model carries the worker/admin role.
AUTH_USER_MODEL = "core.User"

# Unauthenticated users hitting a protected view are sent here.
LOGIN_URL = "login"
