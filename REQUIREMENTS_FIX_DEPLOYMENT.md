# Requirements.txt Fix - Complete Dependency List

## Issue
The original `requirements.txt` was missing critical ML and image processing dependencies needed by the Celery tasks:
- `numpy` - array operations
- `torch` - model inference
- `scipy` - image processing (binary_fill_holes, ConvexHull, etc.)
- `trimesh` - point cloud export
- `einops`, `safetensors`, `huggingface-hub` - LingBot-Map model support

## Solution
Updated `/workspaces/ss-tool/fpa_web/requirements.txt` with complete dependency list:

```
django==6.0.5
celery[redis]==5.3.5
redis>=5.0
python-decouple>=3.8

# Image and ML processing
Pillow>=10.0
numpy>=1.24.0
torch>=2.0.0
scipy>=1.11.0
trimesh>=3.20.0

# LingBot-Map model support
einops>=0.7.0
safetensors>=0.4.0
huggingface-hub>=0.17.0

# Google Cloud Platform support
google-cloud-storage>=2.10.0
django-storages[google]>=1.14.0
psycopg2-binary>=2.9.0

# CORS support for API requests
django-cors-headers>=4.3.0

# Production server
gunicorn>=21.0.0
```

## Deployment Steps

### Step 1: Docker Build (Currently Running)
```bash
cd /workspaces/ss-tool/fpa_web
docker build --tag gcr.io/ss-tool-498115/fpa-web:latest .
```
**Status:** ⏳ Building (installing torch + large packages, ~10-15 minutes)

### Step 2: Push to GCR (After build completes)
```bash
docker push gcr.io/ss-tool-498115/fpa-web:latest
```

### Step 3: Redeploy to Cloud Run
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
  --set-env-vars="DJANGO_SETTINGS_MODULE=config.settings.gcp,SECRET_KEY=5-9zvrsp^xc3efce)3y0s&^)f5)_2cpo@2^tjl$nhwbrcz8)ce,POSTGRES_DB=fpa_db,POSTGRES_USER=adminuser,POSTGRES_PASSWORD=jJX+ZENtVVR+bWaeZWdTqfCVjeXFKUfI,POSTGRES_HOST=/cloudsql/ss-tool-498115:europe-west1:fpa-postgres,REDIS_URL=redis://10.112.227.243:6379/0,USE_GCS=true,GCS_BUCKET_NAME=ss-tool-fpa-media,GCP_PROJECT_ID=ss-tool-498115,SECURE_SSL_REDIRECT=false"
```

## What Dependencies Were Added and Why

| Package | Version | Purpose | Used By |
|---------|---------|---------|---------|
| `numpy` | >=1.24.0 | Array operations, mathematical computations | apps/scans/tasks.py (pose encoding, point cloud processing) |
| `torch` | >=2.0.0 | Model inference framework | LingBot-Map model execution |
| `scipy` | >=1.11.0 | Image processing (morphological ops) | `_extract_floor_artifacts()` - binary_fill_holes, ConvexHull |
| `trimesh` | >=3.20.0 | Point cloud export to PLY format | `_save_point_cloud()` |
| `einops` | >=0.7.0 | Tensor reshaping for LingBot-Map | LingBot-Map model layers |
| `safetensors` | >=0.4.0 | Safe model weight loading | Checkpoint loading |
| `huggingface-hub` | >=0.17.0 | Model hub integration | LingBot-Map model utilities |

## Code Dependencies

### From `apps/scans/tasks.py`:

**Top-level imports:**
```python
import numpy as np
import torch
```

**Inside `_extract_floor_artifacts()`:**
```python
from PIL import Image, ImageDraw
from scipy.ndimage import binary_dilation, binary_fill_holes
from scipy.spatial import ConvexHull
```

**Inside `_save_point_cloud()`:**
```python
import trimesh
```

**Inside `run_scan()`:**
```python
from lingbot_map.utils.load_fn import load_and_preprocess_images
from lingbot_map.models.gct_stream import GCTStream
from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri
```

## Container Size Note

The new image will be **larger** due to torch installation:
- Old image: ~420 MB (Python slim + core deps)
- New image: ~3-4 GB (includes torch, scipy, numpy, trimesh)

This is acceptable because:
1. Cloud Run only charges for actual memory used during execution
2. Container is built once, deployed once
3. GPU worker has same dependencies anyway

## Testing the Fix

After redeployment, verify imports work:

```bash
# SSH into GPU worker and test import chain
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='
python3 -c "
import sys
sys.path.insert(0, \"/home/codespace/fpa_web\")
from apps.scans.tasks import run_scan
print(\"✅ tasks.py imports successful\")
"'
```

## If Build Fails

Common reasons:
1. **torch download timeout** → Retry build, or use CPU-only: `torch-cpu>=2.0.0`
2. **Disk space** → Clean Docker: `docker system prune -a`
3. **Network issues** → Check internet connectivity

Fallback (use smaller torch):
```
torch-cpu>=2.0.0  # CPU-only, ~600MB instead of 2GB+
```

## Rollback Plan

If deployment breaks:
```bash
# Use previous image
gcloud run deploy fpa-web \
  --image gcr.io/ss-tool-498115/fpa-web:v1 \  # Previous working version
  ...
```

The old revisions are kept in Cloud Run.

## Deployment Status

| Stage | Status | ETA |
|-------|--------|-----|
| **Build Docker image** | ⏳ In Progress | ~10-15 min (installing torch) |
| **Push to GCR** | ⏹️ Not started | 1 min |
| **Redeploy Cloud Run** | ⏹️ Not started | 2 min |
| **Verify deployment** | ⏹️ Not started | 1 min |
| **Test with sample scan** | ⏹️ Not started | ~15-30 min (actual scan processing) |

**Total expected time:** ~30-50 minutes

## Monitoring Build Progress

```bash
# Check docker build status
docker images | grep fpa-web

# After push, check GCR
gcloud container images list --repository=gcr.io/ss-tool-498115 | grep fpa-web

# Monitor Cloud Run deployment
gcloud run services describe fpa-web --region=europe-west1
```

## Next Steps

1. ✅ Update requirements.txt (Done)
2. ⏳ Build Docker image (In progress, ~10-15 min)
3. 🔲 Push to GCR (1 min)
4. 🔲 Redeploy to Cloud Run (2 min)
5. 🔲 Create test scan (15-30 min processing)
6. 🔲 Monitor GPU worker logs
7. 🔲 Verify results in web UI
