from .base import *

DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '.app.github.dev']
CSRF_TRUSTED_ORIGINS = ['https://*.app.github.dev', 'https://localhost:8000']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
