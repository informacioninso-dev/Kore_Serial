from pathlib import Path
import os
from datetime import timedelta

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

SECRET_KEY = os.getenv("SECRET_KEY", "kore-serial-development-secret")
DEBUG = os.getenv("DEBUG", "True") == "True"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,.localhost").split(",")

SHARED_APPS = [
    "django_tenants",
    "tenants",
    "changecontrol",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_htmx",
    "huey.contrib.djhuey",
]

TENANT_APPS = [
    "core",
    "assembly",
    "wms",
]

INSTALLED_APPS = SHARED_APPS + [app for app in TENANT_APPS if app not in SHARED_APPS]

MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",
    "tenants.middleware.CurrentTenantMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "tenants.middleware.TenantAccessMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"
PUBLIC_SCHEMA_NAME = "public"
PUBLIC_SCHEMA_URLCONF = "config.public_urls"
TENANT_MODEL = "tenants.Client"
TENANT_DOMAIN_MODEL = "tenants.Domain"
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)
AUTHENTICATION_BACKENDS = ["tenants.auth_backends.TenantAwareModelBackend"]
TENANT_LIMIT_SET_CALLS = False
TENANT_BASE_DOMAIN = os.getenv("TENANT_BASE_DOMAIN", "localhost")

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
                "core.context_processors.tenant_modules",
                "core.context_processors.system_release",
                "config.context_processors.module_access",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": os.getenv("DB_NAME", "kore_serial"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-ec"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
PRIVATE_ROOT = Path(os.getenv("PRIVATE_ROOT", BASE_DIR / "private"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
PASSWORD_RESET_TIMEOUT = 7200
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "kore_serial_sessionid")
CSRF_COOKIE_NAME = os.getenv("CSRF_COOKIE_NAME", "kore_serial_csrftoken")

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

HUEY = {
    "name": "kore-serial",
    "immediate": False,
    "connection": {"url": REDIS_URL},
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

KORE_ENVIRONMENT = os.getenv("KORE_ENVIRONMENT", "Desarrollo" if DEBUG else "Produccion")
KORE_RELEASE_INFO_FILE = Path(os.getenv("KORE_RELEASE_INFO_FILE", BASE_DIR / "runtime" / "release.json"))
