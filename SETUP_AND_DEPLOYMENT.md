# Setup and Deployment Guide

## Quick Start (Local Development)

### Automated Setup (Recommended)
```bash
# From the repo root:
./setup.sh
```

This script will:
1. ✓ Create a Python virtual environment
2. ✓ Install all dependencies from `fpa_web/requirements.txt`
3. ✓ Download the 4.6GB LingBot-Map checkpoint (one-time)
4. ✓ Setup the SQLite database with migrations
5. ✓ Create demo admin account (username: `demo`, password: `demo`)

### Manual Setup
If you prefer to setup manually:

```bash
# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r fpa_web/requirements.txt

# 3. Download model checkpoint
python fpa_web/scripts/download_checkpoint.py

# 4. Setup database
cd fpa_web
python manage.py migrate --settings=config.settings.local

# 5. Create admin account (optional)
python manage.py createsuperuser

# 6. Run development server
python manage.py runserver
```

---

## Running the Development Server

```bash
cd fpa_web
source ../venv/bin/activate
python manage.py runserver
```

Then open: **http://localhost:8000**

**Admin credentials:**
- Username: `demo`
- Password: `demo`

---

## Checkpoint Management

### What is lingbot-map.pt?

The **lingbot-map.pt** checkpoint is a 4.6GB pre-trained deep learning model for 3D scene reconstruction. It is:
- **NOT in version control** (too large for GitHub)
- **Automatically downloaded** from HuggingFace Hub on first setup
- **Cached locally** so subsequent runs skip the download

### Download Details

**Repository:** [robbyant/lingbot-map](https://huggingface.co/robbyant/lingbot-map)  
**Size:** 4.6 GB  
**Download Time:** 10-30 minutes (depends on internet speed)  
**Location:** `/tmp/checkpoints/lingbot-map.pt` (by default)

### Using a Custom Checkpoint

If you want to use a different checkpoint path:

```bash
# Option 1: Set environment variable
export LINGBOT_CHECKPOINT_PATH=/path/to/your/model.pt
python manage.py runserver

# Option 2: Update Django settings
# Edit fpa_web/config/settings/local.py:
LINGBOT_CHECKPOINT_PATH = '/path/to/your/model.pt'
```

### Manual Download

If automatic download fails, download manually:

```bash
# Using huggingface_hub CLI
huggingface-cli download robbyant/lingbot-map lingbot-map.pt

# Or via Python
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id="robbyant/lingbot-map",
    filename="lingbot-map.pt"
)
```

---

## Git and Large Files

### Why isn't lingbot-map.pt in the repo?

- **GitHub file limit:** 1GB max per file
- **Repository bloat:** 4.6GB repository is slow to clone
- **Best practice:** Large binary assets shouldn't be in version control

### How to push code to GitHub

The `.gitignore` file already excludes `*.pt` files:

```bash
# Verify large files aren't staged
git status | grep -i ".pt"

# If you see any .pt files, remove them from git:
git rm --cached path/to/file.pt

# Now commit and push normally
git add .
git commit -m "Your commit message"
git push origin main
```

### Checkpoint Download in Production (Docker)

The `Dockerfile` automatically downloads the checkpoint during build:

```dockerfile
# In Dockerfile, during build:
RUN python scripts/download_checkpoint.py
```

This ensures every deployed instance has the checkpoint without storing it in the image.

---

## Project Structure

```
/workspaces/ss-tool/
├── fpa_web/                          # Django web app
│   ├── config/
│   │   └── settings/
│   │       ├── base.py               # Shared settings
│   │       ├── local.py              # Development (CPU fallback)
│   │       ├── gcp.py                # Production (GCP Cloud Run + GPU worker)
│   │       └── docker.py             # Docker settings
│   ├── apps/
│   │   ├── scans/                    # Scan management
│   │   ├── sites/                    # Site listing
│   │   └── ...
│   ├── templates/                    # HTML templates
│   ├── static/                       # CSS, JS, images
│   ├── scripts/
│   │   └── download_checkpoint.py    # Checkpoint downloader
│   ├── manage.py
│   └── requirements.txt
├── lingbot_map/                      # ML model code
│   ├── layers/                       # Vision transformer layers
│   ├── models/                       # Model definitions
│   ├── aggregator/                   # Feature aggregation
│   └── ...
├── setup.sh                          # Automated setup script
├── GITHUB_PUSH_GUIDE.md              # Large file handling strategy
├── GCP_DEPLOYMENT_GUIDE.md           # Production deployment (Option A)
└── README.md                         # Project overview
```

---

## Database

### Development (SQLite)

Default for local development:
```python
# fpa_web/config/settings/local.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
```

### Production (PostgreSQL on Cloud SQL)

See [GCP_DEPLOYMENT_GUIDE.md](GCP_DEPLOYMENT_GUIDE.md#phase-2-setup-cloud-sql-postgresql) for details on setting up PostgreSQL.

---

## Environment Variables

### Development (local.py)
```bash
# Optional - these have defaults:
export DEBUG=True
export ALLOWED_HOSTS=localhost,127.0.0.1
export CHECKPOINT_ROOT=/tmp/checkpoints
```

### Production (GCP)
See [GCP_DEPLOYMENT_GUIDE.md](GCP_DEPLOYMENT_GUIDE.md#phase-8-celery-configuration) for Cloud Run environment variables.

---

## Inference Pipeline

### Local Development (CPU Fallback)

Inference runs on CPU with memory optimization:
- **Precision:** float32 (stable on CPU)
- **Gradient Checkpointing:** Enabled (reduces memory)
- **Performance:** ~30-60s per frame
- **Suitable for:** Small test scans (25-100 frames)

**Limitations:**
- Codespaces: Cannot handle 200+ frame scans (memory insufficient)
- Local machine: Depends on available RAM

### Production (GPU on Compute Engine)

Inference runs on NVIDIA T4 GPU:
- **Precision:** float16 with AMP autocast (fast + memory-efficient)
- **Gradient Checkpointing:** Disabled (not needed on GPU)
- **Performance:** ~1-2s per frame
- **Suitable for:** Large retail walkthroughs (200+ frames)

**Cost:** ~$0.125 per scan (~5-15 minutes inference)

---

## Testing Scans

### Small Test Scan (Recommended)
```
Input: 25-50 frames
Duration: 5-30 minutes (CPU)
Size: ~100MB
→ Use this to validate the pipeline
```

### Medium Test Scan
```
Input: 50-100 frames
Duration: 30-120 minutes (CPU) or 5-10 minutes (GPU)
Size: ~200-400MB
→ Use this to test artifact generation
```

### Large Production Scan
```
Input: 200-400 frames
Duration: Not feasible on CPU
Duration: 15-60 minutes (GPU)
Size: ~1-2GB
→ Only on GPU deployment
```

---

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'lingbot_map'"

**Solution:** Make sure you're in the correct directory and venv is activated:
```bash
cd /workspaces/ss-tool
source venv/bin/activate
cd fpa_web
python manage.py runserver
```

### Issue: Checkpoint download fails

**Symptoms:**
```
✗ Download failed: [connection error or timeout]
```

**Solutions:**
1. Check internet connection
2. Verify disk space: `df -h | grep /tmp`
3. Try again later (HuggingFace may be temporarily unavailable)
4. [Download manually](https://huggingface.co/robbyant/lingbot-map)
5. Use a different checkpoint with `LINGBOT_CHECKPOINT_PATH`

### Issue: "Connection refused" when running inference

**Symptoms:** Redis connection error when running scans

**Solutions:**
```bash
# In development, Celery runs synchronously, so Redis isn't needed
# But make sure you're using local.py settings:
python manage.py runserver --settings=config.settings.local

# If you get "Connection refused" on localhost:6379, either:
# 1. Skip - local dev doesn't require Redis
# 2. Start Redis: redis-server
```

### Issue: Scan marked PENDING but not processing

**Symptoms:**
```
Scan status stays PENDING; no progress
Django logs show no task output
```

**Solutions:**
1. Check Django logs: `python manage.py runserver 2>&1 | grep -i error`
2. Check database status: `python manage.py shell` → `Scan.objects.get(id=...)`
3. Ensure CELERY_TASK_ALWAYS_EAGER=True in local.py (for synchronous task execution)
4. Check available memory: `free -h` (need 2GB+ for large scans)

---

## Next Steps

### Option 1: Test on CPU (Recommended First)
1. Run setup.sh
2. Upload a small 25-50 frame test scan
3. Monitor processing in Django admin
4. Verify artifacts are generated

### Option 2: Deploy to GCP
See [GCP_DEPLOYMENT_GUIDE.md](GCP_DEPLOYMENT_GUIDE.md) for:
- Setting up Cloud SQL, Cloud Storage, Redis
- Deploying Django app to Cloud Run
- Setting up GPU worker on Compute Engine
- End-to-end testing on GPU

---

## FAQ

**Q: Can I use a different CUDA version?**  
A: The code auto-detects available hardware. It will use GPU if detected, otherwise fallback to CPU.

**Q: How long does inference take?**  
A: Depends on frame count and hardware:
- **50 frames on CPU:** 30 min
- **271 frames on CPU:** Not feasible (memory error)
- **271 frames on GPU:** 5-15 minutes

**Q: Can I process multiple scans simultaneously?**  
A: In development, tasks run sequentially (CELERY_TASK_ALWAYS_EAGER=True).  
In production (GCP), use multiple GPU workers or a task queue.

**Q: Do I need GPU for development?**  
A: No. CPU works fine for testing the pipeline with small scans.

**Q: Where are the outputs stored?**  
A: In `fpa_web/media/scans/{scan_id}/`:
- `point_cloud.ply` - 3D point cloud
- `scene_manifest.json` - Scene metadata
- `camera_path.json` - Camera poses
- `preview.jpg` - Thumbnail

