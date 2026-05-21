# GitHub Push Strategy for Large Files

## Problem
Your `lingbot-map.pt` checkpoint is **4.6GB** and should NOT be in GitHub:
- GitHub free tier: 1GB file size limit
- Version control: Not designed for large binary files
- Repository bloat: Makes cloning slow for everyone

## Solution: Ignore Large Files, Download During Setup

---

## Step 1: Create .gitignore Entry

Check if `.gitignore` exists:
```bash
cat /workspaces/ss-tool/.gitignore
```

If not, create it:
```bash
cat > /workspaces/ss-tool/.gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Django
*.log
local_settings.py
db.sqlite3
/media/
/staticfiles/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Large model files (download during setup, don't commit)
*.pt
*.pth
*.bin
/tmp/checkpoints/
/opt/checkpoints/
checkpoints/

# Environment variables
.env
.env.local
.env.*.local

# Third-party model weights
lingbot-map.pt
models/checkpoints/

# GCP
key.json
EOF
```

---

## Step 2: Verify Large Files Aren't Already Tracked

```bash
cd /workspaces/ss-tool

# Check if lingbot-map.pt is in git history
git ls-files | grep -i "\.pt$"

# If it shows lingbot-map.pt, remove it from git history:
git rm --cached /tmp/checkpoints/lingbot-map.pt  # (or wherever it is)
git commit -m "Remove lingbot-map.pt from version control"
```

---

## Step 3: Create Model Download Script

**Create `fpa_web/scripts/download_checkpoint.py`:**
```python
#!/usr/bin/env python3
"""
Download LingBot-Map checkpoint from HuggingFace Hub.
This script is run during app initialization, not stored in git.
"""

import os
import sys
from pathlib import Path
from huggingface_hub import hf_hub_download

def download_checkpoint():
    """Download model checkpoint from HuggingFace."""
    
    # Determine checkpoint path
    checkpoint_dir = os.environ.get(
        'CHECKPOINT_ROOT',
        '/tmp/checkpoints'
    )
    checkpoint_path = os.environ.get(
        'LINGBOT_CHECKPOINT_PATH',
        os.path.join(checkpoint_dir, 'lingbot-map.pt')
    )
    
    # Create directory
    os.makedirs(checkpoint_dir, exist_ok=True)
    
    # Skip if already exists
    if os.path.exists(checkpoint_path):
        print(f"✓ Checkpoint already exists: {checkpoint_path}")
        return checkpoint_path
    
    print(f"Downloading LingBot-Map checkpoint...")
    print(f"This is a 4.6GB file, may take 10-30 minutes...")
    
    try:
        # Download from HuggingFace
        downloaded_path = hf_hub_download(
            repo_id="robbyant/lingbot-map",
            filename="lingbot-map.pt",
            cache_dir=checkpoint_dir
        )
        
        print(f"✓ Download complete!")
        print(f"Checkpoint saved to: {downloaded_path}")
        return downloaded_path
        
    except Exception as e:
        print(f"✗ Download failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    download_checkpoint()
```

**Create `fpa_web/scripts/__init__.py`:**
```python
# Placeholder
```

---

## Step 4: Update Docker Setup (for GCP deployment)

**Update `fpa_web/Dockerfile`:**
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

# Download checkpoint (this runs during build, not stored in image)
RUN python scripts/download_checkpoint.py

# Collect static files
RUN python manage.py collectstatic --noinput --settings=config.settings.gcp

# Run migrations and start server
CMD ["sh", "-c", "python manage.py migrate --settings=config.settings.gcp && gunicorn config.wsgi:application --bind 0.0.0.0:8080"]
```

---

## Step 5: Create Setup Script for Local Development

**Create `setup.sh`:**
```bash
#!/bin/bash
set -e

echo "🚀 Setting up FPA Scoping development environment..."

# Navigate to project root
cd "$(dirname "$0")"

# Create Python virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r fpa_web/requirements.txt

# Download checkpoint
echo "📥 Downloading LingBot-Map checkpoint (4.6GB)..."
echo "   This may take 10-30 minutes on first run..."
python fpa_web/scripts/download_checkpoint.py

# Setup database
echo "🗄️  Setting up database..."
cd fpa_web
python manage.py migrate
python manage.py createsuperuser --noinput || true

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the development server:"
echo "  cd fpa_web"
echo "  source ../venv/bin/activate"
echo "  python manage.py runserver"
echo ""
echo "Login with username: demo, password: demo"
```

**Make it executable:**
```bash
chmod +x setup.sh
```

---

## Step 6: Create Documentation File

**Create `SETUP_AND_DEPLOYMENT.md` in repo root:**
```markdown
# Setup and Deployment Guide

## Quick Start (Local Development)

### Option 1: Automated Setup
```bash
./setup.sh
```

### Option 2: Manual Setup
```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r fpa_web/requirements.txt

# 3. Download model checkpoint (4.6GB)
cd fpa_web
python scripts/download_checkpoint.py

# 4. Setup database
python manage.py migrate

# 5. Run server
python manage.py runserver
```

## Checkpoint Management

The **lingbot-map.pt** checkpoint (4.6GB) is NOT in version control.

**Automatic Download:**
- Development: `python fpa_web/scripts/download_checkpoint.py`
- Docker/Production: Automatically downloaded during Docker build
- HuggingFace: Downloaded from `robbyant/lingbot-map` repository

**Custom Checkpoint Location:**
```bash
export CHECKPOINT_ROOT=/path/to/checkpoints
export LINGBOT_CHECKPOINT_PATH=/path/to/lingbot-map.pt
python manage.py shell
```

## GCP Deployment

See [GCP_DEPLOYMENT_GUIDE.md](GCP_DEPLOYMENT_GUIDE.md) for full details.

Quick summary:
1. Create GCP project
2. Setup Cloud SQL, Cloud Storage, Redis
3. Build Docker image
4. Deploy to Cloud Run
5. Setup GPU worker on Compute Engine

```bash
gcloud run deploy fpa-web --image gcr.io/PROJECT_ID/fpa-web:latest
```

## FAQ

**Q: Why isn't the checkpoint in the repo?**  
A: It's 4.6GB, which exceeds GitHub's 1GB file size limit and bloats the repo.

**Q: How do I get the checkpoint?**  
A: Run `python scripts/download_checkpoint.py` - it's automatically downloaded from HuggingFace Hub.

**Q: Does the checkpoint download happen every time?**  
A: No, it caches locally. On first setup, it's a one-time 10-30 minute download.

**Q: Can I use a different checkpoint?**  
A: Yes, set `LINGBOT_CHECKPOINT_PATH` environment variable.

```

---

## Step 7: Push to GitHub

Now you can safely push to GitHub:

```bash
cd /workspaces/ss-tool

# Check what will be pushed (should NOT include *.pt files)
git status

# Add all files (except those in .gitignore)
git add .

# Commit
git commit -m "Add GCP deployment guide and checkpoint download script

- Add comprehensive GCP deployment guide (Option A)
- Add model checkpoint download script for HuggingFace
- Create .gitignore to exclude large model files
- Add setup.sh for automated local development setup
- Document checkpoint management strategy
- Exclude lingbot-map.pt from version control (4.6GB file)"

# Push to GitHub
git push origin main
```

---

## What Gets Pushed vs. What Doesn't

### ✅ Pushed to GitHub
```
fpa_web/
├── apps/
├── config/
├── templates/
├── scripts/download_checkpoint.py  ← NEW
├── Dockerfile  ← UPDATED
├── requirements.txt
└── manage.py

.gitignore  ← NEW
GCP_DEPLOYMENT_GUIDE.md  ← NEW
SETUP_AND_DEPLOYMENT.md  ← NEW
setup.sh  ← NEW
README.md
LICENSE.txt
pyproject.toml
```

### ❌ NOT Pushed (in .gitignore)
```
lingbot-map.pt  (4.6GB - downloaded on demand)
__pycache__/
*.log
db.sqlite3
/media/
/staticfiles/
.vscode/
.env
key.json
venv/
/tmp/checkpoints/
```

---

## Verification

After pushing, verify from a fresh clone:

```bash
# Clone the repo (should be ~50MB, not 4.6GB)
git clone https://github.com/YOUR_GITHUB/ss-tool.git
cd ss-tool

# Run setup (automatically downloads checkpoint)
./setup.sh

# Should now work normally
cd fpa_web
python manage.py runserver
```

---

## Size Comparison

**Before (with checkpoint):**
- Repository size: ~4.7GB
- Clone time: 30-60 minutes
- Bandwidth: Excessive

**After (with setup script):**
- Repository size: ~50MB
- Clone time: 10-30 seconds
- First setup: ~15 minutes (checkpoint download only)

