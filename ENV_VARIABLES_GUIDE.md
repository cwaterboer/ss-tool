# FPA Scoping Environment Variables Guide

## Local Development (config.settings.local)

Copy this section to your `.env` file for local Codespaces development:

```bash
# Django
DJANGO_SETTINGS_MODULE=config.settings.local
DEBUG=true
SECRET_KEY=dev-secret-not-for-production

# Database (SQLite - local only)
# No configuration needed; uses db.sqlite3

# Redis/Celery (Local)
REDIS_URL=redis://localhost:6379/0

# Checkpoint
CHECKPOINT_ROOT=/tmp/checkpoints
LINGBOT_CHECKPOINT_PATH=/tmp/checkpoints/lingbot-map.pt

# Media Root
MEDIA_ROOT=./media

# Maps API (optional)
GOOGLE_MAPS_API_KEY=your-api-key-here
```

**To use local settings:**
```bash
python manage.py runserver --settings=config.settings.local
```

---

## Local Testing with Remote GPU Worker

Same as above, but point Redis to your Compute Engine instance:

```bash
# Redis connects to GPU instance (via SSH tunnel or firewall rule)
REDIS_URL=redis://INSTANCE_EXTERNAL_IP:6379/0
```

**SSH Tunnel (if needed):**
```bash
gcloud compute ssh fpa-gpu-worker --zone=us-central1-a \
  -- -L 6379:localhost:6379 &
# Then REDIS_URL=redis://localhost:6379/0
```

---

## Production (config.settings.gcp)

Set these environment variables on Cloud Run, Compute Engine, or your deployment:

```bash
# Django
DJANGO_SETTINGS_MODULE=config.settings.gcp
DEBUG=false
SECRET_KEY=your-strong-secret-key-here

# Cloud SQL PostgreSQL
# Format: postgresql://user:password@host:port/dbname
POSTGRES_DB=fpa_scoping
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-secure-password
POSTGRES_HOST=127.0.0.1  # Cloud SQL Proxy runs here
POSTGRES_PORT=5432

# Cloud Memorystore Redis
REDIS_URL=redis://10.0.0.3:6379/0

# Google Cloud Storage
USE_GCS=true
GCS_BUCKET_NAME=ss-tool-media-prod
GCP_PROJECT_ID=ss-tool-498115
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# Checkpoint (same as local)
CHECKPOINT_ROOT=/tmp/checkpoints
LINGBOT_CHECKPOINT_PATH=/tmp/checkpoints/lingbot-map.pt

# Security (production only)
SECURE_SSL_REDIRECT=true
ALLOWED_HOSTS=*.run.app,*.compute.googleapis.com

# Email Configuration (for error alerts)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# Maps API
GOOGLE_MAPS_API_KEY=your-api-key-here
```

**To use GCP settings:**
```bash
python manage.py runserver --settings=config.settings.gcp
```

---

## GPU Worker Environment (Compute Engine)

Set on the Compute Engine instance running Celery:

```bash
# Django
DJANGO_SETTINGS_MODULE=config.settings.gcp
SECRET_KEY=same-as-above

# Redis (same as app above)
REDIS_URL=redis://10.0.0.3:6379/0

# For local testing: REDIS_URL=redis://localhost:6379/0

# Database (if worker needs it)
POSTGRES_PASSWORD=your-secure-password
POSTGRES_HOST=cloudsql-proxy
```

**Systemd Service automatically sources these from environment.**

---

## Cloud Run Deployment

Set secrets in Cloud Run:

```bash
gcloud run deploy fpa-scoping \
  --set-env-vars="DJANGO_SETTINGS_MODULE=config.settings.gcp" \
  --set-secrets="SECRET_KEY=secret_key:latest" \
  --set-secrets="POSTGRES_PASSWORD=postgres_password:latest" \
  --set-secrets="GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/gcp-key.json"
```

Or use `.env.yaml`:
```yaml
DJANGO_SETTINGS_MODULE: config.settings.gcp
DEBUG: "false"
REDIS_URL: redis://10.0.0.3:6379/0
POSTGRES_DB: fpa_scoping
POSTGRES_USER: postgres
USE_GCS: "true"
GCS_BUCKET_NAME: ss-tool-media-prod
```

Then:
```bash
gcloud run deploy fpa-scoping --env-vars-file=.env.yaml
```

---

## Setting Variables in Different Environments

### Local Development (.env file)

Create `.env` file in project root:
```bash
cp .env.example .env
# Edit .env with local values

# Load in Python:
from decouple import config
debug = config('DEBUG', default=False, cast=bool)
```

### Codespaces Secrets

In GitHub Codespaces:
1. Settings → Secrets and variables → Codespaces
2. Add secret `DJANGO_SECRET_KEY`
3. In `.devcontainer.json`: Add to `remoteEnv`

### Compute Engine Instance

SSH into instance and add to `/etc/environment`:
```bash
sudo nano /etc/environment
# Add variables, then:
source /etc/environment
```

### Cloud Run

```bash
gcloud run deploy SERVICE \
  --set-env-vars KEY1=value1,KEY2=value2
```

Or use Secret Manager:
```bash
gcloud secrets create postgres-password --data-file=-
gcloud run deploy SERVICE \
  --set-secrets POSTGRES_PASSWORD=postgres-password:latest
```

---

## Switching Between Local and GCP

### Development Workflow

1. **Local testing:**
   ```bash
   export DJANGO_SETTINGS_MODULE=config.settings.local
   python manage.py runserver
   ```

2. **Test with remote GPU:**
   ```bash
   export REDIS_URL=redis://INSTANCE_IP:6379/0
   export DJANGO_SETTINGS_MODULE=config.settings.local
   python manage.py runserver
   ```

3. **Full production staging:**
   ```bash
   export DJANGO_SETTINGS_MODULE=config.settings.gcp
   export POSTGRES_HOST=cloudsql-proxy
   # ... (set all GCP variables)
   python manage.py migrate --settings=config.settings.gcp
   python manage.py runserver --settings=config.settings.gcp
   ```

### Configuration Inheritance

Both `config.settings.local` and `config.settings.gcp` inherit from `config.settings.base`:

```python
# base.py - Shared settings
DEBUG = False
INSTALLED_APPS = [...]

# local.py - Override for local
from .base import *
DEBUG = True
DATABASES = {'default': {'ENGINE': 'sqlite3', ...}}

# gcp.py - Override for production
from .base import *
DEBUG = False
DATABASES = {'default': {'ENGINE': 'postgresql', ...}}
```

---

## Variable Reference

| Variable | Purpose | Local | Production |
|----------|---------|-------|-----------|
| `DJANGO_SETTINGS_MODULE` | Which settings file | `config.settings.local` | `config.settings.gcp` |
| `DEBUG` | Django debug mode | `true` | `false` |
| `SECRET_KEY` | Django secret | Dev key | Strong random key |
| `REDIS_URL` | Celery broker | `redis://localhost:6379/0` | `redis://cloud-memorystore-ip:6379/0` |
| `POSTGRES_HOST` | Database host | Uses SQLite | Cloud SQL Proxy IP |
| `USE_GCS` | Cloud Storage enabled | `false` | `true` |
| `GCS_BUCKET_NAME` | Storage bucket | N/A | `ss-tool-media-prod` |
| `CHECKPOINT_ROOT` | Model checkpoint dir | `/tmp/checkpoints` | Same or cloud |

---

## Security Best Practices

❌ **Never commit:**
- `.env` files with real secrets
- Service account keys
- Passwords
- API keys

✅ **Always use:**
- Cloud Secret Manager for production
- Environment variables for sensitive data
- `.env.example` template (with placeholder values)
- Least privilege service accounts

**Example .env.example:**
```bash
# Copy to .env and fill in your values
DJANGO_SETTINGS_MODULE=config.settings.local
DEBUG=true
SECRET_KEY=your-secret-key-here
POSTGRES_PASSWORD=your-password-here
```

---

## Testing Configuration Switching

```bash
# Verify local settings load
python manage.py shell --settings=config.settings.local
>>> from django.conf import settings
>>> settings.DATABASES  # Should show SQLite

# Verify GCP settings load (requires env vars set)
python manage.py shell --settings=config.settings.gcp
>>> from django.conf import settings
>>> settings.DATABASES  # Should show PostgreSQL
```
