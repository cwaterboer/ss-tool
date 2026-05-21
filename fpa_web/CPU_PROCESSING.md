# CPU Processing Guide

## Overview

The FPA web app is configured to use CPU as the fallback processing method for LingBot-Map 3D reconstruction. This allows full functionality in GPU-less environments like GitHub Codespaces development containers.

## CPU Inference Performance

### Inference Speed

| Device | Model | Frame Count | Estimated Time |
|--------|-------|-------------|-----------------|
| CPU (Intel/AMD)  | GCTStream (1.2B params) | 50 frames | 30-60 min |
| CPU (Intel/AMD)  | GCTStream (1.2B params) | 100 frames | 60-120 min |
| GPU (A100 40GB)  | GCTStream (1.2B params) | 50 frames | 1-2 min |
| GPU (H100 80GB)  | GCTStream (1.2B params) | 100 frames | 0.5-1 min |

**Note**: CPU times are approximate and vary based on:
- CPU core count and speed
- Available system memory
- Background processes
- Torch thread count configuration

### Memory Requirements

- **Per-frame memory**: ~80-150 MB for streaming inference
- **50-frame scan**: ~8-10 GB RAM
- **200+ frame scan**: ~16-24 GB RAM
- **Recommendation**: At least 16 GB available RAM for stable CPU inference

## Configuration

### Automatic Device Selection

The system automatically selects CPU when GPU is unavailable:

```python
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
```

### CPU-Specific Settings

When CPU is detected:

1. **Precision**: float32 (more stable than float16 on CPU)
2. **Autocast**: Disabled (no speed benefit on CPU with float32)
3. **AMP**: Not used on CPU
4. **Thread count**: Automatically detected from system
5. **Gradient checkpoint**: Enabled to save memory

### Environment Variables

```bash
# Override checkpoint path (default: /tmp/checkpoints/lingbot-map.pt)
export LINGBOT_CHECKPOINT_PATH=/path/to/checkpoint.pt

# Control torch thread count (default: auto-detected)
export OMP_NUM_THREADS=8
export OPENBLAS_NUM_THREADS=8
```

## Optimization Tips for CPU Processing

### 1. Reduce Frame Count for Testing
```python
# Use 20-30 frames for quick validation
scan.frame_count = 30
```

### 2. Increase System Memory
- Close other applications
- Increase available swap space
- Monitor memory usage during inference

### 3. Optimize Thread Count
```bash
# Check available cores
python -c "import os; print(os.cpu_count())"

# Set threads (typically num_cores - 2)
export OMP_NUM_THREADS=6
```

### 4. Use Streaming Mode (Default)
```python
# Inference mode in Scan model
mode = Scan.InferenceMode.DIRECT  # Streams frames through model
```

## Monitoring CPU Inference

### Watch System Resources
```bash
# In separate terminal
watch -n 1 'top -b -n 1 | head -20'
```

### Check Scan Status
```bash
cd fpa_web
python manage.py shell -c "from apps.scans.models import Scan; s = Scan.objects.get(name='loop-50-frames'); print(f'Status: {s.status}, Floor area: {s.floor_area_m2}')"
```

### View Inference Logs
```bash
# Scan task logs show device, dtype, duration
python manage.py shell -c "from apps.scans.models import Scan; import logging; logging.basicConfig(level=logging.INFO); s = Scan.objects.get(name='loop-50-frames')"
```

## Transitioning to GPU

When a GPU becomes available (e.g., AWS EC2 with NVIDIA instance):

### 1. No Code Changes Required
The system auto-detects GPU and switches automatically:
```python
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
```

### 2. Install CUDA Dependencies
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

### 3. Verify GPU Access
```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name())"
```

## CPU Processing Limitations

| Limitation | Impact | Mitigation |
|-----------|--------|-----------|
| Slow inference | 30-60s/frame | Use smaller frame sets for testing |
| High memory usage | May require 16-24GB RAM | Monitor memory, use swap |
| System load | CPU maxed during inference | Run during off-peak hours |
| Long wait times | Slow feedback during development | Test with 20-30 frames first |

## Performance Profiling

To profile CPU inference bottlenecks:

```python
import cProfile
import pstats
from apps.scans.tasks import run_scan

profiler = cProfile.Profile()
profiler.enable()

run_scan(scan_id)

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 slowest functions
```

## Troubleshooting

### Out of Memory (OOM)
```
RuntimeError: Unable to allocate ... on CPU
```
**Solutions**:
1. Reduce frame count: `scan.frame_count = 30`
2. Increase swap: `sudo fallocate -l 4G /swapfile`
3. Close background apps

### Slow Inference
- Check CPU usage: `top` or `htop`
- Verify thread count: `python -c "import torch; print(torch.get_num_threads())"`
- Ensure no other heavy processes running

### Inference Timeout
```
TimeoutError: Task exceeds time_limit=7200
```
**Default**: 2-hour timeout (7200 seconds)
- Sufficient for 200+ frames on modern CPU
- For larger scans, increase `time_limit` in tasks.py

## CPU Inference Best Practices

✅ **Do**:
- Use CPU for development and testing
- Reduce frame count for quick validation
- Monitor memory during long runs
- Keep background processes minimal

❌ **Don't**:
- Run production scans on CPU
- Expect real-time inference speed
- Ignore memory warnings
- Process 1000+ frame scans on CPU

## Next Steps: GPU Deployment

When ready for production:

1. **AWS EC2 GPU Instance**
   - p3.2xlarge (1x V100) - ~$3/hour
   - p4d.24xlarge (8x A100) - ~$33/hour

2. **Docker + NVIDIA Runtime**
   ```bash
   docker run --gpus all -it gpu_image
   ```

3. **Update inference settings** (automatic):
   - Precision switches to float16/bfloat16
   - AMP autocast enabled
   - Expected speedup: 30-100x

---

**Last Updated**: May 21, 2026  
**CPU Fallback Status**: ✅ Fully Configured
