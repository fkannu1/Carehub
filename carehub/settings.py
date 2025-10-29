from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# -------------------------------------------------------------------
# Core
# -------------------------------------------------------------------
SECRET_KEY = "dev-secret-change-in-prod"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    "oauth2_provider",
    "channels",  # realtime (websockets). in dev we use in-memory layer

    # Local apps
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "carehub.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# -------------------------------------------------------------------
# WSGI/ASGI
# -------------------------------------------------------------------
WSGI_APPLICATION = "carehub.wsgi.application"
ASGI_APPLICATION = "carehub.asgi.application"

# Dev channel layer (in-memory). Switch to Redis in production.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# -------------------------------------------------------------------
# Database
# -------------------------------------------------------------------
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}

# -------------------------------------------------------------------
# Auth & i18n
# -------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"   # <<< important for 9–5 availability windows
USE_I18N = True
USE_TZ = True

AUTH_USER_MODEL = "core.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard_router"
LOGOUT_REDIRECT_URL = "login"

# -------------------------------------------------------------------
# Static & Media
# -------------------------------------------------------------------
STATIC_URL = "static/"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -------------------------------------------------------------------
# DRF / OAuth2
# -------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    # (optional) You can uncomment to restrict to JSON only:
    # "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
}

OAUTH2_PROVIDER = {
    "SCOPES": {
        "read": "Read access",
        "write": "Write access",
    }
}
