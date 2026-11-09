"""Base settings shared by every environment.

All secrets and environment-specific values come from environment variables
(see `.env.example` at the repository root). Nothing secret is committed.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env()
environ.Env.read_env(REPO_ROOT / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    # Project apps (order follows the dependency graph in ARCHITECTURE.md §0.2)
    "apps.core",
    "apps.users",
    "apps.audit",
    "apps.organizations",
    "apps.farms",
    "apps.synchronization",
    "apps.files",
    "apps.fields",
    "apps.crops",
    "apps.varieties",
    "apps.production_plans",
    "apps.inventory",
    "apps.irrigation",
    "apps.agronomy",
    "apps.tasks",
    "apps.finance",
    "apps.harvest",
    "apps.ai_assistant",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)

AUTH_USER_MODEL = "users.User"
AUTHENTICATION_BACKENDS = ["apps.users.backends.EmailOrPhoneBackend"]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français"), ("en", "English")]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.users.authentication.DeviceAwareJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "COERCE_DECIMAL_TO_STRING": True,
    "DEFAULT_THROTTLE_RATES": {"auth": "20/min"},
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=30)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    # An empty value (blank line in an .env file) must never become an empty signing key.
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default="") or SECRET_KEY,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Farm Management System API",
    "DESCRIPTION": "API REST versionnée du système de gestion agricole.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    # Stable names for choice sets shared by several models (otherwise hashed names).
    "ENUM_NAME_OVERRIDES": {
        "TaskStatusEnum": "apps.tasks.models.Task.Status",
        "MeasureUnitEnum": "apps.inventory.models.CatalogItem.Unit",
        "DocumentedSourceKindEnum": "apps.agronomy.models.SourceKind",
        "ActiveArchivedStatusEnum": "apps.farms.models.Farm.Status",
        "MembershipStatusEnum": "apps.farms.models.FarmMembership.Status",
        "VersionedDocumentStatusEnum": "apps.irrigation.models.IrrigationDesign.Status",
        "TransactionKindEnum": "apps.finance.models.FinancialTransaction.Kind",
        "FinanceCategoryKindEnum": "apps.finance.models.FinanceCategory.Kind",
        "TransactionInputKindEnum": ["expense", "income", "transfer", "funding", "repayment"],
        "TreasuryAccountKindEnum": "apps.finance.models.TreasuryAccount.Kind",
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.core.middleware.RequestIdLogFilter"}},
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

# File storage: private, never served by URL (downloads go through the API).
# Production may switch the default backend to an S3-compatible storage.
STORAGES: dict[str, dict[str, Any]] = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": env("FMS_FILE_STORAGE_ROOT", default=str(BASE_DIR / "media"))},
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Product-level settings
FMS_INVITATION_TTL_DAYS = env.int("FMS_INVITATION_TTL_DAYS", default=7)
# Web refresh-token cookie (apps/users/cookies.py, Q26): HTTPS only, except local development.
FMS_REFRESH_COOKIE_SECURE = env.bool("FMS_REFRESH_COOKIE_SECURE", default=True)
FMS_MAX_UPLOAD_MB = env.int("FMS_MAX_UPLOAD_MB", default=10)
FMS_MAX_TECHNICAL_SHEET_MB = env.int("FMS_MAX_TECHNICAL_SHEET_MB", default=20)

# AI assistant (apps/ai_assistant). "null" = assistant unavailable, manual mode only (FR-106).
FMS_AI_PROVIDER = env("FMS_AI_PROVIDER", default="null")
FMS_AI_MODEL = env("FMS_AI_MODEL", default="claude-opus-5-5")
FMS_AI_MONTHLY_REQUEST_LIMIT = env.int("FMS_AI_MONTHLY_REQUEST_LIMIT", default=200)
# Provider list prices in USD per million tokens, used for cost estimates only (FR-107).
FMS_AI_PRICES_USD_PER_MTOK: dict[str, dict[str, str]] = {
    "claude-opus-5-5": {"input": "4.00", "output": "20.00"},
    "claude-sonnet-5-5": {"input": "2.00", "output": "10.00"},
    "claude-haiku-5-5": {"input": "0.10", "output": "0.50"},
}
