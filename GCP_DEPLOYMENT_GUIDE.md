# GCP Deployment Guide (Option A)

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│         Google Cloud Platform               │
├─────────────────────────────────────────────┤
│                                             │
│  ┌──────────────────┐   ┌──────────────┐   │
│  │  Cloud Run       │   │  Cloud SQL   │   │
│  │  Django App      │──▶│ PostgreSQL   │   │
│  │  (CPU, $30/mo)   │   │ ($15/mo)     │   │
│  └──────────────────┘   └──────────────┘   │
│         │                      △            │
│         │ Enqueue task         │ Update     │
│         │                      │ status     │
│  ┌──────▼──────────────────────┴────────┐   │
│  │  Cloud Storage                       │   │
│  │  - Input frames                      │   │
│  │  - Output PLY files                  │   │
│  │  - Scene manifests                   │   │
│  │  (~$1/mo for small usage)            │   │
│  └──────────────────────────────────────┘   │
│                                             │
│  ┌──────────────────┐   ┌──────────────┐   │
│  │ Compute Engine   │   │ Cloud Tasks  │   │
│  │ GPU Worker       │◀──│ (Job Queue)  │   │
│  │ n1-standard-4    │   │              │   │
│  │ + T4 GPU         │   └──────────────┘   │
│  │ ($0.125/scan)    │                      │
│  └──────────────────┘                      │
│                                             │
└─────────────────────────────────────────────┘
```

---

## Phase 1: GCP Project Setup

### Step 1.1: Create GCP Project
```bash
# Set project variables
export PROJECT_ID="fpa-scoping"
export REGION="us-central1"
export ZONE="us-central1-a"

# Create project
gcloud projects create $PROJECT_ID --name="FPA Scoping"

# Set as active project
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  compute.googleapis.com \
  sqladmin.googleapis.com \
  storage-api.googleapis.com \
  cloudtasks.googleapis.com
```

### Step 1.2: Set Billing
```bash
# Link billing account (you'll need a billing account set up)
gcloud billing accounts list  # Find your billing account ID
gcloud billing projects link $PROJECT_ID --billing-account=BILLING_ACCOUNT_ID
```

---

## Phase 2: Database Setup (Cloud SQL)

### Step 2.1: Create PostgreSQL Instance
```bash
gcloud sql instances create fpa-postgres \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=$REGION \
  --no-backup
```

### Step 2.2: Create Database and User
```bash
# Get connection name
INSTANCE_CONNECTION_NAME=$(gcloud sql instances describe fpa-postgres \
  --format='value(connectionName)')

# Connect and create database
gcloud sql connect fpa-postgres --user=postgres

# In the PostgreSQL prompt:
CREATE DATABASE fpa_db;
CREATE USER fpa_user WITH PASSWORD 'your-secure-password';
ALTER ROLE fpa_user SET client_encoding TO 'utf8';
ALTER ROLE fpa_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE fpa_user SET default_transaction_deferrable TO on;
ALTER ROLE fpa_user SET default_transaction_isolation TO 'read committed';
GRANT ALL PRIVILEGES ON DATABASE fpa_db TO fpa_user;
\q
```

### Step 2.3: Create Cloud SQL Auth Proxy (for local testing)
```bash
# Cloud Run will use Cloud SQL Proxy automatically
# For local dev, install:
wget https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64
chmod +x cloud_sql_proxy.linux.amd64
```

---

## Phase 3: Cloud Storage Setup

### Step 3.1: Create Storage Bucket
```bash
gsutil mb -l $REGION gs://$PROJECT_ID-fpa-media

# Configure bucket
gsutil versioning set off gs://$PROJECT_ID-fpa-media
gsutil lifecycle set - <<< '{
  "lifecycle": {
    "rule": [
      {"action": {"type": "Delete"}, "condition": {"age": 90}}
    ]
  }
}'
```

### Step 3.2: Create Service Account for App
```bash
# Create service account
gcloud iam service-accounts create fpa-app \
  --display-name="FPA Web App Service Account"

# Grant Cloud Storage access
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:fpa-app@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

# Grant Cloud SQL access
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:fpa-app@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client"

# Create and download key
gcloud iam service-accounts keys create key.json \
  --iam-account=fpa-app@$PROJECT_ID.iam.gserviceaccount.com
```

---

## Phase 4: Update Django App for GCP

### Step 4.1: Update Settings

**Create `fpa_web/config/settings/gcp.py`:**
```python
from .base import *
import os

# GCP Configuration
DEBUG = False
ALLOWED_HOSTS = ['*.run.app', 'fpa-scoping.example.com']
CSRF_TRUSTED_ORIGINS = ['https://*.run.app']

# Cloud SQL via Cloud SQL Auth Proxy
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'fpa_db',
        'USER': 'fpa_user',
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': '/cloudsql/fpa-scoping:us-central1:fpa-postgres',
        'PORT': '5432',
    }
}

# Cloud Storage
DEFAULT_FILE_STORAGE = 'storages.backends.gcloud.GoogleCloudStorage'
GS_BUCKET_NAME = os.environ.get('GS_BUCKET_NAME', 'fpa-scoping-fpa-media')
GS_DEFAULT_ACL = 'public-read'
GS_PROJECT_ID = os.environ.get('GCP_PROJECT_ID')

# Static files (serve from Cloud Storage)
STATIC_URL = f'https://storage.googleapis.com/{GS_BUCKET_NAME}/static/'
STATICFILES_STORAGE = 'storages.backends.gcloud.GoogleCloudStorage'

# Media files
MEDIA_URL = f'https://storage.googleapis.com/{GS_BUCKET_NAME}/media/'
MEDIA_ROOT = f'gs://{GS_BUCKET_NAME}/media/'

# Security
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = True

# Celery configuration for Cloud Run
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_TASK_ALWAYS_EAGER = False  # Use async in production
```

### Step 4.2: Install GCS Storage Backend
```bash
cd /workspaces/ss-tool/fpa_web
pip install django-storages[google]
```

### Step 4.3: Create Dockerfile

**Create `fpa_web/Dockerfile`:**
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    libpq-dev \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Create static directory
RUN mkdir -p /app/staticfiles

# Collect static files
RUN python manage.py collectstatic --noinput --settings=config.settings.gcp

# Run migrations and start server
CMD ["sh", "-c", "python manage.py migrate --settings=config.settings.gcp && gunicorn config.wsgi:application --bind 0.0.0.0:8080 --timeout 120"]
```

### Step 4.4: Create requirements.txt
```bash
# From your Codespaces environment
cd /workspaces/ss-tool/fpa_web
pip freeze > requirements.txt

# Add GCP-specific packages
cat >> requirements.txt << 'EOF'
django-storages[google]==1.14.2
google-cloud-storage==2.10.0
google-cloud-tasks==2.14.0
gunicorn==21.2.0
psycopg2-binary==2.9.9
EOF
```

---

## Phase 5: GPU Worker Setup

### Step 5.1: Create Compute Engine Instance with GPU

```bash
# Create instance
gcloud compute instances create gpu-worker-1 \
  --machine-type=n1-standard-4 \
  --zone=$ZONE \
  --accelerator=type=nvidia-tesla-t4,count=1 \
  --image-family=ubuntu-2004-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=100GB \
  --preemptible  # Optional: save 70% cost (can be terminated)
```

### Step 5.2: Setup GPU Worker

**SSH into the instance:**
```bash
gcloud compute ssh gpu-worker-1 --zone=$ZONE
```

**On the GPU instance, run:**
```bash
#!/bin/bash
set -e

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install CUDA 12.1
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/cuda-ubuntu2004.pin
sudo mv cuda-ubuntu2004.pin /etc/apt/preferences.d/cuda-repository-pin-600
sudo apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/3bf863cc.pub
sudo add-apt-repository "deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/ /"
sudo apt-get update
sudo apt-get install cuda-toolkit-12-1 -y

# Install cuDNN
# Download from NVIDIA (requires account)
# or use: sudo apt-get install libcudnn8 libcudnn8-dev

# Install Python and dependencies
sudo apt-get install -y python3.12 python3.12-venv python3-pip
python3.12 -m pip install --upgrade pip

# Clone repo
cd /opt
sudo git clone https://github.com/curtisleewaterboer-arch/ss-tool.git
cd ss-tool/fpa_web
sudo python3.12 -m pip install -r requirements.txt

# Install LingBot dependencies
sudo python3.12 -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Download model checkpoint
mkdir -p /opt/checkpoints
cd /opt/checkpoints
python3.12 << 'PYTHON_EOF'
from huggingface_hub import hf_hub_download
hf_hub_download(repo_id="robbyant/lingbot-map", filename="lingbot-map.pt", cache_dir="/opt/checkpoints")
PYTHON_EOF

# Create systemd service for worker
sudo tee /etc/systemd/system/fpa-gpu-worker.service > /dev/null <<EOF
[Unit]
Description=FPA GPU Worker
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/ss-tool/fpa_web
Environment="LINGBOT_CHECKPOINT_PATH=/opt/checkpoints/models--robbyant--lingbot-map/snapshots/latest/lingbot-map.pt"
Environment="DJANGO_SETTINGS_MODULE=config.settings.gcp"
User=ubuntu
ExecStart=/usr/bin/python3.12 -m celery -A config worker -l info
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable fpa-gpu-worker
sudo systemctl start fpa-gpu-worker
```

---

## Phase 6: Deploy Django App to Cloud Run

### Step 6.1: Build and Push Docker Image

```bash
cd /workspaces/ss-tool/fpa_web

# Build image
docker build -t gcr.io/$PROJECT_ID/fpa-web:latest .

# Push to Google Container Registry
docker push gcr.io/$PROJECT_ID/fpa-web:latest
```

### Step 6.2: Deploy to Cloud Run

```bash
gcloud run deploy fpa-web \
  --image gcr.io/$PROJECT_ID/fpa-web:latest \
  --platform managed \
  --region $REGION \
  --memory 1Gi \
  --cpu 1 \
  --timeout 120 \
  --set-env-vars "\
    DJANGO_SETTINGS_MODULE=config.settings.gcp,\
    GCP_PROJECT_ID=$PROJECT_ID,\
    GS_BUCKET_NAME=$PROJECT_ID-fpa-media,\
    DB_PASSWORD=your-secure-password,\
    SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  --service-account fpa-app@$PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated
```

### Step 6.3: Get Cloud Run URL
```bash
gcloud run services describe fpa-web --region $REGION --format='value(status.url)'
```

---

## Phase 7: Connect Redis (for Celery)

### Option A: Google Cloud Memorystore (Recommended)
```bash
gcloud redis instances create fpa-redis \
  --size=1 \
  --region=$REGION \
  --redis-version=7.0
```

### Option B: Self-hosted Redis on Compute Engine
```bash
# Create another instance
gcloud compute instances create redis-instance \
  --machine-type=f1-micro \
  --zone=$ZONE

# SSH and install Redis
gcloud compute ssh redis-instance --zone=$ZONE

# On the instance:
sudo apt-get update
sudo apt-get install redis-server -y
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

---

## Phase 8: Configure Celery for Cloud Run

Update `fpa_web/config/settings/gcp.py`:
```python
# Use Cloud Memorystore Redis
CELERY_BROKER_URL = 'redis://10.0.0.3:6379/0'  # Internal IP of Redis instance
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_ALWAYS_EAGER = False
```

---

## Phase 9: Run Initial Migrations

```bash
# From local machine with Cloud SQL Proxy
./cloud_sql_proxy -instances=fpa-scoping:us-central1:fpa-postgres=tcp:5432 &

# Run migrations
DJANGO_SETTINGS_MODULE=config.settings.gcp \
DB_PASSWORD=your-secure-password \
python manage.py migrate

# Create superuser
DJANGO_SETTINGS_MODULE=config.settings.gcp \
DB_PASSWORD=your-secure-password \
python manage.py createsuperuser
```

---

## Phase 10: Testing

### Test Django App
```bash
CLOUD_RUN_URL=$(gcloud run services describe fpa-web --region $REGION --format='value(status.url)')
curl $CLOUD_RUN_URL
```

### Test Inference Queue
```bash
# From GPU worker instance, check logs:
sudo journalctl -u fpa-gpu-worker -f
```

---

## Monitoring & Costs

### Monitor Costs
```bash
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="FPA Scoping Budget" \
  --budget-amount=100 \
  --threshold-rule=percent=50,percent=90,percent=100
```

### View Logs
```bash
# Cloud Run logs
gcloud run logs read fpa-web --region=$REGION --limit=50

# GPU worker logs
gcloud compute ssh gpu-worker-1 --zone=$ZONE -- sudo journalctl -u fpa-gpu-worker -f
```

---

## Cost Breakdown (Monthly)

| Service | Cost |
|---------|------|
| Cloud Run (Django) | $10-30 |
| Cloud SQL (db-f1-micro) | $15 |
| Cloud Storage | $1-5 |
| Compute Engine (idle) | $15-30 |
| Memorystore Redis | $10-15 |
| **Per 271-frame scan** | **~$0.125** |
| **Base monthly** | **~$50-80** |

---

## Troubleshooting

### Django won't connect to Cloud SQL
```bash
# Check Cloud SQL Proxy is running
gcloud sql instances describe fpa-postgres --format='value(state)'

# Verify service account has permissions
gcloud projects get-iam-policy $PROJECT_ID --flatten="bindings[].members" --filter="bindings.members:fpa-app@"
```

### GPU worker not processing tasks
```bash
# SSH into worker and check status
gcloud compute ssh gpu-worker-1 --zone=$ZONE
sudo systemctl status fpa-gpu-worker
sudo journalctl -u fpa-gpu-worker -20
```

### Cloud Storage access denied
```bash
# Verify service account has Cloud Storage Admin role
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:fpa-app@"
```

---

## Next Steps

1. **Domain setup**: Point your domain to Cloud Run
2. **SSL certificate**: Auto-provisioned by Cloud Run
3. **Backups**: Enable Cloud SQL automated backups
4. **Monitoring**: Set up Cloud Monitoring alerts
5. **CI/CD**: Add GitHub Actions to auto-deploy on push

