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
    'storages',
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
    'core.middleware.UserTimezoneMiddleware',
    'core.middleware.MaintenanceModeMiddleware',
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
                'core.context_processors.announcement_alerts',
                'core.context_processors.emergency_banner',
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

AUTHENTICATION_BACKENDS = [
    'users.backends.EmailOrUsernameModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

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
# Object Storage Configuration (S3 / Cloudflare R2 / MinIO with local disk fallback)
MEDIA_BUCKET = os.environ.get('AWS_STORAGE_BUCKET_NAME') or os.environ.get('MEDIA_S3_BUCKET')
if MEDIA_BUCKET:
    s3_options = {
        'bucket_name': MEDIA_BUCKET,
        'location': os.environ.get('AWS_MEDIA_LOCATION', 'media'),
        'file_overwrite': False,
        'default_acl': None,
        'querystring_auth': False,
    }
    endpoint_url = os.environ.get('AWS_S3_ENDPOINT_URL') or os.environ.get('MEDIA_S3_ENDPOINT_URL')
    if endpoint_url:
        s3_options['endpoint_url'] = endpoint_url
    access_key = os.environ.get('AWS_ACCESS_KEY_ID') or os.environ.get('MEDIA_S3_ACCESS_KEY')
    if access_key:
        s3_options['access_key'] = access_key
    secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY') or os.environ.get('MEDIA_S3_SECRET_KEY')
    if secret_key:
        s3_options['secret_key'] = secret_key
    region_name = os.environ.get('AWS_S3_REGION_NAME') or os.environ.get('MEDIA_S3_REGION', 'us-east-1')
    if region_name:
        s3_options['region_name'] = region_name

    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
            'OPTIONS': s3_options,
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
        },
    }
    MEDIA_URL = f"https://{MEDIA_BUCKET}.s3.amazonaws.com/{s3_options['location']}/"
    if endpoint_url:
        MEDIA_URL = f"{endpoint_url.rstrip('/')}/{MEDIA_BUCKET}/{s3_options['location']}/"
else:
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


# Production Hardening & Security Guardrails
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB upload cap
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = 'DENY'
    SESSION_COOKIE_HTTPONLY = True
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'False').lower() in ('true', '1')
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() in ('true', '1')
    CSRF_COOKIE_SECURE = os.environ.get('CSRF_COOKIE_SECURE', 'False').lower() in ('true', '1')
