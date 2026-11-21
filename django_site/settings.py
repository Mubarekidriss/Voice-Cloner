
"""
Django settings for django_site project.
"""

import os

from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
import dj_database_url


BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------
# SECURITY AND ENVIRONMENT
# ---------------------------------------------------------

DEBUG = os.environ.get(
    "DJANGO_DEBUG", "true"
).lower() in {"true", "1", "yes"}

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")

if not SECRET_KEY:

    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be configured in production."
        )

    SECRET_KEY = (
        "django-insecure-local-development-only-change-before-deployment"
    )

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,[::1]"
    ).split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS", ""
    ).split(",")
    if origin.strip()
]

# Render automatically supplies this hostname for deployed services.
RENDER_EXTERNAL_HOSTNAME = os.environ.get(
    "RENDER_EXTERNAL_HOSTNAME"
)

if RENDER_EXTERNAL_HOSTNAME:

    if RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

    render_origin = f"https://{RENDER_EXTERNAL_HOSTNAME}"

    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)

# ---------------------------------------------------------
# APPLICATIONS
# ---------------------------------------------------------

INSTALLED_APPS = [
    "modules.apps.VoiceClonerWebConfig",

    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]


# ---------------------------------------------------------
# MIDDLEWARE
# ---------------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # Serve collected static files in production.
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


ROOT_URLCONF = "django_site.urls"


# ---------------------------------------------------------
# TEMPLATES
# ---------------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


WSGI_APPLICATION = "django_site.wsgi.application"


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:

    # Production database, such as Render PostgreSQL.
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=not DEBUG,
        )
    }

else:

    # Local development database.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# ---------------------------------------------------------
# PASSWORD VALIDATION
# ---------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# ---------------------------------------------------------
# AUTHENTICATION REDIRECTS
# ---------------------------------------------------------

LOGIN_URL = "login"

LOGIN_REDIRECT_URL = "voice_cloner_home"

LOGOUT_REDIRECT_URL = "login"


# ---------------------------------------------------------
# INTERNATIONALIZATION
# ---------------------------------------------------------

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# ---------------------------------------------------------
# STATIC AND MEDIA FILES
# ---------------------------------------------------------

STATIC_URL = "/static/"

STATICFILES_DIRS = [
    BASE_DIR / "static"
]

# Destination for collectstatic.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Keep the default storage for ordinary uploaded files.
# Use compressed, hashed static files in production.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },

    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if not DEBUG
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}

MEDIA_ROOT = BASE_DIR / "runtime_media"


# ---------------------------------------------------------
# AUDIO UPLOAD PROTECTION
# ---------------------------------------------------------

MAX_AUDIO_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB

FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

DATA_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024

DATA_UPLOAD_MAX_NUMBER_FILES = 1

FILE_UPLOAD_HANDLERS = [
    "modules.security.MaxAudioSizeUploadHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]


# ---------------------------------------------------------
# PRIVATE AUDIO STORAGE
# ---------------------------------------------------------

PRIVATE_AUDIO_ROOT = BASE_DIR / "runtime_audio_private"

AUDIO_RETENTION_SECONDS = 60 * 60


# ---------------------------------------------------------
# CONSENT
# ---------------------------------------------------------

# Matches the name attribute in index.html:
# name="consent_ack"

VOICE_CLONING_CONSENT_FIELD = "consent_ack"


# ---------------------------------------------------------
# SESSION AND COOKIE SECURITY
# ---------------------------------------------------------

SESSION_COOKIE_HTTPONLY = True

SESSION_COOKIE_SAMESITE = "Lax"

SESSION_COOKIE_SECURE = not DEBUG

CSRF_COOKIE_SAMESITE = "Lax"

CSRF_COOKIE_SECURE = not DEBUG


# ---------------------------------------------------------
# DEPLOYMENT SECURITY
# ---------------------------------------------------------

SECURE_SSL_REDIRECT = os.environ.get(
    "DJANGO_SECURE_SSL_REDIRECT",
    "false" if DEBUG else "true"
).lower() in {"true", "1", "yes"}

SECURE_CONTENT_TYPE_NOSNIFF = True

SECURE_REFERRER_POLICY = "same-origin"

X_FRAME_OPTIONS = "DENY"

SECURE_HSTS_SECONDS = int(
    os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0")
)

SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    SECURE_HSTS_SECONDS > 0
)

SECURE_HSTS_PRELOAD = (
    SECURE_HSTS_SECONDS > 0
)

# Render terminates HTTPS at its proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# This allows Django to recognize the original HTTPS connection.

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = (
        "HTTP_X_FORWARDED_PROTO",
        "https"
    )


# ---------------------------------------------------------
# DEFAULT PRIMARY KEY
# ---------------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# FP11: web process can call an authorized external model worker.
VOICE_INFERENCE_MODE = os.environ.get("VOICE_INFERENCE_MODE", "local").lower()
if VOICE_INFERENCE_MODE not in {"local", "remote"}:
    raise ImproperlyConfigured("VOICE_INFERENCE_MODE must be local or remote.")
VOICE_WORKER_URL = os.environ.get("VOICE_WORKER_URL", "")
VOICE_WORKER_SECRET = os.environ.get("VOICE_WORKER_SECRET", "")
VOICE_WORKER_TIMEOUT = int(os.environ.get("VOICE_WORKER_TIMEOUT", "180"))
if not 1 <= VOICE_WORKER_TIMEOUT <= 600:
    raise ImproperlyConfigured("VOICE_WORKER_TIMEOUT must be 1 to 600 seconds.")
VOICE_WORKER_ALLOW_LOOPBACK = DEBUG and os.environ.get("VOICE_WORKER_ALLOW_LOOPBACK", "false").lower() == "true"
