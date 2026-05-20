# FPA Scoping Web App

## Local setup

1. Create a virtual environment and install dependencies:

```bash
pip install -r requirements.txt
```

2. Set `DJANGO_SETTINGS_MODULE=config.settings.local` and populate `.env`.
3. Run migrations and start the server:

```bash
cd fpa_web
python manage.py makemigrations sites scans
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Celery worker

```bash
celery -A config worker --loglevel=info --concurrency=1
```

## Nginx example

```nginx
server {
    listen 80;
    server_name your.domain.com;
    client_max_body_size 5G;

    location /media/ {
        alias /absolute/path/to/fpa_web/media/;
        add_header Access-Control-Allow-Origin *;
    }

    location /static/ {
        alias /absolute/path/to/fpa_web/staticfiles/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }
}
```
