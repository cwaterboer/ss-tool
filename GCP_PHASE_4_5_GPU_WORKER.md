# Phase 4-5: GPU Worker Setup on Google Cloud Platform

## Overview

This phase sets up a GPU-accelerated Celery worker on Google Compute Engine that processes 3D scans using the LingBot-Map model. The worker connects to your local Redis broker for testing, then switches to Cloud Memorystore for production.

**Timeline:** 45-60 minutes
**Cost:** ~$0.40/hour for n1-standard-4 + T4 GPU (can pause when not in use)

---

## Phase 4: Create Compute Engine Instance with GPU

### Step 1: Create the Instance

```bash
# Set variables
export PROJECT_ID="ss-tool-498115"
export REGION="us-central1"
export ZONE="us-central1-a"
export INSTANCE_NAME="fpa-gpu-worker"

# Create instance with T4 GPU
# Breakdown: n1-standard-4 (4 vCPU, 15GB RAM) + 1x T4 GPU
gcloud compute instances create $INSTANCE_NAME \
  --zone=$ZONE \
  --machine-type=n1-standard-4 \
  --accelerator=type=nvidia-tesla-t4,count=1 \
  --image-family=ubuntu-2004-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=50GB \
  --scopes=cloud-platform \
  --enable-display-device=false \
  --project=$PROJECT_ID

# Verify instance is running
gcloud compute instances describe $INSTANCE_NAME --zone=$ZONE --project=$PROJECT_ID
```

**Expected output:** Instance shows `STATUS: RUNNING`

### Step 2: SSH into the Instance

```bash
gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --project=$PROJECT_ID
```

Once connected, you're on the Compute Engine instance. Proceed with the GPU setup script.

---

## Phase 5: Install GPU Dependencies and Celery Worker

### Step 1: Download and Run Setup Script

Inside your SSH session on the Compute Engine instance:

```bash
# Download setup script
curl -O https://raw.githubusercontent.com/curtisleewaterboer-arch/ss-tool/main/setup_gpu_worker.sh
chmod +x setup_gpu_worker.sh

# Run setup (takes ~10-15 minutes)
./setup_gpu_worker.sh
```

This script:
- ✅ Updates system packages
- ✅ Installs CUDA 12.4 and cuDNN 9.1.0
- ✅ Installs PyTorch with GPU support
- ✅ Installs Celery, Redis, and dependencies
- ✅ Creates startup and systemd service files
- ✅ Verifies GPU access with `nvidia-smi`

**Expected output at the end:**
```
GPU verification complete
✅ GPU Worker Setup Complete!
```

### Step 2: Clone or Copy Your Django Project

```bash
cd ~
git clone https://github.com/curtisleewaterboer-arch/ss-tool.git
# or copy files via: gcloud compute scp

cd ~/ss-tool/fpa_web
```

### Step 3: Configure for Your Setup

**For Local Testing (Codespace Django → GPU Worker):**

If your GPU worker needs to connect to your local Redis on Codespaces:

```bash
# Set up SSH tunnel from Compute Engine → your Codespaces Redis
# In a new terminal on your LOCAL machine:
gcloud compute ssh fpa-gpu-worker --zone=us-central1-a \
  --tunnel-through-iap \
  -- -L 6379:localhost:6379

# Then on the GPU worker, set:
export REDIS_URL="redis://localhost:6379/0"  # Via SSH tunnel
```

Or, easier approach: **Start Redis on the Compute Engine instance:**

```bash
# SSH into the instance
sudo apt-get install -y redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Verify Redis is running
redis-cli ping  # Should output: PONG
```

Then local Django connects to: `REDIS_URL=redis://INSTANCE_EXTERNAL_IP:6379/0`

**For Production (Django → GPU Worker → Cloud Memorystore):**

Set environment variables:

```bash
export REDIS_URL="redis://10.0.0.3:6379/0"  # Cloud Memorystore internal IP
export DJANGO_SETTINGS_MODULE="config.settings.gcp"
export POSTGRES_PASSWORD="your-secure-password"
export POSTGRES_HOST="cloudsql-proxy"  # Assuming Cloud SQL Proxy is running
export SECRET_KEY="your-django-secret-key"
export GCP_PROJECT_ID="ss-tool-498115"
```

### Step 4: Download Checkpoint (First Time Only)

```bash
cd ~/ss-tool
source ~/gpu_worker_env/bin/activate
python fpa_web/scripts/download_checkpoint.py
```

This downloads the 4.6GB LingBot-Map model from HuggingFace.

### Step 5: Start Celery Worker

**Option A: Direct Command (for testing)**

```bash
cd ~/ss-tool/fpa_web
source ~/gpu_worker_env/bin/activate

celery -A config.celery worker \
  --loglevel=info \
  --concurrency=1 \
  --prefetch-multiplier=1 \
  --pool=solo \
  --broker=redis://localhost:6379/0
```

Expected output:
```
 ___      _ _ _
| _ | ___| | ___| | _ | ___
| _ \/ __| | |_| |_|
|___/\__\_|_____|\__|

celery@fpa-gpu-worker v5.3.5 (opalescent)

...ready to accept tasks
```

**Option B: Systemd Service (for production)**

```bash
# Enable and start service
sudo systemctl enable celery-gpu-worker.service
sudo systemctl start celery-gpu-worker.service

# Check status
sudo systemctl status celery-gpu-worker.service

# View logs
sudo journalctl -u celery-gpu-worker.service -f
```

---

## Testing the GPU Worker

### From Your Local Machine

```bash
# 1. Start Django locally
cd /workspaces/ss-tool/fpa_web
python manage.py runserver --settings=config.settings.local

# 2. In another terminal, verify Celery can reach the worker
python manage.py shell
>>> from config.celery import app
>>> result = app.send_task('config.tasks.ping_worker')
>>> result.get(timeout=5)  # Should return 'pong' if worker is reachable
```

### Create a Test Scan

1. Open http://localhost:8000 in browser
2. Upload a short test video (10-20 frames)
3. Submit as scan
4. Check GPU worker terminal for processing logs
5. Monitor GPU usage: `watch nvidia-smi` (on the instance)

Expected:
- Scan status: PENDING → PROCESSING → DONE
- GPU terminal shows frame-by-frame progress
- Frame processing time: ~1-2 seconds per frame on T4

---

## Network Configuration

### Local Testing (Codespace + GPU Worker)

```
Your Codespace (localhost:8000)
    ↓
    REDIS_URL=redis://INSTANCE_IP:6379/0
    ↓
Compute Engine (Redis + Celery worker)
    ↓
GPU processes frames
    ↓
Results back to Codespace via Redis
```

**Required:** Firewall rule to allow port 6379 from your IP

```bash
gcloud compute firewall-rules create allow-redis-dev \
  --allow=tcp:6379 \
  --source-ranges=YOUR_IP/32 \
  --description="Allow Redis from dev machine"
```

### Production (Cloud Run + GPU Worker + Cloud Memorystore)

```
Cloud Run (Django)
    ↓
    REDIS_URL=redis://cloud-memorystore-ip:6379/0
    ↓
Cloud Memorystore (Redis)
    ↓
    Private network connection to Compute Engine
    ↓
Compute Engine GPU Worker
```

**No firewall rules needed** — all on private VPC.

---

## Configuration Summary

| Aspect | Local Testing | Production |
|--------|-------------|-----------|
| Django | Codespace (localhost:8000) | Cloud Run |
| Redis | Compute Engine instance | Cloud Memorystore |
| Redis URL | `redis://INSTANCE_IP:6379/0` | `redis://10.0.0.3:6379/0` |
| Settings | `config.settings.local` | `config.settings.gcp` |
| Database | SQLite | Cloud SQL PostgreSQL |
| Storage | Local `/media/` | Google Cloud Storage |
| GPU Worker | Compute Engine n1-standard-4 + T4 | Same (reusable) |

---

## Monitoring and Costs

### Monitor GPU Usage

```bash
# On the Compute Engine instance
watch nvidia-smi

# Monitor Celery worker
sudo journalctl -u celery-gpu-worker.service -f
```

### Estimate Costs

- **n1-standard-4:** $0.19/hour
- **NVIDIA T4 GPU:** $0.35/hour
- **Total:** $0.54/hour (~$13/day if running 24/7)

**Cost optimization:**
- Pause instance when not processing: `gcloud compute instances stop fpa-gpu-worker`
- Resume: `gcloud compute instances start fpa-gpu-worker`
- Cost drops to ~$0.005/day when stopped

### Pause/Resume Instance

```bash
# Pause (stops billing)
gcloud compute instances stop fpa-gpu-worker --zone=us-central1-a

# Resume
gcloud compute instances start fpa-gpu-worker --zone=us-central1-a
```

---

## Troubleshooting

### GPU Not Detected

```bash
nvidia-smi  # Should show GPU info

# If not found, check driver:
sudo nvidia-smi  # May need sudo
```

### Celery Worker Won't Connect to Redis

```bash
# Verify Redis is running
redis-cli ping

# Check connection
redis-cli CLIENT LIST

# Verify network firewall
gcloud compute firewall-rules list
```

### Django Can't Reach GPU Worker

```bash
# Test connection from Django
python manage.py shell
>>> import redis
>>> r = redis.Redis.from_url('redis://INSTANCE_IP:6379/0')
>>> r.ping()  # Should return True
```

### Model Takes Too Long

```bash
# Check GPU is being used
watch nvidia-smi  # GPU-Util should be ~90%+

# Check if CPU fallback is happening
celery -A config.celery inspect active  # View active tasks
```

---

## Next Steps

✅ **Phase 4-5 complete!**

Proceed to:
- **Phase 6:** Create Cloud SQL PostgreSQL database
- **Phase 7:** Set up Cloud Storage bucket
- **Phase 8:** Deploy Django app to Cloud Run
- **Phase 9:** Configure CI/CD pipeline
- **Phase 10:** Test end-to-end production deployment

Once confident with local GPU testing, run the Fourth Scan (271 frames) and watch it complete in 5-15 minutes instead of timing out! 🎉

---

## Quick Reference Commands

```bash
# SSH into GPU instance
gcloud compute ssh fpa-gpu-worker --zone=us-central1-a

# Monitor GPU
watch nvidia-smi

# Restart worker
sudo systemctl restart celery-gpu-worker.service

# View logs
sudo journalctl -u celery-gpu-worker.service -n 100

# Stop instance (pause billing)
gcloud compute instances stop fpa-gpu-worker --zone=us-central1-a

# List all instances
gcloud compute instances list

# Delete instance (irreversible!)
gcloud compute instances delete fpa-gpu-worker --zone=us-central1-a
```
