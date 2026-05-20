import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(key, default=None):
    value = os.environ.get(key, default)
    if value is None:
        raise ImproperlyConfigured(f'Required env var {key} is not set')
    return value


SECRET_KEY = env('SECRET_KEY', 'dev-secret-not-for-production')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'apps.sites',
    'apps.scans',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]

STATIC_URL = '/static/'
MEDIA_URL = '/media/'
MEDIA_ROOT = env('MEDIA_ROOT', str(BASE_DIR / 'media'))

CHECKPOINT_ROOT = env('CHECKPOINT_ROOT', '/tmp/checkpoints')
LINGBOT_CHECKPOINT_PATH = env('LINGBOT_CHECKPOINT_PATH', '/tmp/checkpoints/lingbot-map.pt')

CELERY_BROKER_URL = env('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_TIME_LIMIT = 7200

GOOGLE_MAPS_API_KEY = env('GOOGLE_MAPS_API_KEY', '')

DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024 * 1024
FILE_UPLOAD_HANDLERS = ['django.core.files.uploadhandler.TemporaryFileUploadHandler']
