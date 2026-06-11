# Cloud Run Deployment - Status Report

## ✅ Successfully Completed

### 1. Docker Files Created
- [Dockerfile](Dockerfile) - Python 3.12 slim image with all dependencies
- [entrypoint.sh](entrypoint.sh) - Gunicorn startup script  
- [.dockerignore](.dockerignore) - Build context optimization

### 2. Django Configuration
- Created [config/wsgi.py](config/wsgi.py) - WSGI application module
- Updated [config/settings/gcp.py](config/settings/gcp.py) - Cloud Run settings with proper ALLOWED_HOSTS
- Fixed requirements.txt - Removed GPU dependencies (torch, lingbot_map) and conflicting version specs

### 3. Docker Image Built & Pushed
- Image: `gcr.io/ss-tool-498115/fpa-web:latest`
- Tags: v2, v3, and production versions pushed to Google Container Registry
- Image size: ~420MB (minimal, no GPU deps)

### 4. Cloud Run Deployment Successful
- Service created: `fpa-web` in `europe-west1`
- URL: https://fpa-web-369870387328.europe-west1.run.app
- Configuration:
  - 1 vCPU, 1Gi memory
  - Gunicorn with 2 workers, 300s timeout
  - CPU boost enabled for faster startup
  - Service account: fpa-app@ss-tool-498115.iam.gserviceaccount.com

### 5. Django Application Responds
- ✅ HTTP responses working (400, 500 error codes = app is running)
- ✅ Gunicorn server starting successfully
- ✅ URL routing working (accessing /admin/login/ triggers Django)
- ✅ Static files configured for Cloud Storage (USE_GCS=true)

---

## ⚠️  Current Issue: Cloud SQL Proxy Not Connecting

### Error
```
psycopg2.OperationalError: connection to server at "127.0.0.1", port 5432 failed: Connection refused
```
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
### Root Cause
The Cloud SQL Auth Proxy sidecar (configured with `--set-cloudsql-instances ss-tool-498115:europe-west1:fpa-postgres`) is not establishing a connection on localhost:5432.

### Why This Occurs
- The Cloud SQL Proxy should start automatically as a sidecar container in Cloud Run
- It needs to be accessible at 127.0.0.1:5432 from the main container
- Current status: The proxy either isn't starting or isn't reachable

### Next Steps to Debug

1. **Verify Cloud SQL Instance Accessibility**
   ```bash
   gcloud sql instances describe fpa-postgres --format='value(state,settings.backupConfiguration.enabled)'
   ```

2. **Check VPC Connectivity**
   - Verify Cloud Run service has network access to Cloud SQL
   - Check if any firewall rules are blocking connections

3. **Test Cloud SQL Proxy Directly**
   ```bash
   gcloud sql connect fpa-postgres --user=adminuser
   ```

4. **Alternative: Skip DB on Startup**
   - Don't access database until a view/page requires it
   - Use lazy database initialization
   - Modify Django middleware to handle connection errors gracefully

5. **Manual Migrations Alternative**
   - Deploy Cloud Run WITHOUT requiring database startup
   - Run migrations manually via Cloud Run jobs or SSH tunnel
   - Use connection pooling that defers initialization

---

## Environment Variables (Current Deployment)

```
DJANGO_SETTINGS_MODULE=config.settings.gcp
SECRET_KEY=test-secret-key-production
POSTGRES_DB=fpa_db
POSTGRES_USER=adminuser
POSTGRES_PASSWORD=jJX+ZENtVVR+bWaeZWdTqfCVjeXFKUfI
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
REDIS_URL=redis://10.112.227.243:6379/0
USE_GCS=true
GCS_BUCKET_NAME=ss-tool-fpa-media
GCP_PROJECT_ID=ss-tool-498115
CLOUD_SQL_CONNECTION_NAME=ss-tool-498115:europe-west1:fpa-postgres
SECURE_SSL_REDIRECT=false
```

---

## Files Modified

- [fpa_web/Dockerfile](Dockerfile) - Container image definition
- [fpa_web/entrypoint.sh](entrypoint.sh) - Startup script
- [fpa_web/.dockerignore](.dockerignore) - Build context
- [fpa_web/requirements.txt](requirements.txt) - Cleaned up dependencies
- [fpa_web/config/wsgi.py](config/wsgi.py) - **NEW** - WSGI application
- [fpa_web/config/settings/gcp.py](config/settings/gcp.py) - Updated ALLOWED_HOSTS

---

## Service URL

🔗 **Cloud Run Service**: https://fpa-web-369870387328.europe-west1.run.app

---

## Quick Deployment Command

```bash
gcloud run deploy fpa-web \
  --image gcr.io/ss-tool-498115/fpa-web:latest \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --set-cloudsql-instances ss-tool-498115:europe-west1:fpa-postgres \
  --service-account fpa-app@ss-tool-498115.iam.gserviceaccount.com \
  --memory 1Gi \
  --cpu 1 \
  --timeout 600 \
  --cpu-boost \
  --set-env-vars="DJANGO_SETTINGS_MODULE=config.settings.gcp,SECRET_KEY=...,POSTGRES_PASSWORD=..."
```

---

## Architecture Summary

```
┌─────────────────────────────┐
│   Google Cloud Run          │
│   fpa-web service           │
├─────────────────────────────┤
│ ┌─────────────────────────┐ │
│ │  Django App (Gunicorn)  │ │
│ │  Port: 8080             │ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │  Cloud SQL Proxy        │ ❌ NOT CONNECTING
│ │  Port: 127.0.0.1:5432   │
│ └─────────────────────────┘ │
└─────────────────────────────┘
          ↓ (attempts to connect)
┌─────────────────────────────┐
│  Cloud SQL PostgreSQL       │
│  ss-tool-498115:europe-west1:fpa-postgres
└─────────────────────────────┘
```

---

## Success Criteria Met

✅ Docker image builds without errors  
✅ Container runs and starts Gunicorn  
✅ Django application imports successfully  
✅ WSGI module works  
✅ Cloud Run deployment successful  
✅ HTTP requests reaching application  
✅ Environment variables configured  
✅ GCS storage configured (not tested)  
✅ Redis configured (not tested)  

❌ Database connectivity (Cloud SQL Proxy sidecar issue)

---

## Notes for Production

1. **Database Password**: Currently using a static test password. Should migrate to Cloud Secret Manager integration.
2. **Django Secret Key**: Using test key. Should use Secret Manager in production.
3. **SECURE_SSL_REDIRECT**: Currently false. Enable for production.
4. **Debug Mode**: Currently off (DEBUG=False), which is correct for production.
5. **Migrations**: Need to establish a process for running migrations at deployment time or via separate jobs.
6. **Static Files**: Configured for Cloud Storage but not tested. Uses django-storages with Google backend.
7. **Media Files**: Configured for Cloud Storage.

