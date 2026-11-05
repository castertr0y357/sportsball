from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-church-sports-leagues-dev-key-change-in-production'
)

DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')

# Reverse proxy and CSRF support
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

raw_csrf = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in raw_csrf.split(',') if origin.strip()] if raw_csrf else []
for host in ALLOWED_HOSTS:
    host = host.strip()
    if host and host != '*' and not host.startswith('127.') and host != 'localhost':
        CSRF_TRUSTED_ORIGINS.append(f"https://{host}")
        CSRF_TRUSTED_ORIGINS.append(f"http://{host}")
CSRF_TRUSTED_ORIGINS = list(set(CSRF_TRUSTED_ORIGINS))

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Local apps
    'core',
    'users',
    'leagues',
    'stats',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'church_leagues.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.media',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'church_leagues.wsgi.application'

# Database configuration: PostgreSQL when DATABASE_URL or DB_HOST/POSTGRES_HOST is set,
# falling back to SQLite for local development and CI testing.
db_url = os.environ.get('DATABASE_URL')
db_host = os.environ.get('DB_HOST') or os.environ.get('POSTGRES_HOST')

if db_url:
    try:
        import dj_database_url
        DATABASES = {
            'default': dj_database_url.parse(
                db_url,
                conn_max_age=int(os.environ.get('DB_CONN_MAX_AGE', 600)),
                conn_health_checks=True,
            )
        }
    except ImportError:
        import urllib.parse
        parsed = urllib.parse.urlparse(db_url)
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': parsed.path.lstrip('/'),
                'USER': parsed.username or '',
                'PASSWORD': parsed.password or '',
                'HOST': parsed.hostname or '',
                'PORT': str(parsed.port or 5432),
                'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', 600)),
            }
        }
elif db_host:
    DATABASES = {
        'default': {
            'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.postgresql'),
            'NAME': os.environ.get('DB_NAME') or os.environ.get('POSTGRES_DB', 'sportsball'),
            'USER': os.environ.get('DB_USER') or os.environ.get('POSTGRES_USER', 'sportsball'),
            'PASSWORD': os.environ.get('DB_PASSWORD') or os.environ.get('POSTGRES_PASSWORD', ''),
            'HOST': db_host,
            'PORT': str(os.environ.get('DB_PORT') or os.environ.get('POSTGRES_PORT', '5432')),
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', 600)),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

AUTH_USER_MODEL = 'users.CustomUser'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/New_York'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}
WHITENOISE_MANIFEST_STRICT = False

# Email Configuration (Gmail SMTP with local Console fallback)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')

if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    DEFAULT_FROM_EMAIL = f"SportsBall <{EMAIL_HOST_USER}>"
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    DEFAULT_FROM_EMAIL = 'SportsBall <noreply@sportsball.local>'

# Optional Twilio SMS Configuration
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '')

if DEBUG:
    try:
        import debug_toolbar  # noqa: F401
        INSTALLED_APPS.append('debug_toolbar')
        MIDDLEWARE.append('debug_toolbar.middleware.DebugToolbarMiddleware')
        DEBUG_TOOLBAR_CONFIG = {
            'DISABLE_PANELS': ['debug_toolbar.panels.redirects.RedirectsPanel'],
            'SHOW_TEMPLATE_CONTEXT': True,
        }
        INTERNAL_IPS = ['127.0.0.1']
    except ImportError:
        pass

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}
