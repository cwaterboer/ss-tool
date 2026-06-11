# SSH Access to GPU Worker - Quick Guide

## 🔧 Setup Complete ✅

SSH access to the GPU worker (`fpa-gpu-worker`) is now configured and tested.

## Quick SSH Commands

### Interactive SSH Session
```bash
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c
```

### Run Commands Directly
```bash
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='<command>'
```

### Create Convenient Alias (Optional)
Add to your `~/.bashrc` or `~/.zshrc`:
```bash
alias gpu-ssh='gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c'
alias gpu-cmd='gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command'
```

Then use:
```bash
gpu-ssh                              # Interactive session
gpu-cmd 'systemctl status fpa-gpu-worker'  # Run command
```

## Instance Details
- **Instance Name:** fpa-gpu-worker
- **Zone:** europe-west1-c
- **External IP:** 34.53.182.156
- **Internal IP:** 10.132.0.2
- **OS:** Ubuntu 20.04
- **User:** ubuntu (via gcloud SSH)

## Common Commands for Monitoring

### 1. Check Celery Worker Status
```bash
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='sudo systemctl status fpa-gpu-worker'
```

### 2. Watch Live Celery Logs
```bash
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='sudo journalctl -u fpa-gpu-worker -f'
```

### 3. Check GPU Status
```bash
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='nvidia-smi'
```

### 4. Monitor Task Queue
```bash
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='redis-cli -h 10.112.227.243 -p 6379 LLEN celery'
```

### 5. Check Redis Connection
```bash
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='redis-cli -h 10.112.227.243 -p 6379 PING'
```

### 6. Restart Celery Worker
```bash
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='sudo systemctl restart fpa-gpu-worker'
```

### 7. View Checkpoint File
```bash
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='ls -lh /home/codespace/checkpoints/lingbot-map.pt'
```

## Current System Status ✅

| Component | Status | Details |
|-----------|--------|---------|
| Celery Worker | ✅ ACTIVE | Running via systemd |
| Redis Connection | ✅ CONNECTED | redis://10.112.227.243:6379/0 |
| GPU (NVIDIA L4) | ✅ READY | 23GB VRAM, 0% utilization, 32°C |
| Task Registration | ✅ REGISTERED | apps.scans.tasks.run_scan |
| Checkpoint File | ✅ EXISTS | 4.4GB lingbot-map.pt |
| Task Queue | ✅ IDLE | 0 tasks pending |

## Authentication

SSH authentication is handled automatically via `gcloud` using your GCP credentials. No separate SSH key configuration needed—just run the gcloud commands above.

## Troubleshooting

### Permission Denied
If you get "Permission denied", ensure you're logged in to gcloud:
```bash
gcloud auth login
gcloud config set project ss-tool-498115
```

### Connection Timeout
If SSH times out, check your firewall rules:
```bash
gcloud compute firewall-rules list --filter="direction:INGRESS" --format="table(name,direction,sourceRanges,allowed[].map().firewall_rule())"
```

### Can't Connect to Redis
Verify from the worker:
```bash
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='nc -zv 10.112.227.243 6379'
```

## Live Testing - Create a Scan

1. Login to web app: https://fpa-web-369870387328.europe-west1.run.app/accounts/login/
   - Username: `admin`
   - Password: `admin`

2. Create a site and upload a scan video

3. In your local terminal, monitor the GPU worker:
   ```bash
   gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='sudo journalctl -u fpa-gpu-worker -f --lines=50'
   ```

4. Watch for logs like:
   ```
   Received task: apps.scans.tasks.run_scan[task-id]
   [scan:xxx] started
   [scan:xxx] 150 frames
   [scan:xxx] inference done in 45.2s
   [scan:xxx] ✓ DONE
   ```

## For Quick Diagnostics

Create a script file `run_diagnostics.sh` in your local workspace:
```bash
#!/bin/bash
echo "GPU Worker Diagnostics"
gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='
echo "Celery Status:"; sudo systemctl is-active fpa-gpu-worker
echo "GPU Status:"; nvidia-smi -q -d utilization
echo "Queue Depth:"; redis-cli -h 10.112.227.243 -p 6379 LLEN celery
echo "Recent Logs:"; sudo journalctl -u fpa-gpu-worker -n 5 --no-pager
'
```

Then run:
```bash
bash run_diagnostics.sh
```
