"""
WSGI config for ss-tool project.
It exposes the WSGI callable as a module-level variable named ``application``.
"""

import os
from django.core.wsgi import get_wsgi_application

# Use GCP settings by default, but respect DJANGO_SETTINGS_MODULE if set
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.gcp')

application = get_wsgi_application()
