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
    "corsheaders",  # CORS
    "channels",     # websockets (dev: in-memory layer)

    # Local apps
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",

    # CORS must be before CommonMiddleware
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",

    # 👇 COMMENTED OUT FOR POSTMAN TESTING - UNCOMMENT IN PRODUCTION!
    # "django.middleware.csrf.CsrfViewMiddleware",
    
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

# Dev channel layer (in-memory). Switch to Redis in prod.
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
TIME_ZONE = "America/New_York"  # ✅ This is correct
USE_I18N = True
USE_TZ = True  # ✅ This is critical - keeps all datetimes timezone-aware

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
    # 👇 CHANGED FOR POSTMAN TESTING - Change back to IsAuthenticated in production!
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.AllowAny",  # Was: IsAuthenticated
    ),
    # ✅ OPTIONAL: Add this for better datetime handling in API responses
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%S%z",  # ISO 8601 with timezone
    "DATETIME_INPUT_FORMATS": [
        "%Y-%m-%dT%H:%M:%S%z",  # 2025-11-05T14:30:00-0500
        "%Y-%m-%dT%H:%M:%S.%f%z",  # with microseconds
        "%Y-%m-%dT%H:%M:%SZ",  # UTC
        "%Y-%m-%dT%H:%M:%S",  # naive (will be interpreted as local)
    ],
}

OAUTH2_PROVIDER = {
    "SCOPES": {
        "read": "Read access",
        "write": "Write access",
    }
}

# -------------------------------------------------------------------
# CORS / CSRF (Dev)
# -------------------------------------------------------------------
# Vite dev server origins
CORS_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8000",  # 👈 ADDED for Postman
    "http://localhost:8000",   # 👈 ADDED for Postman
]

# Allow cookies to flow cross-origin (frontend -> backend)
CORS_ALLOW_CREDENTIALS = True

# Trust the Vite origin for CSRF
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8000",  # 👈 ADDED for Postman
    "http://localhost:8000",   # 👈 ADDED for Postman
]

# Dev cookie settings
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Keep HttpOnly = False so Axios (running in the browser) can read the cookie
# value and send it back in the X-CSRFToken header automatically.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_NAME = "csrftoken"  # Django default, explicit here

# -------------------------------------------------------------------
# Logging (Optional but helpful for debugging)
# -------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'core': {
            'handlers': ['console'],
            'level': 'DEBUG',  # Change to INFO in production
        },
    },
}