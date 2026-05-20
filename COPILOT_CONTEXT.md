# COPILOT CONTEXT — FPA Scoping Web App
# Read this ENTIRE file before writing any code.
# This is the source of truth for all architectural and implementation decisions.
# Keep this file open in a tab for the entire session.
# Last updated: grounded against the LingBot-Map paper (arXiv:submit/7483828, April 2026)

---

## What we are building

A Django web application used internally by RetailNext FPA (Field Planning & Analysis) teams.
Onsite technicians capture a video walkthrough of a retail store. That video is uploaded to this
app, which runs it through a 3D reconstruction model (LingBot-Map) as an async background job.
The reconstruction output generates a top-down floor plan of the store with accurate obstacle
positions and per-cell ceiling height data. An FPA analyst then opens the planner UI for that
scan, places Aurora bifocal sensors on the floor plan, and sees real-time FOV coverage polygons
and blindspot highlighting.

This milestone covers: job sites, scans, upload, job status, the reconstructed floor plan as a
top-down image, and an interactive 3D point cloud viewer in the browser with RGB colour.
Camera placement logic (Aurora FOV, coverage polygons, blindspot) is the next milestone.

---

## Repo structure we are adding to

The lingbot-map package is already installed as a local editable package:
    pip install -e .

The package name is `lingbot_map`. It provides:
    from lingbot_map.models.gct_stream import GCTStream          # Direct mode
    from lingbot_map.models.gct_stream_window import GCTStream   # VO mode
    from lingbot_map.utils.load_fn import load_and_preprocess_images
    from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri
    from lingbot_map.utils.geometry import closed_form_inverse_se3_general

Do NOT modify anything inside the lingbot_map/ directory.
All new Django code lives in a new top-level directory: fpa_web/

---

## LingBot-Map — Architecture grounded in the paper

### What it does

LingBot-Map is a feed-forward 3D foundation model for streaming scene reconstruction.
Given a continuous frame sequence it outputs per-frame:
  - Camera pose (camera-to-world extrinsic 3×4, intrinsic 3×3)
  - Per-pixel depth map with uncertainty
  - Dense 3D world-space point cloud with per-point confidence AND per-pixel RGB colour

It runs at ~20 FPS (with FlashInfer on GPU) or ~10.5 FPS (PyTorch baseline on GPU)
at 518×378 resolution, stable over sequences exceeding 10,000 frames.

### Architecture: Geometric Context Attention (GCA)

The transformer uses three complementary attention contexts, each solving a distinct problem:

  ANCHOR CONTEXT  (first n frames, default n=3 from paper Fig. 3)
    The first n frames are processed with full mutual attention and a learnable anchor token.
    They fix the coordinate system and absolute scale for the entire sequence.
    All subsequent frames attend to these anchor frames as fixed references.
    CRITICAL: The model normalises ground-truth depth/translation relative to anchor scale
    s = mean(||x||) for x in the anchor point cloud. This is why the world coordinates
    are in an arbitrary scale — they are relative to the anchor frame geometry.
    Do not assume world units are metres without a scale calibration step.

  LOCAL POSE-REFERENCE WINDOW  (sliding window of k recent frames)
    Retains full image tokens (M≈500 tokens per frame) for the k most recent frames.
    Provides dense local geometry cues for accurate frame-to-frame registration.
    DEFAULT k=64 per Section 4.4 of the paper ("Default Inference Configuration").
    WE PREVIOUSLY HAD k=16 — THIS WAS WRONG. Correct value is k=64.
    Training randomly sampled k from 16 to 64, so k=64 is the upper bound used at inference.
    On CPU without FlashInfer, k=64 is slower but geometrically more accurate than k=16.

  TRAJECTORY MEMORY  (compact 6-token summary per evicted frame)
    For frames outside the anchor set and sliding window, the model evicts the M image tokens
    but retains 6 compact context tokens (camera + anchor + register tokens) per frame.
    These carry temporal ordering via Video RoPE positional encoding.
    This is why the model does not drift: it has a lightweight record of every past frame.
    kv_cache_scale_frames in the constructor controls how many scale frames are permanently
    retained. Default 8. Do not reduce below 4.

### Complexity (from paper Section 3.2)

  Causal attention:  T*(M+6) tokens — grows linearly, unusable for long sequences
  GCA:               (n+k)*M + 6T tokens — only 6 tokens per evicted frame
  At T=10,000, k=64, M=500: GCA retains ~70,000 tokens vs causal's ~5,000,000
  Per-frame growth reduced by ~80× compared to causal attention.

### Two inference modes — paper Section 4.4

  DIRECT OUTPUT MODE  (paper name — maps to gct_stream.GCTStream)
    Default mode. Processes frames causally with full three-level GCA context.
    No state reset. Each frame outputs absolute camera pose + depth.
    Stable up to ~3,000 frames (10× the 320-frame training maximum).
    For retail store walkthroughs (typically 300-600 frames at 10 FPS) always use this.
    Beyond ~3,000 frames, accuracy degrades gradually.

  VO MODE  (paper name — maps to gct_stream_window.GCTStream)
    For sequences far exceeding ~3,000 frames (e.g. warehouse, multi-floor building).
    Partitions sequence into overlapping local windows. State resets between windows.
    Fuses windows via Sim(3) alignment (scale + rotation + translation).
    Introduces additional alignment drift at each window boundary.
    Use only when Direct mode's effective range is exceeded.

### Paper's default inference configuration (Section 4.4)

  Mode:              Direct Output
  Window size k:     64  (NOT 16 — update all constructor calls)
  Keyframe interval: m=1 (every frame retained in KV cache)
  Resolution:        518×378
  Precision:         bfloat16 on Ampere+ GPUs, float16 otherwise
  FlashInfer:        Required for ~20 FPS. Without it: ~10.5 FPS on GPU, ~3 FPS on CPU.
                     The warning "flashinfer not available" in your test output is expected
                     on CPU — geometry is still correct, just slower.

### Output tensors — corrected understanding

  predictions['world_points']        (B, T, 3, H, W)
    3D XYZ coordinates in world space. Axis convention: Y=up, X=right, Z=forward.
    Scale is relative to anchor frames — NOT necessarily in metres.
    To get approximate metres: divide by scale factor s (mean ||x|| of anchor point cloud).
    This is the primary input to _extract_floor_artifacts().

  predictions['world_points_conf']   (B, T, H, W)
    Confidence per point, range ~0–5+. Default threshold 1.5 is reasonable.
    Lower to 0.5–1.0 if getting floor_area_m2=0 (too few points passing threshold).

  predictions['depth']               (B, T, 1, H, W)
    Per-pixel depth from camera in world-scale units (same scale as world_points).

  predictions['pose_enc']            raw pose encoding
    Decoded by pose_encoding_to_extri_intri() → extrinsic (T,3,4) + intrinsic (T,3,3).

### CRITICAL: Camera-to-world convention

  From paper Section 3.3:
  "Unlike VGGT, we supervise the network using camera-to-world transformations
  rather than world-to-camera ones."

  This means the model ALREADY outputs camera-to-world (c2w) extrinsics.
  The extrinsic inversion step using closed_form_inverse_se3_general() that was in the
  original spec was based on incorrect assumptions inherited from VGGT.

  CHECK YOUR CHECKPOINT: if pose_encoding_to_extri_intri() returns c2w matrices
  (translation column points in the direction the camera is facing in world space),
  DO NOT invert. If it returns w2c matrices, inversion is needed.

  Diagnostic: after decoding, extrinsic[0] should be approximately identity (the first
  anchor frame defines the world origin). If it is far from identity, you have w2c and
  need to invert.

### CRITICAL: RGB colour in point cloud

  The model outputs world_points in (B, T, 3, H, W) — 3D positions per pixel.
  Each pixel in the input image maps 1:1 to a point in world_points.
  The INPUT IMAGES are loaded as (B, T, 3, H, W) tensors and are available.

  To get a coloured point cloud:
    - Flatten world_points to (N, 3)
    - Flatten the input image tensor to (N, 3) RGB values
    - Filter both by world_points_conf > threshold
    - Export PLY with both XYZ and RGB columns

  The shell reconstruction in Three.js is caused by the PLY having NO colour.
  trimesh.PointCloud(pts) exports XYZ only. You must pass colours explicitly:
    trimesh.PointCloud(vertices=pts, colors=rgb_uint8)

  The paper's Figure S3 shows exactly this — top-down point clouds coloured with
  per-pixel RGB from the rendered frames. This is what the viewer should look like.

### Why floor_area_m2 = 0.0 with 45 frames

  45 frames = 4.5 seconds at 10 FPS = camera covered maybe 20-30% of the store perimeter.
  binary_fill_holes() requires a CLOSED perimeter to fill the interior.
  With partial coverage the perimeter is open, nothing gets filled, floor_mask is empty.

  Solution 1 (immediate): Capture longer video — minimum 2-3 minutes for a retail store,
  targeting 150-300 frames at 10 FPS. Walk the FULL perimeter first, then aisles.

  Solution 2 (robustness): In _extract_floor_artifacts(), add a convex hull fallback:
  if floor_mask.sum() == 0 after binary_fill_holes, compute the convex hull of all
  projected floor-level points as the floor boundary. Less accurate but never returns 0.

  Solution 3 (conf_threshold): The test used conf_threshold=0.1 and still got 0.0.
  This confirms the issue is coverage (open perimeter), not confidence filtering.

---

## Directory layout to scaffold

```
fpa_web/
├── manage.py
├── .env
├── requirements.txt
├── config/
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── local.py
│   │   └── production.py
│   ├── urls.py
│   └── celery.py
├── apps/
│   ├── __init__.py
│   ├── sites/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── forms.py
│   │   └── templates/sites/
│   │       ├── list.html
│   │       ├── detail.html
│   │       └── create.html
│   └── scans/
│       ├── __init__.py
│       ├── models.py
│       ├── views.py
│       ├── urls.py
│       ├── forms.py
│       ├── tasks.py
│       └── templates/scans/
│           ├── create.html
│           ├── detail.html
│           └── _status_badge.html
├── templates/
│   └── base.html
└── media/
    └── scans/<uuid>/
        ├── input/
        └── output/
            ├── floor_mask.png
            ├── obstacle_grid.png
            ├── height_map.png
            ├── point_cloud.ply        # full res, XYZ+RGB
            ├── point_cloud_web.ply    # decimated, XYZ+RGB, for browser
            └── preview.jpg
```

---

## Environment variables (.env)

```
DJANGO_SETTINGS_MODULE=config.settings.local
SECRET_KEY=change-me-in-production
DATABASE_URL=sqlite:///db.sqlite3
REDIS_URL=redis://localhost:6379/0
MEDIA_ROOT=/absolute/path/to/fpa_web/media
CHECKPOINT_ROOT=/absolute/path/to/checkpoints
LINGBOT_CHECKPOINT_PATH=/absolute/path/to/checkpoints/lingbot-map.pt
GOOGLE_MAPS_API_KEY=your-key-here
```

---

## Data models

### apps/sites/models.py

```python
import uuid
from django.db import models
from django.contrib.auth.models import User


class JobSite(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sites')
    name       = models.CharField(max_length=255)
    address    = models.CharField(max_length=512)
    place_id   = models.CharField(max_length=255, blank=True)
    latitude   = models.FloatField(null=True, blank=True)
    longitude  = models.FloatField(null=True, blank=True)
    store_type = models.CharField(max_length=100, blank=True)
    notes      = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} — {self.address}"

    @property
    def scan_count(self):
        return self.scans.count()

    @property
    def latest_scan(self):
        return self.scans.order_by('-created_at').first()
```

### apps/scans/models.py

```python
import os
import uuid
from django.db import models
from django.conf import settings
from apps.sites.models import JobSite


class Scan(models.Model):

    class Status(models.TextChoices):
        PENDING    = 'pending',    'Pending'
        PROCESSING = 'processing', 'Processing'
        DONE       = 'done',       'Done'
        FAILED     = 'failed',     'Failed'

    class InputType(models.TextChoices):
        VIDEO  = 'video',  'Video walkthrough'
        IMAGES = 'images', 'Image folder (zip)'

    class InferenceMode(models.TextChoices):
        DIRECT = 'direct', 'Direct Output (up to ~3000 frames, retail stores)'
        VO     = 'vo',     'VO Mode (very long sequences >3000 frames)'

    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site              = models.ForeignKey(JobSite, on_delete=models.CASCADE, related_name='scans')
    name              = models.CharField(max_length=255)
    notes             = models.TextField(blank=True)
    status            = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    input_type        = models.CharField(max_length=10, choices=InputType.choices, default=InputType.VIDEO)
    celery_task_id    = models.CharField(max_length=128, blank=True)
    error_message     = models.TextField(blank=True)

    # Inference config — see paper Section 4.4 for defaults
    fps               = models.IntegerField(default=10)
    mode              = models.CharField(
                            max_length=10,
                            choices=InferenceMode.choices,
                            default=InferenceMode.DIRECT,
                        )
    kv_window_size    = models.IntegerField(default=64)   # k in paper, default 64 NOT 16
    keyframe_interval = models.IntegerField(default=1)    # m in paper, default 1
    conf_threshold    = models.FloatField(default=1.5)    # filter on world_points_conf

    # Output paths — all absolute, populated after job completes
    input_dir         = models.CharField(max_length=512, blank=True)
    floor_mask_path   = models.CharField(max_length=512, blank=True)
    obstacle_path     = models.CharField(max_length=512, blank=True)
    height_map_path   = models.CharField(max_length=512, blank=True)
    point_cloud_path  = models.CharField(max_length=512, blank=True)   # full res XYZ+RGB
    web_ply_path      = models.CharField(max_length=512, blank=True)   # decimated XYZ+RGB
    preview_path      = models.CharField(max_length=512, blank=True)

    # Derived metadata
    floor_area_m2     = models.FloatField(null=True, blank=True)
    grid_resolution   = models.FloatField(default=0.05)  # metres per pixel (approximate)
    origin_x          = models.FloatField(null=True, blank=True)
    origin_z          = models.FloatField(null=True, blank=True)
    anchor_scale      = models.FloatField(null=True, blank=True)  # world units → approx metres
    frame_count       = models.IntegerField(null=True, blank=True)

    created_at        = models.DateTimeField(auto_now_add=True)
    started_at        = models.DateTimeField(null=True, blank=True)
    completed_at      = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.site.name})"

    @property
    def output_dir(self):
        return os.path.join(settings.MEDIA_ROOT, 'scans', str(self.id), 'output')

    @property
    def input_path(self):
        return os.path.join(settings.MEDIA_ROOT, 'scans', str(self.id), 'input')

    def _media_url(self, abs_path):
        if not abs_path:
            return None
        rel = os.path.relpath(abs_path, settings.MEDIA_ROOT)
        return settings.MEDIA_URL + rel

    @property
    def preview_url(self):
        return self._media_url(self.preview_path)

    @property
    def web_ply_url(self):
        return self._media_url(self.web_ply_path)

    @property
    def point_cloud_url(self):
        return self._media_url(self.point_cloud_path)

    @property
    def duration_seconds(self):
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
```

---

## The Celery task — apps/scans/tasks.py

Write this exactly. Every comment explains a decision grounded in the paper.

```python
import os
import time
import logging
import numpy as np
import torch
from celery import shared_task
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, time_limit=7200)
def run_scan(self, scan_id: str):
    from apps.scans.models import Scan
    scan = Scan.objects.get(id=scan_id)

    scan.status         = Scan.Status.PROCESSING
    scan.started_at     = timezone.now()
    scan.celery_task_id = self.request.id
    scan.save(update_fields=['status', 'started_at', 'celery_task_id'])
    logger.info(f"[scan:{scan_id}] started")

    try:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f"[scan:{scan_id}] device={device}")

        # ── 1. Load and preprocess images ────────────────────────────────────
        # load_and_preprocess_images returns a tensor we also need for RGB colour.
        # We keep the raw PIL images separately to extract RGB values for the PLY.
        from lingbot_map.utils.load_fn import load_and_preprocess_images

        paths = _collect_image_paths(scan.input_path)
        if not paths:
            raise ValueError(f"No images found in {scan.input_path}")
        if len(paths) < 20:
            raise ValueError(
                f"Only {len(paths)} frames found. LingBot-Map needs at least ~100 frames "
                f"(~60 seconds at 10 FPS) for a retail store reconstruction. "
                f"Re-capture with a longer walkthrough covering the full perimeter."
            )

        logger.info(f"[scan:{scan_id}] {len(paths)} frames")
        scan.frame_count = len(paths)
        scan.save(update_fields=['frame_count'])

        images = load_and_preprocess_images(
            paths, mode='crop', image_size=518, patch_size=14,
        ).to(device)
        # images shape: (1, T, 3, H, W) — values normalised, not raw RGB

        # Extract raw RGB for point cloud colouring (0-255 uint8)
        # We reload at the same crop/resize as the model for pixel alignment
        rgb_for_colour = _load_rgb_for_colour(paths, target_h=378, target_w=518)
        # rgb_for_colour shape: (T, H, W, 3) uint8

        # ── 2. Load model ─────────────────────────────────────────────────────
        # Paper Section 4.4: default k=64 (kv_cache_sliding_window)
        # scan.mode: 'direct' → gct_stream, 'vo' → gct_stream_window
        if scan.mode == 'vo':
            from lingbot_map.models.gct_stream_window import GCTStream
        else:
            from lingbot_map.models.gct_stream import GCTStream

        model = GCTStream(
            img_size=518,
            patch_size=14,
            enable_3d_rope=True,
            max_frame_num=1024,
            kv_cache_sliding_window=scan.kv_window_size,   # default 64, paper Section 4.4
            kv_cache_scale_frames=8,                        # trajectory memory, min 4
            kv_cache_cross_frame_special=True,
            kv_cache_include_scale_frames=True,
            use_sdpa=not torch.cuda.is_available(),         # FlashInfer fallback
        )

        ckpt_path = settings.LINGBOT_CHECKPOINT_PATH
        logger.info(f"[scan:{scan_id}] loading checkpoint: {ckpt_path}")
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=True)
        model.load_state_dict(ckpt.get('model', ckpt), strict=False)
        model = model.to(device).eval()

        # ── 3. Inference ──────────────────────────────────────────────────────
        # Paper Section 4.1: bfloat16 on Ampere+ (compute capability >= 8.0), float16 otherwise
        # torch.amp.autocast is the non-deprecated form (vs torch.cuda.amp.autocast)
        use_bf16 = torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 8
        dtype    = torch.bfloat16 if use_bf16 else torch.float16
        amp_ctx  = torch.amp.autocast('cuda', dtype=dtype) if torch.cuda.is_available() \
                   else torch.no_grad()

        logger.info(f"[scan:{scan_id}] inference mode={scan.mode} k={scan.kv_window_size} dtype={dtype}")
        t0 = time.time()

        with torch.no_grad(), amp_ctx:
            if scan.mode == 'direct':
                predictions = model.inference_streaming(
                    images,
                    num_scale_frames=8,
                    keyframe_interval=scan.keyframe_interval,  # default 1
                )
            else:
                # VO mode: window_size should be >= kv_window_size
                predictions = model.inference_windowed(
                    images,
                    window_size=max(scan.kv_window_size, 64),
                    overlap_size=16,
                    num_scale_frames=8,
                )

        logger.info(f"[scan:{scan_id}] inference done in {time.time()-t0:.1f}s")

        # ── 4. Decode poses ───────────────────────────────────────────────────
        # Paper Section 3.3: model outputs camera-to-world (c2w), NOT world-to-camera.
        # "Unlike VGGT, we supervise the network using camera-to-world transformations."
        # pose_encoding_to_extri_intri may return c2w directly — check by verifying
        # that extrinsic[0] is close to identity (first anchor frame = world origin).
        from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri

        extrinsic, intrinsic = pose_encoding_to_extri_intri(
            predictions['pose_enc'], images.shape[-2:]
        )
        # extrinsic: (T, 3, 4), intrinsic: (T, 3, 3)

        # Diagnostic: log first frame extrinsic to confirm c2w convention
        ext0 = extrinsic[0].cpu().float().numpy()
        logger.info(f"[scan:{scan_id}] extrinsic[0] translation: {ext0[:, 3]}")
        # If translation is near [0,0,0] → c2w confirmed, no inversion needed.
        # If translation is large/unexpected → inversion may be needed; log a warning.
        if np.linalg.norm(ext0[:, 3]) > 5.0:
            logger.warning(
                f"[scan:{scan_id}] extrinsic[0] translation norm={np.linalg.norm(ext0[:,3]):.2f} "
                f"— may need w2c→c2w inversion. Check checkpoint convention."
            )

        extrinsic = extrinsic.cpu().float().numpy()
        intrinsic = intrinsic.cpu().float().numpy()

        # ── 5. Extract world points and compute anchor scale ──────────────────
        world_points = predictions['world_points'].squeeze(0).cpu().float().numpy()
        world_conf   = predictions['world_points_conf'].squeeze(0).cpu().float().numpy()

        # Paper Section 3.2, Anchor Context: coordinates are normalised by
        # s = mean(||x||) for x in anchor point cloud.
        # Estimate anchor scale from the first few frames' confident points.
        anchor_pts   = world_points[:3].reshape(-1, 3)   # first 3 frames
        anchor_conf  = world_conf[:3].reshape(-1)
        anchor_pts_f = anchor_pts[anchor_conf > scan.conf_threshold]
        anchor_scale = float(np.mean(np.linalg.norm(anchor_pts_f, axis=1))) if len(anchor_pts_f) > 10 else 1.0
        logger.info(f"[scan:{scan_id}] anchor_scale={anchor_scale:.4f}")

        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # ── 6. Extract floor plan artifacts ───────────────────────────────────
        os.makedirs(scan.output_dir, exist_ok=True)
        artifacts = _extract_floor_artifacts(
            world_points=world_points,
            world_conf=world_conf,
            conf_threshold=scan.conf_threshold,
            grid_resolution=scan.grid_resolution,
            output_dir=scan.output_dir,
        )

        # ── 7. Save coloured point clouds ─────────────────────────────────────
        ply_path, web_ply_path = _save_point_cloud(
            world_points=world_points,
            world_conf=world_conf,
            rgb_colours=rgb_for_colour,
            conf_threshold=scan.conf_threshold,
            output_dir=scan.output_dir,
        )

        # ── 8. Persist results ────────────────────────────────────────────────
        scan.status           = Scan.Status.DONE
        scan.completed_at     = timezone.now()
        scan.floor_mask_path  = artifacts['floor_mask_path']
        scan.obstacle_path    = artifacts['obstacle_path']
        scan.height_map_path  = artifacts['height_map_path']
        scan.preview_path     = artifacts['preview_path']
        scan.point_cloud_path = ply_path
        scan.web_ply_path     = web_ply_path
        scan.floor_area_m2    = artifacts['floor_area_m2']
        scan.origin_x         = artifacts['origin_x']
        scan.origin_z         = artifacts['origin_z']
        scan.anchor_scale     = anchor_scale
        scan.save(update_fields=[
            'status', 'completed_at',
            'floor_mask_path', 'obstacle_path', 'height_map_path',
            'preview_path', 'point_cloud_path', 'web_ply_path',
            'floor_area_m2', 'origin_x', 'origin_z', 'anchor_scale',
        ])
        logger.info(
            f"[scan:{scan_id}] done — floor_area={artifacts['floor_area_m2']:.1f} "
            f"anchor_scale={anchor_scale:.4f} frames={scan.frame_count}"
        )

    except Exception as exc:
        logger.exception(f"[scan:{scan_id}] FAILED: {exc}")
        scan.status        = Scan.Status.FAILED
        scan.error_message = str(exc)
        scan.completed_at  = timezone.now()
        scan.save(update_fields=['status', 'error_message', 'completed_at'])
        raise


# ── Helpers ────────────────────────────────────────────────────────────────────

def _collect_image_paths(folder: str) -> list:
    import glob
    paths = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.PNG']:
        paths.extend(glob.glob(os.path.join(folder, ext)))
    return sorted(set(paths))


def _load_rgb_for_colour(paths: list, target_h: int = 378, target_w: int = 518) -> np.ndarray:
    """
    Load images resized to (target_h, target_w) as uint8 RGB arrays.
    Returns (T, H, W, 3) uint8 array aligned pixel-for-pixel with world_points.
    """
    from PIL import Image as PILImage
    frames = []
    for p in paths:
        img = PILImage.open(p).convert('RGB')
        # Centre crop to match load_and_preprocess_images(mode='crop')
        w, h = img.size
        scale = max(target_w / w, target_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), PILImage.BILINEAR)
        left = (new_w - target_w) // 2
        top  = (new_h - target_h) // 2
        img  = img.crop((left, top, left + target_w, top + target_h))
        frames.append(np.array(img, dtype=np.uint8))
    return np.stack(frames, axis=0)  # (T, H, W, 3)


def _extract_floor_artifacts(world_points, world_conf,
                               conf_threshold, grid_resolution, output_dir):
    """
    Derives floor_mask, obstacle_grid, height_map, and preview image.

    world_points: (T, 3, H, W) — Y=up, X=right, Z=forward
    world_conf:   (T, H, W)

    Returns dict with paths and metadata.
    """
    from scipy.ndimage import binary_fill_holes, binary_dilation
    from scipy.spatial import ConvexHull
    from PIL import Image

    T, _, H, W = world_points.shape
    pts  = world_points.transpose(0, 2, 3, 1).reshape(-1, 3)
    conf = world_conf.reshape(-1)
    pts  = pts[conf > conf_threshold]

    if len(pts) < 50:
        raise ValueError(
            f"Only {len(pts)} confident points (threshold={conf_threshold}). "
            f"The video likely does not cover enough of the store. "
            f"Walk the complete store perimeter before aisles. "
            f"Minimum recommended: ~100 frames covering the full floor boundary."
        )

    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]

    # Identify floor and ceiling heights via percentiles
    y_floor   = float(np.percentile(y, 5))
    y_ceiling = float(np.percentile(y, 90))
    logger.info = print   # fallback for helper context
    print(f"  y_floor={y_floor:.3f} y_ceiling={y_ceiling:.3f} (world units, not metres)")

    # Obstacle slice: horizontal cross-section at mid-height captures walls + shelving
    mid_y     = (y_floor + y_ceiling) * 0.5
    thickness = (y_ceiling - y_floor) * 0.15
    in_slice  = (y > mid_y - thickness) & (y < mid_y + thickness)
    sx, sz    = x[in_slice], z[in_slice]

    origin_x = float(x.min())
    origin_z = float(z.min())
    gw = int((x.max() - origin_x) / grid_resolution) + 1
    gh = int((z.max() - origin_z) / grid_resolution) + 1

    # Clamp grid size to prevent memory issues with very large reconstructions
    MAX_GRID = 4000
    if gw > MAX_GRID or gh > MAX_GRID:
        scale_factor = MAX_GRID / max(gw, gh)
        grid_resolution = grid_resolution / scale_factor
        gw = int((x.max() - origin_x) / grid_resolution) + 1
        gh = int((z.max() - origin_z) / grid_resolution) + 1

    obstacle_grid = np.zeros((gh, gw), dtype=bool)
    xi = np.clip(((sx - origin_x) / grid_resolution).astype(int), 0, gw - 1)
    zi = np.clip(((sz - origin_z) / grid_resolution).astype(int), 0, gh - 1)
    obstacle_grid[zi, xi] = True
    obstacle_grid = binary_dilation(obstacle_grid, iterations=2)

    # Floor mask: fill interior, subtract obstacles
    filled     = binary_fill_holes(obstacle_grid)
    floor_mask = filled & ~obstacle_grid

    # Convex hull fallback if binary_fill_holes found nothing (open perimeter)
    if floor_mask.sum() == 0:
        print("  WARNING: binary_fill_holes returned empty floor. "
              "Perimeter is not closed (insufficient video coverage). "
              "Using convex hull of floor-level points as fallback.")
        floor_pts = pts[(y - y_floor) < (y_ceiling - y_floor) * 0.3]
        if len(floor_pts) >= 4:
            fp_x = np.clip(((floor_pts[:, 0] - origin_x) / grid_resolution).astype(int), 0, gw - 1)
            fp_z = np.clip(((floor_pts[:, 2] - origin_z) / grid_resolution).astype(int), 0, gh - 1)
            xy   = np.stack([fp_x, fp_z], axis=1)
            try:
                hull  = ConvexHull(xy)
                from PIL import ImageDraw
                img_tmp = Image.new('L', (gw, gh), 0)
                draw    = ImageDraw.Draw(img_tmp)
                hull_pts = [(int(xy[v, 0]), int(xy[v, 1])) for v in hull.vertices]
                draw.polygon(hull_pts, fill=255)
                hull_mask  = np.array(img_tmp) > 0
                floor_mask = hull_mask & ~obstacle_grid
            except Exception as e:
                print(f"  Convex hull failed: {e}. floor_area will be 0.")

    floor_area_m2 = float(floor_mask.sum()) * (grid_resolution ** 2)
    print(f"  floor_area={floor_area_m2:.1f} (world units², divide by anchor_scale² for m²)")

    # Ceiling height map — max Y per grid cell above floor
    height_map  = np.zeros((gh, gw), dtype=np.float32)
    above_floor = y > (y_floor + 0.3)
    hx = np.clip(((x[above_floor] - origin_x) / grid_resolution).astype(int), 0, gw - 1)
    hz = np.clip(((z[above_floor] - origin_z) / grid_resolution).astype(int), 0, gh - 1)
    hy = y[above_floor]
    for i in range(len(hx)):
        if hy[i] > height_map[hz[i], hx[i]]:
            height_map[hz[i], hx[i]] = hy[i]
    height_map -= y_floor

    # Save outputs
    floor_mask_path = os.path.join(output_dir, 'floor_mask.png')
    obstacle_path   = os.path.join(output_dir, 'obstacle_grid.png')
    height_map_path = os.path.join(output_dir, 'height_map.png')
    preview_path    = os.path.join(output_dir, 'preview.jpg')

    Image.fromarray((floor_mask    * 255).astype(np.uint8), 'L').save(floor_mask_path)
    Image.fromarray((obstacle_grid * 255).astype(np.uint8), 'L').save(obstacle_path)
    height_mm = np.clip(height_map * 1000, 0, 65535).astype(np.uint16)
    Image.fromarray(height_mm, 'I;16').save(height_map_path)

    preview = np.ones((gh, gw, 3), dtype=np.uint8) * 255
    preview[floor_mask]    = [220, 220, 220]
    preview[obstacle_grid] = [60,  60,  60]
    Image.fromarray(preview).save(preview_path, quality=90)

    return {
        'floor_mask_path': floor_mask_path,
        'obstacle_path':   obstacle_path,
        'height_map_path': height_map_path,
        'preview_path':    preview_path,
        'floor_area_m2':   floor_area_m2,
        'origin_x':        origin_x,
        'origin_z':        origin_z,
    }


def _save_point_cloud(world_points, world_conf, rgb_colours,
                       conf_threshold, output_dir):
    """
    Save two coloured PLY files:
      point_cloud.ply     — full resolution, XYZ + RGB
      point_cloud_web.ply — every 10th point, XYZ + RGB, for browser viewer

    rgb_colours: (T, H, W, 3) uint8 — pixel-aligned with world_points (T, 3, H, W)

    The shell reconstruction issue in Three.js was caused by exporting XYZ only.
    trimesh.PointCloud requires colours as (N, 4) RGBA uint8.
    The paper's Figure S3 shows RGB-coloured point clouds — this is the correct output.
    """
    import trimesh

    T, _, H, W = world_points.shape
    pts  = world_points.transpose(0, 2, 3, 1).reshape(-1, 3)
    conf = world_conf.reshape(-1)
    rgb  = rgb_colours.reshape(-1, 3)   # (T*H*W, 3) uint8

    mask  = conf > conf_threshold
    pts   = pts[mask]
    rgb   = rgb[mask]
    rgba  = np.concatenate([rgb, np.full((len(rgb), 1), 255, dtype=np.uint8)], axis=1)

    # Full resolution — for download and future camera planning
    cloud    = trimesh.PointCloud(vertices=pts, colors=rgba)
    ply_path = os.path.join(output_dir, 'point_cloud.ply')
    cloud.export(ply_path)

    # Decimated for browser — every 10th point, still visually dense
    cloud_web = trimesh.PointCloud(vertices=pts[::10], colors=rgba[::10])
    web_path  = os.path.join(output_dir, 'point_cloud_web.ply')
    cloud_web.export(web_path)

    return ply_path, web_path


def _extract_frames(video_path, output_dir, fps=10):
    """Extract frames from video using ffmpeg. Must be on PATH."""
    import subprocess
    subprocess.run([
        'ffmpeg', '-i', video_path,
        '-vf', f'fps={fps}',
        '-q:v', '2',
        os.path.join(output_dir, '%06d.jpg'),
    ], check=True, capture_output=True)
```

---

## URL routing

### config/urls.py

```python
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/',    admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('',          include('apps.sites.urls', namespace='sites')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

### apps/sites/urls.py

```python
from django.urls import path, include
from . import views

app_name = 'sites'
urlpatterns = [
    path('',           views.SiteListView.as_view(),   name='list'),
    path('new/',       views.SiteCreateView.as_view(), name='create'),
    path('<uuid:pk>/', views.SiteDetailView.as_view(), name='detail'),
    path('<uuid:pk>/scans/', include('apps.scans.urls', namespace='scans')),
]
```

### apps/scans/urls.py

```python
from django.urls import path
from . import views

app_name = 'scans'
urlpatterns = [
    path('new/',                    views.ScanCreateView.as_view(), name='create'),
    path('<uuid:scan_pk>/',         views.ScanDetailView.as_view(), name='detail'),
    path('<uuid:scan_pk>/status/',  views.ScanStatusView.as_view(), name='status'),
    path('<uuid:scan_pk>/retry/',   views.ScanRetryView.as_view(),  name='retry'),
]
```

---

## Views

### apps/sites/views.py

```python
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, CreateView
from django.urls import reverse_lazy
from .models import JobSite
from .forms import JobSiteForm


class SiteListView(LoginRequiredMixin, ListView):
    model               = JobSite
    template_name       = 'sites/list.html'
    context_object_name = 'sites'

    def get_queryset(self):
        return JobSite.objects.filter(owner=self.request.user).prefetch_related('scans')


class SiteDetailView(LoginRequiredMixin, DetailView):
    model               = JobSite
    template_name       = 'sites/detail.html'
    context_object_name = 'site'

    def get_queryset(self):
        return JobSite.objects.filter(owner=self.request.user)


class SiteCreateView(LoginRequiredMixin, CreateView):
    model         = JobSite
    form_class    = JobSiteForm
    template_name = 'sites/create.html'
    success_url   = reverse_lazy('sites:list')

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)
```

### apps/scans/views.py

```python
import os
import zipfile
import io
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import CreateView, DetailView
from django.views import View
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from .models import Scan
from .forms import ScanCreateForm
from apps.sites.models import JobSite


class ScanCreateView(LoginRequiredMixin, CreateView):
    model         = Scan
    form_class    = ScanCreateForm
    template_name = 'scans/create.html'

    def get_site(self):
        return get_object_or_404(JobSite, pk=self.kwargs['pk'], owner=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['site'] = self.get_site()
        return ctx

    def form_valid(self, form):
        site  = self.get_site()
        scan  = form.save(commit=False)
        scan.site = site

        upload = self.request.FILES.get('upload')
        if not upload:
            form.add_error(None, 'Please upload a video (.mp4) or image archive (.zip).')
            return self.form_invalid(form)

        input_dir = scan.input_path
        os.makedirs(input_dir, exist_ok=True)

        if scan.input_type == Scan.InputType.VIDEO:
            video_path = os.path.join(input_dir, 'input.mp4')
            with open(video_path, 'wb') as f:
                for chunk in upload.chunks():
                    f.write(chunk)
            from .tasks import _extract_frames
            _extract_frames(video_path, input_dir, fps=scan.fps)
        else:
            zf = zipfile.ZipFile(io.BytesIO(upload.read()))
            zf.extractall(input_dir)

        scan.input_dir = input_dir
        scan.save()

        from .tasks import run_scan
        run_scan.delay(str(scan.id))

        return redirect('sites:scans:detail', pk=site.pk, scan_pk=scan.pk)


class ScanDetailView(LoginRequiredMixin, DetailView):
    model               = Scan
    template_name       = 'scans/detail.html'
    context_object_name = 'scan'
    pk_url_kwarg        = 'scan_pk'

    def get_queryset(self):
        return Scan.objects.filter(site__owner=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['site'] = self.object.site
        return ctx


class ScanStatusView(LoginRequiredMixin, View):
    def get(self, request, **kwargs):
        scan = get_object_or_404(Scan, pk=kwargs['scan_pk'], site__owner=request.user)
        return JsonResponse({
            'status':       scan.status,
            'preview_url':  scan.preview_url,
            'web_ply_url':  scan.web_ply_url,
            'floor_area':   round(scan.floor_area_m2, 1) if scan.floor_area_m2 else None,
            'frame_count':  scan.frame_count,
            'duration':     round(scan.duration_seconds) if scan.duration_seconds else None,
            'anchor_scale': scan.anchor_scale,
            'error':        scan.error_message or None,
        })


class ScanRetryView(LoginRequiredMixin, View):
    def post(self, request, **kwargs):
        scan = get_object_or_404(
            Scan, pk=kwargs['scan_pk'],
            site__owner=request.user,
            status=Scan.Status.FAILED,
        )
        scan.status        = Scan.Status.PENDING
        scan.error_message = ''
        scan.save(update_fields=['status', 'error_message'])
        from .tasks import run_scan
        run_scan.delay(str(scan.id))
        return redirect('sites:scans:detail', pk=scan.site.pk, scan_pk=scan.pk)
```

---

## Forms

### apps/sites/forms.py

```python
from django import forms
from .models import JobSite

class JobSiteForm(forms.ModelForm):
    class Meta:
        model  = JobSite
        fields = ['name', 'address', 'place_id', 'latitude', 'longitude', 'store_type', 'notes']
        widgets = {
            'address':   forms.TextInput(attrs={'id': 'address-input', 'autocomplete': 'off',
                                                 'placeholder': 'Start typing an address…'}),
            'place_id':  forms.HiddenInput(),
            'latitude':  forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
            'notes':     forms.Textarea(attrs={'rows': 3}),
        }
```

### apps/scans/forms.py

```python
from django import forms
from .models import Scan

class ScanCreateForm(forms.ModelForm):
    upload = forms.FileField(
        label='Upload video (.mp4) or image zip (.zip)',
        widget=forms.FileInput(attrs={'accept': '.mp4,.zip'}),
    )

    class Meta:
        model  = Scan
        fields = ['name', 'notes', 'input_type', 'fps', 'mode',
                  'kv_window_size', 'keyframe_interval', 'conf_threshold']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
```

---

## Settings

### config/settings/base.py

```python
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent

def env(key, default=None):
    val = os.environ.get(key, default)
    if val is None:
        raise ImproperlyConfigured(f"Required env var {key} is not set")
    return val

SECRET_KEY = env('SECRET_KEY', 'dev-secret-not-for-production')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'apps.sites',
    'apps.scans',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF       = 'config.urls'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL          = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

STATIC_URL = '/static/'
MEDIA_URL  = '/media/'
MEDIA_ROOT = env('MEDIA_ROOT', str(BASE_DIR / 'media'))

CHECKPOINT_ROOT         = env('CHECKPOINT_ROOT', '/tmp/checkpoints')
LINGBOT_CHECKPOINT_PATH = env('LINGBOT_CHECKPOINT_PATH', '/tmp/checkpoints/lingbot-map.pt')

CELERY_BROKER_URL      = env('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND  = CELERY_BROKER_URL
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT  = ['json']
CELERY_TASK_TIME_LIMIT = 7200

GOOGLE_MAPS_API_KEY = env('GOOGLE_MAPS_API_KEY', '')

DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024 * 1024
FILE_UPLOAD_HANDLERS = ['django.core.files.uploadhandler.TemporaryFileUploadHandler']
```

### config/settings/local.py

```python
from .base import *

DEBUG         = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME':   BASE_DIR / 'db.sqlite3',
    }
}

CELERY_TASK_ALWAYS_EAGER     = True
CELERY_TASK_EAGER_PROPAGATES = True
```

### config/settings/production.py

```python
from .base import *
import os

DEBUG         = False
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')

DATABASES = {
    'default': {
        'ENGINE':   'django.db.backends.postgresql',
        'NAME':     os.environ['DB_NAME'],
        'USER':     os.environ['DB_USER'],
        'PASSWORD': os.environ['DB_PASSWORD'],
        'HOST':     os.environ.get('DB_HOST', 'localhost'),
        'PORT':     os.environ.get('DB_PORT', '5432'),
    }
}

SECURE_SSL_REDIRECT         = True
SESSION_COOKIE_SECURE       = True
CSRF_COOKIE_SECURE          = True
SECURE_BROWSER_XSS_FILTER   = True
SECURE_CONTENT_TYPE_NOSNIFF = True
```

### config/celery.py

```python
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
app = Celery('fpa_web')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

### config/__init__.py

```python
from .celery import app as celery_app
__all__ = ('celery_app',)
```

---

## requirements.txt

```
django>=4.2,<5.0
celery>=5.3
redis>=5.0
Pillow>=10.0
numpy>=1.26
scipy>=1.11
trimesh>=4.0
torch>=2.0
torchvision>=0.15
opencv-python>=4.8
tqdm>=4.66
einops>=0.7
safetensors>=0.4
huggingface_hub>=0.20
python-decouple>=3.8
```

Install torch with correct CUDA wheel:
    pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128

---

## Templates to generate

Use Django template tags, Tailwind Play CDN. No React, Vue, Alpine, or HTMX.

### 1. templates/base.html
Nav: "FPA Scoping" → sites:list, username, logout.
Django messages block. {% block content %} {% block extra_js %} at body end.

### 2. templates/sites/list.html
Table: Site name, Address, Store type, Scans, Latest status, Actions.
"Add site" button. Empty state.

### 3. templates/sites/create.html
JobSiteForm with Google Places Autocomplete on #address-input.
JS populates hidden place_id, latitude, longitude on place_changed.
Script: https://maps.googleapis.com/maps/api/js?key={{ GOOGLE_MAPS_API_KEY }}&libraries=places

### 4. templates/sites/detail.html
Site name, address (Google Maps link), store type, notes.
"New scan" button. Table of scans with status badges.

### 5. templates/scans/create.html
File upload (drag-drop). Basic fields: name, notes, input_type, fps.
Collapsible Advanced: mode, kv_window_size, keyframe_interval, conf_threshold.
Help text: "Minimum 2-3 minutes of video covering the full store perimeter."

### 6. templates/scans/detail.html — three states

STATE pending/processing:
  Status badge id="status-badge". Spinner. Metadata. JS polling block (below).

STATE done:
  Metadata: floor_area_m2, frame_count, duration, anchor_scale.
  Full-width 3D viewer (below).
  Top-down preview image at 50% width.
  Download PLY link.

STATE failed:
  Red status badge. Error in id="error-section" > id="error-msg". Retry POST form.

---

## 3D viewer component — paste verbatim in {% if scan.status == 'done' %}

The PLY now contains XYZ + RGB colour. The viewer uses vertex colours from the PLY directly
rather than computing height-based colours. Height colour toggle still available.

```html
<div id="viewer-wrap"
     style="border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;
            background:#0d0d0f;margin-bottom:1.5rem">

  <canvas id="three-canvas"
          style="display:block;width:100%;height:520px;cursor:grab"></canvas>

  <div style="display:flex;align-items:center;justify-content:space-between;
              padding:10px 16px;border-top:1px solid rgba(255,255,255,0.08);
              background:#111113">
    <div style="display:flex;gap:20px">
      <span style="font-size:12px;color:rgba(255,255,255,.4)">
        points&nbsp;<strong id="pt-count" style="color:rgba(255,255,255,.85)">loading…</strong>
      </span>
      <span style="font-size:12px;color:rgba(255,255,255,.4)">
        floor area&nbsp;
        <strong style="color:rgba(255,255,255,.85)">{{ scan.floor_area_m2|floatformat:1 }} units²</strong>
      </span>
      <span style="font-size:12px;color:rgba(255,255,255,.4)">
        frames&nbsp;
        <strong style="color:rgba(255,255,255,.85)">{{ scan.frame_count }}</strong>
      </span>
    </div>
    <div style="display:flex;gap:6px">
      <button onclick="setView('3d')"  id="btn-3d"    class="vbtn active">3D</button>
      <button onclick="setView('top')" id="btn-top"   class="vbtn">Top-down</button>
      <button onclick="cycleColor()"   id="btn-color" class="vbtn">Height colour</button>
      <a href="{{ scan.point_cloud_url }}" download
         style="font-size:12px;padding:4px 10px;border-radius:6px;
                border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.06);
                color:rgba(255,255,255,.7);text-decoration:none">Download PLY</a>
    </div>
  </div>
</div>

<style>
  .vbtn{font-size:12px;padding:4px 10px;border-radius:6px;cursor:pointer;
        border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.06);
        color:rgba(255,255,255,.7)}
  .vbtn:hover{background:rgba(255,255,255,.12);color:#fff}
  .vbtn.active{background:rgba(255,255,255,.18);color:#fff;border-color:rgba(255,255,255,.3)}
</style>

<script src="https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.160.0/examples/js/loaders/PLYLoader.js"></script>
<script>
(function(){
  const PLY_URL = "{{ scan.web_ply_url }}";
  const canvas  = document.getElementById('three-canvas');
  const W = canvas.parentElement.clientWidth, H = 520;

  const renderer = new THREE.WebGLRenderer({canvas, antialias:true});
  renderer.setPixelRatio(devicePixelRatio);
  renderer.setSize(W, H);
  renderer.setClearColor(0x0d0d0f);

  const scene  = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, W/H, 0.01, 500);

  let theta=-0.3, phi=0.4, radius=20;
  let tTheta=theta, tPhi=phi, tRadius=radius;
  let dragging=false, lastX=0, lastY=0, topView=false;

  const loader = new THREE.PLYLoader();
  loader.load(PLY_URL, function(geo){
    geo.computeBoundingBox();
    const centre = new THREE.Vector3();
    geo.boundingBox.getCenter(centre);
    geo.translate(-centre.x, -centre.y, -centre.z);
    geo.computeBoundingBox();

    const size = new THREE.Vector3();
    geo.boundingBox.getSize(size);
    radius = tRadius = Math.max(size.x, size.z) * 1.1;
    camera.far = radius * 10;
    camera.updateProjectionMatrix();

    const nPts = geo.attributes.position.array.length / 3;
    document.getElementById('pt-count').textContent = nPts.toLocaleString();

    // PLY has RGB vertex colours from the actual camera frames — use them directly.
    // Also compute height-based colours for toggle.
    const posArr = geo.attributes.position.array;
    let yMin=Infinity, yMax=-Infinity;
    for(let i=1;i<posArr.length;i+=3){
      if(posArr[i]<yMin) yMin=posArr[i];
      if(posArr[i]>yMax) yMax=posArr[i];
    }

    const hColArr = new Float32Array(nPts*3);
    const ca=new THREE.Color(), cb=new THREE.Color();
    for(let i=0;i<nPts;i++){
      const t=Math.max(0,Math.min(1,(posArr[i*3+1]-yMin)/(yMax-yMin)));
      let c;
      if(t<0.33){ca.set(0x1D9E75);cb.set(0x378ADD);c=ca.clone().lerp(cb,t/0.33);}
      else if(t<0.66){ca.set(0x378ADD);cb.set(0xEF9F27);c=ca.clone().lerp(cb,(t-0.33)/0.33);}
      else{ca.set(0xEF9F27);cb.set(0xD85A30);c=ca.clone().lerp(cb,(t-0.66)/0.34);}
      hColArr[i*3]=c.r; hColArr[i*3+1]=c.g; hColArr[i*3+2]=c.b;
    }

    // Store both colour arrays
    window._geo    = geo;
    window._hCol   = hColArr;
    // If PLY has vertex colours, store them; otherwise fall back to height colours
    window._rgbCol = geo.attributes.color
                     ? geo.attributes.color.array.slice()
                     : hColArr.slice();
    window._cMode  = 0;  // 0=RGB, 1=height

    // Start with RGB colours (from camera frames)
    if(!geo.attributes.color){
      geo.setAttribute('color', new THREE.BufferAttribute(hColArr.slice(), 3));
      window._cMode = 1;  // no RGB available, start in height mode
      document.getElementById('btn-color').textContent = 'RGB colour';
    }

    const mat   = new THREE.PointsMaterial({size:0.05, vertexColors:true, sizeAttenuation:true});
    scene.add(new THREE.Points(geo, mat));
  });

  window.setView = function(mode){
    document.getElementById('btn-3d').classList.toggle('active', mode==='3d');
    document.getElementById('btn-top').classList.toggle('active', mode==='top');
    topView = mode==='top';
    if(mode==='top'){tPhi=Math.PI/2-0.01;tTheta=0;tRadius=radius*1.25;}
    else{tPhi=0.4;tTheta=-0.3;tRadius=radius;}
  };

  window.cycleColor = function(){
    if(!window._geo) return;
    window._cMode = 1 - window._cMode;
    const arr = window._cMode===0 ? window._rgbCol : window._hCol;
    window._geo.attributes.color.array.set(arr);
    window._geo.attributes.color.needsUpdate = true;
    document.getElementById('btn-color').textContent =
      window._cMode===0 ? 'Height colour' : 'RGB colour';
  };

  canvas.addEventListener('mousedown',e=>{dragging=true;lastX=e.clientX;lastY=e.clientY;});
  window.addEventListener('mouseup',()=>dragging=false);
  window.addEventListener('mousemove',e=>{
    if(!dragging||topView) return;
    tTheta-=(e.clientX-lastX)*0.008;
    tPhi=Math.max(0.05,Math.min(Math.PI/2-0.01,tPhi-(e.clientY-lastY)*0.008));
    lastX=e.clientX;lastY=e.clientY;
  });
  canvas.addEventListener('wheel',e=>{
    tRadius=Math.max(2,Math.min(500,tRadius+e.deltaY*0.03));
    e.preventDefault();
  },{passive:false});

  let t0=null;
  canvas.addEventListener('touchstart',e=>{
    if(e.touches.length===1){dragging=true;lastX=e.touches[0].clientX;lastY=e.touches[0].clientY;}
    if(e.touches.length===2) t0=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);
  },{passive:true});
  canvas.addEventListener('touchend',()=>{dragging=false;t0=null;});
  canvas.addEventListener('touchmove',e=>{
    if(e.touches.length===1&&dragging&&!topView){
      tTheta-=(e.touches[0].clientX-lastX)*0.01;
      tPhi=Math.max(0.05,Math.min(Math.PI/2-0.01,tPhi-(e.touches[0].clientY-lastY)*0.01));
      lastX=e.touches[0].clientX;lastY=e.touches[0].clientY;
    }
    if(e.touches.length===2&&t0!==null){
      const d=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);
      tRadius=Math.max(2,Math.min(500,tRadius-(d-t0)*0.05));
      t0=d;
    }
  },{passive:true});

  function lerp(a,b,t){return a+(b-a)*t;}
  (function animate(){
    requestAnimationFrame(animate);
    theta=lerp(theta,tTheta,0.1);phi=lerp(phi,tPhi,0.1);radius=lerp(radius,tRadius,0.1);
    camera.position.set(
      radius*Math.cos(phi)*Math.sin(theta),
      radius*Math.sin(phi),
      radius*Math.cos(phi)*Math.cos(theta)
    );
    camera.lookAt(0,0,0);
    renderer.render(scene,camera);
  })();
})();
</script>
```

---

## JS polling block

```html
{% if scan.status == 'pending' or scan.status == 'processing' %}
<script>
  const STATUS_URL = "{% url 'sites:scans:status' pk=site.pk scan_pk=scan.pk %}";

  function updateBadge(status){
    const b=document.getElementById('status-badge');
    const cfg={
      pending:   ['Pending',    'bg-gray-100 text-gray-700'],
      processing:['Processing', 'bg-blue-100 text-blue-700'],
      done:      ['Done',       'bg-green-100 text-green-700'],
      failed:    ['Failed',     'bg-red-100 text-red-700'],
    };
    const [label,cls]=cfg[status]||['Unknown',''];
    b.textContent=label;
    b.className='inline-block px-2 py-0.5 rounded text-sm font-medium '+cls;
  }

  const timer=setInterval(async()=>{
    try{
      const res=await fetch(STATUS_URL);
      const data=await res.json();
      updateBadge(data.status);
      if(data.status==='done'){clearInterval(timer);window.location.reload();}
      if(data.status==='failed'){
        clearInterval(timer);
        const box=document.getElementById('error-section');
        if(box){
          box.style.display='block';
          const msg=document.getElementById('error-msg');
          if(msg) msg.textContent=data.error||'Unknown error';
        }
      }
    }catch(e){console.warn('Poll error:',e);}
  },3000);
</script>
{% endif %}
```

---

## Bootstrap commands

```bash
cd fpa_web
python manage.py makemigrations sites scans
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Production Celery worker:
```bash
celery -A config worker --loglevel=info --concurrency=1
```

---

## Nginx config (production)

```nginx
server {
    listen 80;
    server_name your.domain.com;
    client_max_body_size 5G;

    location /media/ {
        alias /absolute/path/to/fpa_web/media/;
        add_header Access-Control-Allow-Origin *;
    }

    location /static/ { alias /absolute/path/to/fpa_web/staticfiles/; }

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }
}
```

---

## Implementation notes — read before writing any file

1.  NEVER import lingbot_map at module level in views, models, or forms.
    Only import inside the Celery task function body.

2.  torch.load uses weights_only=True. Do not change this.

3.  Use torch.amp.autocast('cuda', dtype=dtype) — NOT torch.cuda.amp.autocast().
    The cuda.amp form is deprecated and generates FutureWarning in your test output.

4.  The default kv_cache_sliding_window is NOW 64, not 16.
    This is per the paper's Section 4.4 "Default Inference Configuration".
    The Scan model field is kv_window_size with default=64.

5.  InferenceMode choices are NOW 'direct' and 'vo' — not 'streaming' and 'windowed'.
    This matches the paper's terminology. Update any existing migration if mode field exists.

6.  _save_point_cloud NOW takes rgb_colours (T, H, W, 3) uint8 and exports XYZ+RGB PLY.
    trimesh.PointCloud(vertices=pts, colors=rgba) where rgba is (N, 4) uint8.
    This fixes the shell/hollow reconstruction in Three.js.

7.  The Three.js viewer NOW uses PLY vertex colours (RGB from camera frames) as the
    primary colour mode. Height colour is a toggle. Both arrays stored in window._rgbCol
    and window._hCol. cycleColor() swaps between them.

8.  floor_area_m2 is in world coordinate units squared, NOT metres squared.
    Divide by anchor_scale² to get approximate metres². Display as "units²" in the UI
    until anchor scale calibration is implemented. anchor_scale is saved on the Scan model.

9.  The extrinsic inversion using closed_form_inverse_se3_general may not be needed.
    The paper states the model outputs c2w directly. The task logs extrinsic[0] translation
    to help diagnose which convention the checkpoint uses.

10. CELERY_TASK_ALWAYS_EAGER=True in local.py: upload view blocks until reconstruction.
    Acceptable for dev testing. Disable in production.

11. FILE_UPLOAD_HANDLERS must be TemporaryFileUploadHandler for large video files.

12. ffmpeg must be on PATH. macOS: brew install ffmpeg. Ubuntu: apt install ffmpeg.

13. Three.js version 0.160.0 exactly. PLYLoader at:
    https://cdn.jsdelivr.net/npm/three@0.160.0/examples/js/loaders/PLYLoader.js
    It self-attaches as THREE.PLYLoader when loaded as UMD.

14. CORS header on nginx /media/ is required — Three.js fetches PLY via XHR.

15. UUID primary keys on all models. URL patterns use <uuid:pk> and <uuid:scan_pk>.

16. Minimum video length warning: the task raises ValueError if fewer than 20 frames
    found. The recommended minimum for a retail store is ~100 frames (60s at 10 FPS)
    covering the FULL perimeter. The convex hull fallback handles partial coverage
    gracefully but the floor plan will be approximate.

17. anchor_scale: the model works in normalised world coordinates, not metres.
    anchor_scale = mean ||x|| for anchor frame point cloud, saved on Scan.
    Future: use known ceiling height (e.g. 3.2m from Aurora mount spec) to calibrate
    a world-to-metres conversion factor and report floor_area in true m².
```
