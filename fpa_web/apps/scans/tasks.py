import contextlib
import json
import logging
import os
import time

import numpy as np
import torch
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _write_json(path, payload):
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def _build_camera_path(extrinsic, sample_limit=120):
    frames = []
    total = int(extrinsic.shape[0])
    step = max(total // sample_limit, 1)
    for index in range(0, total, step):
        matrix = extrinsic[index]
        frames.append(
            {
                'index': index,
                'matrix': matrix.tolist(),
                'position': matrix[:3, 3].tolist(),
                'forward': [-float(matrix[0, 2]), -float(matrix[1, 2]), -float(matrix[2, 2])],
                'up': [float(matrix[0, 1]), float(matrix[1, 1]), float(matrix[2, 1])],
            }
        )
    return {'frame_count': total, 'sample_step': step, 'frames': frames}


def _build_scene_manifest(scan, artifacts, point_cloud_path, web_ply_path, camera_path_path, *, duration_seconds, status='done'):
    return {
        'scan_id': str(scan.id),
        'site_id': str(scan.site_id),
        'scan_name': scan.name,
        'generated_at': timezone.now().isoformat(),
        'status': status,
        'frame_count': scan.frame_count,
        'duration_seconds': duration_seconds,
        'floor_area_m2': artifacts['floor_area_m2'],
        'anchor_scale': scan.anchor_scale,
        'grid_resolution': scan.grid_resolution,
        'viewer': {
            'default_mode': 'orbit',
            'available_modes': ['orbit', 'walkthrough'],
            'available_overlays': ['rgb', 'height', 'occupancy', 'camera_path'],
        },
        'assets': {
            'preview': os.path.basename(artifacts['preview_path']),
            'floor_mask': os.path.basename(artifacts['floor_mask_path']),
            'obstacle_grid': os.path.basename(artifacts['obstacle_path']),
            'height_map': os.path.basename(artifacts['height_map_path']),
            'point_cloud': os.path.basename(point_cloud_path),
            'web_point_cloud': os.path.basename(web_ply_path),
            'camera_path': os.path.basename(camera_path_path),
            'mesh': os.path.basename(scan.mesh_path) if scan.mesh_path else '',
        },
    }


@shared_task(bind=True, max_retries=0, time_limit=7200)
def run_scan(self, scan_id: str):
    """
    LingBot-Map 3D reconstruction task.
    
    Processes a sequence of image frames through the LingBot-Map model to produce:
    - Camera pose trajectory (c2w extrinsics)
    - Dense 3D point cloud with confidence scores
    - RGB colours, depth maps, and scene metadata
    
    CPU Processing (Fallback):
    - Inference time: ~30-60s per frame on modern CPU
    - Recommended: Use GPU for production (A100/H100 ~1-2s per frame)
    - Memory: ~16-24GB for 200+ frame scans
    - Precision: float32 (more stable on CPU than float16)
    """
    from apps.scans.models import Scan

    scan = Scan.objects.get(id=scan_id)
    scan.status = Scan.Status.PROCESSING
    scan.started_at = timezone.now()
    scan.celery_task_id = self.request.id
    scan.save(update_fields=['status', 'started_at', 'celery_task_id'])
    logger.info('[scan:%s] started', scan_id)

    try:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        is_cpu = device.type == 'cpu'
        logger.info('[scan:%s] device=%s (CPU fallback processing)', scan_id, device)

        from lingbot_map.utils.load_fn import load_and_preprocess_images

        paths = _collect_image_paths(scan.input_path)
        if not paths:
            raise ValueError(f'No images found in {scan.input_path}')
        if len(paths) < 20:
            raise ValueError(
                f'Only {len(paths)} frames found. LingBot-Map needs at least ~100 frames '
                f'(~60 seconds at 10 FPS) for a retail store reconstruction. '
                'Re-capture with a longer walkthrough covering the full perimeter.'
            )

        scan.frame_count = len(paths)
        scan.save(update_fields=['frame_count'])
        logger.info('[scan:%s] %s frames', scan_id, len(paths))

        images = load_and_preprocess_images(paths, mode='crop', image_size=518, patch_size=14).to(device)
        rgb_for_colour = _load_rgb_for_colour(paths, target_h=378, target_w=518)

        if scan.mode == 'vo':
            from lingbot_map.models.gct_stream_window import GCTStream
        else:
            from lingbot_map.models.gct_stream import GCTStream

        model = GCTStream(
            img_size=518,
            patch_size=14,
            enable_3d_rope=True,
            max_frame_num=1024,
            kv_cache_sliding_window=scan.kv_window_size,
            kv_cache_scale_frames=8,
            kv_cache_cross_frame_special=True,
            kv_cache_include_scale_frames=True,
            use_sdpa=not torch.cuda.is_available(),
        )

        ckpt_path = settings.LINGBOT_CHECKPOINT_PATH
        logger.info('[scan:%s] loading checkpoint: %s', scan_id, ckpt_path)
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=True)
        model.load_state_dict(ckpt.get('model', ckpt), strict=False)
        model = model.to(device).eval()

        # CPU-specific optimizations
        if is_cpu:
            torch.set_num_threads(torch.get_num_threads())
            logger.info('[scan:%s] CPU threads: %d', scan_id, torch.get_num_threads())
            # Enable gradient checkpointing to save memory
            if hasattr(model, 'use_gradient_checkpoint'):
                model.use_gradient_checkpoint = True

        # CPU-friendly dtype selection
        # On CPU: use float32 (float16 is slower and less stable)
        # On GPU: use bfloat16 if supported (A100+), else float16
        if is_cpu:
            dtype = torch.float32
            amp_enabled = False  # Autocast not beneficial on CPU with float32
            logger.info('[scan:%s] CPU inference: float32 precision, no autocast', scan_id)
        else:
            use_bf16 = torch.cuda.get_device_capability()[0] >= 8
            dtype = torch.bfloat16 if use_bf16 else torch.float16
            amp_enabled = True
            amp_device = 'cuda'

        # AMP context only for GPU
        if amp_enabled:
            amp_ctx = torch.amp.autocast(amp_device, dtype=dtype)
        else:
            amp_ctx = contextlib.nullcontext()

        logger.info('[scan:%s] inference mode=%s kv_window=%s dtype=%s', 
                   scan_id, scan.mode, scan.kv_window_size, dtype)
        t0 = time.time()

        with torch.no_grad(), amp_ctx:
            if scan.mode == Scan.InferenceMode.DIRECT:
                predictions = model.inference_streaming(
                    images,
                    num_scale_frames=8,
                    keyframe_interval=scan.keyframe_interval,
                )
            else:
                predictions = model.inference_windowed(
                    images,
                    window_size=max(scan.kv_window_size, 64),
                    overlap_size=16,
                    num_scale_frames=8,
                )

        logger.info('[scan:%s] inference done in %.1fs', scan_id, time.time() - t0)

        from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri

        extrinsic, intrinsic = pose_encoding_to_extri_intri(predictions['pose_enc'], images.shape[-2:])
        ext0 = extrinsic[0].cpu().float().numpy()
        logger.info('[scan:%s] extrinsic[0] translation: %s', scan_id, ext0[:, 3])
        if np.linalg.norm(ext0[:, 3]) > 5.0:
            logger.warning(
                '[scan:%s] extrinsic[0] translation norm=%.2f - may need w2c->c2w inversion',
                scan_id,
                np.linalg.norm(ext0[:, 3]),
            )

        extrinsic = extrinsic.cpu().float().numpy()
        intrinsic = intrinsic.cpu().float().numpy()
        _ = (extrinsic, intrinsic)
        camera_path = _build_camera_path(extrinsic)

        world_points = predictions['world_points'].squeeze(0).cpu().float().numpy()
        world_conf = predictions['world_points_conf'].squeeze(0).cpu().float().numpy()

        anchor_pts = world_points[:3].reshape(-1, 3)
        anchor_conf = world_conf[:3].reshape(-1)
        anchor_pts_f = anchor_pts[anchor_conf > scan.conf_threshold]
        anchor_scale = float(np.mean(np.linalg.norm(anchor_pts_f, axis=1))) if len(anchor_pts_f) > 10 else 1.0
        logger.info('[scan:%s] anchor_scale=%.4f', scan_id, anchor_scale)

        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        os.makedirs(scan.output_dir, exist_ok=True)
        artifacts = _extract_floor_artifacts(
            world_points=world_points,
            world_conf=world_conf,
            conf_threshold=scan.conf_threshold,
            grid_resolution=scan.grid_resolution,
            output_dir=scan.output_dir,
        )

        ply_path, web_ply_path = _save_point_cloud(
            world_points=world_points,
            world_conf=world_conf,
            rgb_colours=rgb_for_colour,
            conf_threshold=scan.conf_threshold,
            output_dir=scan.output_dir,
        )

        camera_path_path = os.path.join(scan.output_dir, 'camera_path.json')
        _write_json(camera_path_path, camera_path)

        scene_manifest_path = os.path.join(scan.output_dir, 'scene_manifest.json')
        scene_manifest = _build_scene_manifest(
            scan,
            artifacts,
            ply_path,
            web_ply_path,
            camera_path_path,
            duration_seconds=time.time() - t0,
        )
        _write_json(scene_manifest_path, scene_manifest)

        scan.status = Scan.Status.DONE
        scan.completed_at = timezone.now()
        scan.floor_mask_path = artifacts['floor_mask_path']
        scan.obstacle_path = artifacts['obstacle_path']
        scan.height_map_path = artifacts['height_map_path']
        scan.preview_path = artifacts['preview_path']
        scan.point_cloud_path = ply_path
        scan.web_ply_path = web_ply_path
        scan.scene_manifest_path = scene_manifest_path
        scan.camera_path_path = camera_path_path
        scan.floor_area_m2 = artifacts['floor_area_m2']
        scan.origin_x = artifacts['origin_x']
        scan.origin_z = artifacts['origin_z']
        scan.anchor_scale = anchor_scale
        scan.save(
            update_fields=[
                'status',
                'completed_at',
                'floor_mask_path',
                'obstacle_path',
                'height_map_path',
                'preview_path',
                'point_cloud_path',
                'web_ply_path',
                'scene_manifest_path',
                'camera_path_path',
                'floor_area_m2',
                'origin_x',
                'origin_z',
                'anchor_scale',
            ]
        )
        logger.info(
            '[scan:%s] ✓ DONE (device=%s) - floor_area=%.1f m² anchor_scale=%.4f duration=%.1fs frames=%d',
            scan_id,
            'cpu' if is_cpu else 'gpu',
            artifacts['floor_area_m2'],
            anchor_scale,
            time.time() - t0,
            scan.frame_count,
        )

    except Exception as exc:
        logger.exception('[scan:%s] FAILED: %s', scan_id, exc)
        scan.status = Scan.Status.FAILED
        scan.error_message = str(exc)
        scan.completed_at = timezone.now()
        scan.save(update_fields=['status', 'error_message', 'completed_at'])
        raise


def _collect_image_paths(folder: str) -> list:
    import glob

    paths = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG']:
        paths.extend(glob.glob(os.path.join(folder, '**', ext), recursive=True))
    return sorted(set(paths))


def _load_rgb_for_colour(paths: list, target_h: int = 378, target_w: int = 518) -> np.ndarray:
    from PIL import Image as PILImage

    frames = []
    for path in paths:
        image = PILImage.open(path).convert('RGB')
        width, height = image.size
        scale = max(target_w / width, target_h / height)
        new_w, new_h = int(width * scale), int(height * scale)
        image = image.resize((new_w, new_h), PILImage.BILINEAR)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        image = image.crop((left, top, left + target_w, top + target_h))
        frames.append(np.array(image, dtype=np.uint8))
    return np.stack(frames, axis=0)


def _extract_floor_artifacts(world_points, world_conf, conf_threshold, grid_resolution, output_dir):
    from PIL import Image, ImageDraw
    from scipy.ndimage import binary_dilation, binary_fill_holes
    from scipy.spatial import ConvexHull

    pts = world_points.transpose(0, 2, 3, 1).reshape(-1, 3)
    conf = world_conf.reshape(-1)
    pts = pts[conf > conf_threshold]

    if len(pts) < 50:
        raise ValueError(
            f'Only {len(pts)} confident points (threshold={conf_threshold}). '
            'The video likely does not cover enough of the store. '
            'Walk the complete store perimeter before aisles. '
            'Minimum recommended: ~100 frames covering the full floor boundary.'
        )

    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    y_floor = float(np.percentile(y, 5))
    y_ceiling = float(np.percentile(y, 90))
    logger.info('[floor] y_floor=%.3f y_ceiling=%.3f (world units)', y_floor, y_ceiling)

    mid_y = (y_floor + y_ceiling) * 0.5
    thickness = (y_ceiling - y_floor) * 0.15
    in_slice = (y > mid_y - thickness) & (y < mid_y + thickness)
    sx, sz = x[in_slice], z[in_slice]

    origin_x = float(x.min())
    origin_z = float(z.min())
    gw = int((x.max() - origin_x) / grid_resolution) + 1
    gh = int((z.max() - origin_z) / grid_resolution) + 1

    max_grid = 4000
    if gw > max_grid or gh > max_grid:
        scale_factor = max_grid / max(gw, gh)
        grid_resolution = grid_resolution / scale_factor
        gw = int((x.max() - origin_x) / grid_resolution) + 1
        gh = int((z.max() - origin_z) / grid_resolution) + 1

    obstacle_grid = np.zeros((gh, gw), dtype=bool)
    xi = np.clip(((sx - origin_x) / grid_resolution).astype(int), 0, gw - 1)
    zi = np.clip(((sz - origin_z) / grid_resolution).astype(int), 0, gh - 1)
    obstacle_grid[zi, xi] = True
    obstacle_grid = binary_dilation(obstacle_grid, iterations=2)

    filled = binary_fill_holes(obstacle_grid)
    floor_mask = filled & ~obstacle_grid

    if floor_mask.sum() == 0:
        logger.warning('[floor] binary_fill_holes returned empty floor; using convex hull fallback')
        floor_pts = pts[(y - y_floor) < (y_ceiling - y_floor) * 0.3]
        if len(floor_pts) >= 4:
            fp_x = np.clip(((floor_pts[:, 0] - origin_x) / grid_resolution).astype(int), 0, gw - 1)
            fp_z = np.clip(((floor_pts[:, 2] - origin_z) / grid_resolution).astype(int), 0, gh - 1)
            xy = np.stack([fp_x, fp_z], axis=1)
            try:
                hull = ConvexHull(xy)
                hull_image = Image.new('L', (gw, gh), 0)
                draw = ImageDraw.Draw(hull_image)
                hull_points = [(int(xy[index, 0]), int(xy[index, 1])) for index in hull.vertices]
                draw.polygon(hull_points, fill=255)
                hull_mask = np.array(hull_image) > 0
                floor_mask = hull_mask & ~obstacle_grid
            except Exception as exc:
                logger.warning('[floor] convex hull fallback failed: %s', exc)

    floor_area_m2 = float(floor_mask.sum()) * (grid_resolution ** 2)
    logger.info('[floor] floor_area=%.1f (world units^2)', floor_area_m2)

    height_map = np.zeros((gh, gw), dtype=np.float32)
    above_floor = y > (y_floor + 0.3)
    hx = np.clip(((x[above_floor] - origin_x) / grid_resolution).astype(int), 0, gw - 1)
    hz = np.clip(((z[above_floor] - origin_z) / grid_resolution).astype(int), 0, gh - 1)
    hy = y[above_floor]
    for index in range(len(hx)):
        if hy[index] > height_map[hz[index], hx[index]]:
            height_map[hz[index], hx[index]] = hy[index]
    height_map -= y_floor

    floor_mask_path = os.path.join(output_dir, 'floor_mask.png')
    obstacle_path = os.path.join(output_dir, 'obstacle_grid.png')
    height_map_path = os.path.join(output_dir, 'height_map.png')
    preview_path = os.path.join(output_dir, 'preview.jpg')

    Image.fromarray((floor_mask * 255).astype(np.uint8), 'L').save(floor_mask_path)
    Image.fromarray((obstacle_grid * 255).astype(np.uint8), 'L').save(obstacle_path)
    height_mm = np.clip(height_map * 1000, 0, 65535).astype(np.uint16)
    Image.fromarray(height_mm, 'I;16').save(height_map_path)

    preview = np.ones((gh, gw, 3), dtype=np.uint8) * 255
    preview[floor_mask] = [220, 220, 220]
    preview[obstacle_grid] = [60, 60, 60]
    Image.fromarray(preview).save(preview_path, quality=90)

    return {
        'floor_mask_path': floor_mask_path,
        'obstacle_path': obstacle_path,
        'height_map_path': height_map_path,
        'preview_path': preview_path,
        'floor_area_m2': floor_area_m2,
        'origin_x': origin_x,
        'origin_z': origin_z,
    }


def _save_point_cloud(world_points, world_conf, rgb_colours, conf_threshold, output_dir):
    import trimesh

    pts = world_points.transpose(0, 2, 3, 1).reshape(-1, 3)
    conf = world_conf.reshape(-1)
    rgb = rgb_colours.reshape(-1, 3)

    mask = conf > conf_threshold
    pts = pts[mask]
    rgb = rgb[mask]
    rgba = np.concatenate([rgb, np.full((len(rgb), 1), 255, dtype=np.uint8)], axis=1)

    cloud = trimesh.PointCloud(vertices=pts, colors=rgba)
    ply_path = os.path.join(output_dir, 'point_cloud.ply')
    cloud.export(ply_path)

    cloud_web = trimesh.PointCloud(vertices=pts[::10], colors=rgba[::10])
    web_path = os.path.join(output_dir, 'point_cloud_web.ply')
    cloud_web.export(web_path)

    return ply_path, web_path


def _extract_frames(video_path, output_dir, fps=10):
    import subprocess

    subprocess.run(
        ['ffmpeg', '-i', video_path, '-vf', f'fps={fps}', '-q:v', '2', os.path.join(output_dir, '%06d.jpg')],
        check=True,
        capture_output=True,
    )
