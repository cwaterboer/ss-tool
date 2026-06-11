#!/bin/bash
set -e

echo "Waiting for Cloud SQL proxy..."
sleep 5

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8080 \
    --workers 2 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile -
