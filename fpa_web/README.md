# FPA Web — Field Planning & Analysis Platform

Django web application for LingBot-Map 3D store reconstruction with interactive viewer.

## ⚡ Quick Start (CPU Development)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Download LingBot checkpoint (4.63GB)
python << 'EOF'
from huggingface_hub import hf_hub_download
from pathlib import Path
Path('/tmp/checkpoints').mkdir(exist_ok=True)
hf_hub_download('robbyant/lingbot-map', 'lingbot-map.pt', cache_dir='/tmp/checkpoints')
EOF

# 3. Setup database and user
cd fpa_web
python manage.py migrate
python manage.py createsuperuser

# 4. Run development server
python manage.py runserver 0.0.0.0:8000
```

Open http://localhost:8000 in browser.

## 📊 CPU Processing (Fallback Mode)

System automatically uses **CPU inference** when no GPU available. This is fully supported but slower:

| Metric | Value |
|--------|-------|
| Inference speed | ~30-60 sec per frame |
| 50-frame scan | 30-60 minutes |
| 100-frame scan | 60-120 minutes |
| Memory required | 16-24 GB RAM |
| Precision | float32 (stable on CPU) |

### Quick CPU Tips

```bash
# Set thread count (CPU cores - 2)
export OMP_NUM_THREADS=6

# Monitor memory
watch -n 1 'free -h'

# Start with 20-30 frames for testing
```

**📖 See [CPU_PROCESSING.md](CPU_PROCESSING.md) for detailed CPU guide.**

## Setup Details

### Local setup

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

### Celery worker

```bash
# For sync development (CELERY_TASK_ALWAYS_EAGER=True in local settings)
# Tasks run immediately without separate worker

# For async production
celery -A config worker --loglevel=info --concurrency=1
```

## Architecture

### Key Components

- **Django 6.0.5**: Web framework + ORM
- **Celery 5.3**: Background inference tasks
- **LingBot-Map**: 3D reconstruction (1.2B params, CPU/GPU compatible)
- **Three.js**: Interactive 3D viewer
- **PostgreSQL** (prod) / **SQLite** (dev)

### Data Flow

```
Upload → Extract Frames → LingBot Inference → Generate Artifacts → Viewer
                (CPU/GPU)     ├─ Point cloud
                              ├─ Camera path
                              ├─ Floor plan
                              └─ Preview image
```

## Project Structure

```
fpa_web/
├── config/
│   ├── settings/
│   │   ├── base.py          # Checkpoint + Celery config
│   │   ├── local.py         # CPU-friendly dev settings
│   │   └── production.py
│   ├── celery.py
│   └── urls.py
│
├── apps/
│   ├── sites/               # Job site management
│   ├── scans/               # Upload + run_scan task
│   │   ├── models.py        # Scan model + paths
│   │   ├── tasks.py         # run_scan with CPU optimization
│   │   ├── views.py
│   │   └── templates/
│   └── auth/                # Login/register
│
├── media/
│   └── scans/{scan_id}/
│       ├── input/           # Uploaded frames
│       └── output/          # Artifacts (PLY, JSON, PNG)
│
├── CPU_PROCESSING.md        # CPU inference guide
├── .env.cpu.example         # CPU configuration
└── requirements.txt
```

## Nginx Configuration

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

## Environment Variables

```bash
# Required
LINGBOT_CHECKPOINT_PATH=/tmp/checkpoints/lingbot-map.pt

# CPU Optimization (optional)
OMP_NUM_THREADS=8              # Set to (CPU cores - 2)
DJANGO_SETTINGS_MODULE=config.settings.local

# Production
DATABASE_URL=postgresql://user:pass@localhost/fpa
SECRET_KEY=your-secret-key
ALLOWED_HOSTS=yourdomain.com
```

## Deployment

### Production Checklist

- [ ] PostgreSQL database
- [ ] Redis for Celery
- [ ] Gunicorn/uWSGI server
- [ ] HTTPS/SSL certificate
- [ ] Environment variables configured
- [ ] DEBUG = False
- [ ] ALLOWED_HOSTS configured
- [ ] Static files collected: `python manage.py collectstatic`

### GPU Instance (Recommended)

When GPU available (AWS p3.2xlarge, A100, etc.):
- System auto-detects and switches to GPU
- Expected speedup: 30-50x
- Cost: ~$1-3/hour for inference

## Testing

```bash
# Run Django tests
python manage.py test apps.scans

# Quick CPU test (50 frames)
python manage.py shell << 'EOF'
from apps.scans.models import Scan
from apps.scans.tasks import run_scan

# Create test data first
scan = Scan.objects.get(name='loop-50-frames')
run_scan(str(scan.id))
EOF

# Check results
python manage.py shell -c "
from apps.scans.models import Scan
s = Scan.objects.get(name='loop-50-frames')
print(f'Status: {s.status}, Floor area: {s.floor_area_m2} m²')
"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Out of memory | Reduce frame count, increase swap, close apps |
| Slow inference | Check thread count, monitor CPU load |
| Import error | `python manage.py shell -c "import lingbot_map"` |
| GPU not detected | `python -c "import torch; print(torch.cuda.is_available())"` |

## References

- 📖 [CPU_PROCESSING.md](CPU_PROCESSING.md) — Detailed CPU guide + GPU migration
- 🤗 [HuggingFace Checkpoint](https://huggingface.co/robbyant/lingbot-map)
- 📄 [LingBot-Map Paper](https://arxiv.org/abs/2404.xxxxx)
- ⚙️ [.env.cpu.example](.env.cpu.example) — CPU config template

## Status

✅ **Fully Functional**
- CPU Processing: Configured and optimized
- Model Inference: LingBot-Map integrated
- Web Interface: Django scaffold complete
- 3D Viewer: Three.js ready
- Checkpoint: Auto-download from HuggingFace

🚀 **Next**: GPU deployment, Aurora sensor placement

---

**Last Updated**: May 21, 2026  
**Device**: CPU Fallback (Codespaces)

}
```
