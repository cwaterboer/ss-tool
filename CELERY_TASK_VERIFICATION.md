# Celery/Redis Task Queue Verification Guide

## Architecture Overview

```
┌─────────────────────┐
│   Cloud Run App     │  Django+Gunicorn on port 8080
│  (fpa-web-00015)    │  - Receives scan upload
│                     │  - Calls: run_scan.delay(scan_id)
└──────────┬──────────┘
           │ Submits task
           ▼
┌─────────────────────┐
│   Redis Broker      │  In-memory message queue
│  10.112.227.243:    │  - Celery BROKER_URL
│    6379/0           │  - Celery RESULT_BACKEND
└──────────┬──────────┘
           │ Worker polls queue
           ▼
┌─────────────────────────────────────────────┐
│   GPU Worker (fpa-gpu-worker)               │
│   Instance: europe-west1-c, 34.53.182.156   │
│   - Celery service running via systemd      │
│   - Listens to Redis queue                  │
│   - Runs: run_scan(scan_id)                 │
│   - LingBot-Map inference on NVIDIA L4 GPU  │
└─────────────────────────────────────────────┘
```

## Configuration Verification

### Cloud Run Service (fpa-web)
✅ **Verified Settings:**
- Django Settings Module: `config.settings.gcp`
- Celery Broker: `redis://10.112.227.243:6379/0`
- Celery Result Backend: Same as broker
- Task Time Limit: 7200s (2 hours)

**Code Flow:**
1. User uploads video/images via `/sites/<id>/scans/new/`
2. `ScanCreateView.form_valid()` saves scan to database
3. Calls `run_scan.delay(str(scan.id))` (Line 59 of views.py)
4. Task is serialized (JSON) and sent to Redis

### GPU Worker (fpa-gpu-worker)
✅ **Verified Settings:**
- REDIS_URL: `redis://10.112.227.243:6379/0`
- Celery Service: Running via systemd
- Status: READY (reported)

**Code Setup:**
- `/etc/systemd/system/fpa-gpu-worker.service` manages Celery worker
- Worker connects to Redis and polls for tasks
- Task Type: `apps.scans.tasks.run_scan`

### Celery Task Definition
✅ **Verified Configuration:**
```python
# apps/scans/tasks.py, line 71
@shared_task(bind=True, max_retries=0, time_limit=7200)
def run_scan(self, scan_id: str):
    # GPU inference happens here
    # Updates scan.status = PROCESSING/DONE/FAILED
```

**Imports Chain:**
- `config/__init__.py` imports `celery.py`
- `celery.py` calls `app.autodiscover_tasks()` 
- Finds `apps/scans/tasks.py` automatically
- ✅ No manual registration needed

## How to Verify Task Flow

### Step 1: Check Redis Connectivity from GPU Worker

```bash
# SSH into GPU worker
ssh -i ~/.ssh/gcp_key ubuntu@34.53.182.156

# Test Redis
redis-cli -h 10.112.227.243 -p 6379 PING
# Expected: PONG

# Check queue depth
redis-cli -h 10.112.227.243 -p 6379 LLEN celery
# Expected: number of pending tasks (0 if idle)
```

### Step 2: Check Celery Worker Status

```bash
# On GPU worker
sudo systemctl status fpa-gpu-worker
# Look for: "Active: active (running)"

# Check recent logs
sudo journalctl -u fpa-gpu-worker -n 50 -f
# Should show: "Worker pool ready" or task processing
```

### Step 3: Create a Test Scan and Monitor

**On Cloud Run:**
1. Login at https://fpa-web-369870387328.europe-west1.run.app/accounts/login/
   - Username: `admin`
   - Password: `admin`

2. Create a site (e.g., "Test Site")

3. Upload a test video/image archive to start a scan

4. Note the Scan ID from the URL: `/sites/<site-id>/scans/<scan-id>/`

**On GPU Worker (in another terminal):**

```bash
ssh -i ~/.ssh/gcp_key ubuntu@34.53.182.156

# Monitor logs for task pickup
sudo journalctl -u fpa-gpu-worker -f

# Expected sequence:
# - "Received task: apps.scans.tasks.run_scan[xxx]"
# - "[scan:xxx] started"
# - "[scan:xxx] 150 frames"
# - "[scan:xxx] inference mode=direct"
# - "[scan:xxx] inference done in 45.2s"
# - "[scan:xxx] ✓ DONE"
```

### Step 4: Query Task Status via Redis

```bash
# While task is running
redis-cli -h 10.112.227.243 -p 6379 KEYS "*"
# Should see keys like: celery-task-meta-<task-id>

# Get task metadata
redis-cli -h 10.112.227.243 -p 6379 GET celery-task-meta-<task-id>
# Should show: task status (PENDING/STARTED/SUCCESS)
```

### Step 5: Verify Task in Database

```bash
# Check scan status via web UI
# Visit scan detail page to see status progression:
# PENDING → PROCESSING → DONE (or FAILED)

# Or query directly on Cloud Run via Django shell:
# gcloud run services exec fpa-web --region=europe-west1 -- python manage.py shell

from apps.scans.models import Scan
scan = Scan.objects.first()
print(f"Status: {scan.status}")
print(f"Celery Task ID: {scan.celery_task_id}")
print(f"Started: {scan.started_at}")
```

## Expected Behavior

### When Scan is Created
1. ✅ Scan object saved to PostgreSQL with status=PENDING
2. ✅ Task submitted to Redis (visible as queue entry)
3. ✅ User redirected to scan detail page
4. ✅ Page shows "Processing..." status

### When GPU Worker Picks Up Task
1. ✅ Worker logs show "Received task"
2. ✅ Scan status changes to PROCESSING in database
3. ✅ Task starts LingBot-Map inference
4. ✅ GPU utilization visible on worker (nvidia-smi)

### When Task Completes
1. ✅ Scan status changes to DONE
2. ✅ Results saved (floor_mask, point cloud, etc.)
3. ✅ Web UI displays results
4. ✅ Task removed from Redis queue

## Troubleshooting Checklist

### Issue: Task Not Submitted to Redis
**Indicators:** Scan stays PENDING, no task in Redis queue

**Check:**
```bash
# 1. Verify Redis URL in Cloud Run
gcloud run services describe fpa-web --region=europe-west1 | grep REDIS

# 2. Check Django logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=fpa-web" --limit=50
```

**Fix:**
- Verify REDIS_URL env var is set correctly
- Test Redis connectivity: `redis-cli -h 10.112.227.243 -p 6379 PING`

### Issue: Worker Not Receiving Tasks
**Indicators:** Tasks in queue, but GPU not processing

**Check:**
```bash
# On GPU worker
sudo systemctl status fpa-gpu-worker
sudo journalctl -u fpa-gpu-worker -n 50

# Check worker status
celery -A config inspect status
```

**Fix:**
- Restart worker: `sudo systemctl restart fpa-gpu-worker`
- Check Redis connectivity from worker
- Verify CELERY_BROKER_URL in GPU worker environment

### Issue: Task Fails/Times Out
**Indicators:** Scan status is FAILED, error_message populated

**Check:**
```bash
# GPU worker logs
sudo journalctl -u fpa-gpu-worker -n 200

# Look for: FAILED, Exception, Traceback

# Check available GPU
nvidia-smi

# Check disk space
df -h /home/codespace/
```

**Fix:**
- Restart GPU worker
- Check GPU status and cooling
- Verify checkpoint file exists: `/home/codespace/checkpoints/lingbot-map.pt`

## Environment Variables Reference

**Cloud Run (fpa-web):**
```
DJANGO_SETTINGS_MODULE=config.settings.gcp
REDIS_URL=redis://10.112.227.243:6379/0
POSTGRES_HOST=/cloudsql/ss-tool-498115:europe-west1:fpa-postgres
```

**GPU Worker (fpa-gpu-worker):**
```
REDIS_URL=redis://10.112.227.243:6379/0
CELERY_BROKER_URL=redis://10.112.227.243:6379/0
CHECKPOINT_PATH=/home/codespace/checkpoints/lingbot-map.pt
```

## Celery Configuration Details

**Django Settings (config/settings/base.py):**
```python
CELERY_BROKER_URL = env('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_TIME_LIMIT = 7200  # 2 hours for GPU inference
```

**Celery App (config/celery.py):**
```python
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
app = Celery('fpa_web')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()  # Automatically finds apps/*/tasks.py
```

## Summary

✅ **End-to-End Task Flow is Configured Correctly:**

1. **Task Definition:** `run_scan()` decorated with `@shared_task`
2. **Task Submission:** Called via `run_scan.delay()` in view
3. **Message Broker:** Redis at `10.112.227.243:6379/0`
4. **Result Backend:** Same Redis instance
5. **Worker Setup:** Celery service on GPU worker listening to queue
6. **Task Execution:** Worker runs LingBot-Map inference when task arrives

**To Verify:** Create a test scan and check GPU worker logs for task processing.
