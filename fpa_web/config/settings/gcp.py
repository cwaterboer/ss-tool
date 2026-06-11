"""
Google Cloud Platform production settings.

Switches from local SQLite/Redis to Cloud SQL/Cloud Memorystore.
Use with: python manage.py runserver --settings=config.settings.gcp
"""

from .base import *

DEBUG = False
ALLOWED_HOSTS = [
    'fpa-web-369870387328.europe-west1.run.app',
    'fpa-web.europe-west1.run.app',
    '.run.app',  # Match all Cloud Run domains
    '.compute.googleapis.com',  # Match Compute Engine domains
    '127.0.0.1',
    'localhost',
]

# ============================================================================
# CSRF and Session Configuration
# ============================================================================
CSRF_TRUSTED_ORIGINS = [
    'https://fpa-web-369870387328.europe-west1.run.app',
    'https://fpa-web.europe-west1.run.app',
    'https://*.run.app',  # Match all Cloud Run domains
]
# CLOUD SQL PostgreSQL Configuration
# ============================================================================
# Connection via Cloud SQL Auth Proxy:
#   gcloud cloud-sql-proxy ss-tool-498115:us-central1:fpa-db
#
# Then point Django to the proxy running on localhost:5432

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('POSTGRES_DB', 'fpa_scoping'),
        'USER': env('POSTGRES_USER', 'postgres'),
        'PASSWORD': env('POSTGRES_PASSWORD'),  # REQUIRED
        'HOST': env('POSTGRES_HOST', 'localhost'),  # Cloud SQL Proxy runs here
        'PORT': env('POSTGRES_PORT', '5432'),
        'ATOMIC_REQUESTS': True,
        'CONN_MAX_AGE': 60,
    }
}

# ============================================================================
# CLOUD MEMORYSTORE (Redis) Configuration
# ============================================================================
# For local testing with remote GPU worker:
#   REDIS_URL=redis://localhost:6379/0
#
# For production with Cloud Memorystore:
#   REDIS_URL=redis://10.0.0.3:6379/0  (internal IP)

CELERY_BROKER_URL = env('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_TIME_LIMIT = 7200  # 2 hours for GPU processing

# ============================================================================
# CORS Configuration
# ============================================================================
# Allow API requests from the Cloud Run frontend
CORS_ALLOWED_ORIGINS = [
    'https://fpa-web-369870387328.europe-west1.run.app',
    'https://fpa-web.europe-west1.run.app',
]
CORS_ALLOW_CREDENTIALS = True

# ============================================================================
# GOOGLE CLOUD STORAGE Configuration
# ============================================================================
# Requires:
#   - gs-bucket-name GCS bucket created
#   - GOOGLE_APPLICATION_CREDENTIALS set to service account key
#   - pip install django-storages[google]

if env('USE_GCS', 'false').lower() == 'true':
    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.gcloud.GoogleCloudStorage',
            'OPTIONS': {
                'bucket_name': env('GCS_BUCKET_NAME'),
                'project_id': env('GCP_PROJECT_ID', 'ss-tool-498115'),
            }
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        }
    }
    STATIC_ROOT = '/app/staticfiles'
    STATIC_URL = '/static/'
    MEDIA_URL = f'https://storage.googleapis.com/{env("GCS_BUCKET_NAME")}/media/'
else:
    # Fallback to local filesystem if GCS not configured
    STATIC_ROOT = '/app/staticfiles'
    STATIC_URL = '/static/'
    MEDIA_URL = '/media/'
    MEDIA_ROOT = env('MEDIA_ROOT', str(BASE_DIR / 'media'))

# ============================================================================
# Security Settings for Production
# ============================================================================
SECURE_SSL_REDIRECT = env('SECURE_SSL_REDIRECT', 'true').lower() == 'true'
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# ============================================================================
# Email Configuration (for error alerts)
# ============================================================================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = env('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(env('EMAIL_PORT', '587'))
EMAIL_USE_TLS = env('EMAIL_USE_TLS', 'true').lower() == 'true'
EMAIL_HOST_USER = env('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', '')

# Logging for Cloud Run
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            'format': '{"time": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
