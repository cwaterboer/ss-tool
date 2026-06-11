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
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


@shared_task(bind=True, max_retries=0, time_limit=7200)
def run_scan(self, scan_id: str):
    from apps.scans.models import Scan

    scan = Scan.objects.get(id=scan_id)
    scan.status = Scan.Status.PROCESSING
    scan.started_at = timezone.now()
    scan.celery_task_id = self.request.id
    scan.save(update_fields=["status", "started_at", "celery_task_id"])
    logger.info("[scan:%s] started", scan_id)

    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("[scan:%s] device=%s", scan_id, device)

        from lingbot_map.utils.load_fn import load_and_preprocess_images
        from apps.scans.gcs import is_gcs_mode, download_folder_from_gcs
        import tempfile

        # Download frames from GCS if needed
        if is_gcs_mode() and scan.input_dir and not scan.input_dir.startswith("/"):
            _tmpdir = tempfile.mkdtemp()
            download_folder_from_gcs(scan.input_dir, _tmpdir)
            local_input = _tmpdir
        else:
            local_input = scan.input_path

        paths = _collect_image_paths(local_input)
        if not paths:
            raise ValueError(f"No images found in {local_input} (input_dir={scan.input_dir})")
        if len(paths) < 20:
            raise ValueError(
                f"Only {len(paths)} frames found. Need at least 20 frames."
            )

        scan.frame_count = len(paths)
        scan.save(update_fields=["frame_count"])
        logger.info("[scan:%s] %s frames", scan_id, len(paths))

        images = load_and_preprocess_images(
            paths, mode="crop", image_size=518, patch_size=14
        ).to(device)
        rgb_for_colour = _load_rgb_for_colour(paths, target_h=378, target_w=518)

        if scan.mode == "vo":
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
            use_sdpa=True,
            enable_point=False,
        )

        ckpt_path = settings.LINGBOT_CHECKPOINT_PATH
        logger.info("[scan:%s] loading checkpoint: %s", scan_id, ckpt_path)
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=True)
        model.load_state_dict(ckpt.get("model", ckpt), strict=False)
        model = model.to(device).eval()

        use_bf16 = torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 8
        dtype = torch.bfloat16 if use_bf16 else torch.float16
        amp_ctx = torch.amp.autocast("cuda", dtype=dtype) if torch.cuda.is_available() else contextlib.nullcontext()

        logger.info("[scan:%s] inference mode=%s kv_window=%s dtype=%s",
                    scan_id, scan.mode, scan.kv_window_size, dtype)
        t0 = time.time()

        with torch.no_grad(), amp_ctx:
            if scan.mode == "direct":
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

        logger.info("[scan:%s] inference done in %.1fs", scan_id, time.time() - t0)
        logger.info("[scan:%s] prediction keys: %s", scan_id, list(predictions.keys()))

        from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri

        extrinsic, intrinsic = pose_encoding_to_extri_intri(
            predictions["pose_enc"], images.shape[-2:]
        )
        extrinsic = extrinsic.cpu().float().numpy()
        intrinsic = intrinsic.cpu().float().numpy()

        # Squeeze batch dim if present
        if extrinsic.ndim == 4:
            extrinsic = extrinsic.squeeze(0)
        if intrinsic.ndim == 4:
            intrinsic = intrinsic.squeeze(0)

        depth_np   = predictions["depth"].squeeze(0).cpu().float().numpy()
        depth_conf = predictions["depth_conf"].squeeze(0).cpu().float().numpy()

        world_points, world_conf = _depth_to_world_points(
            depth_np, depth_conf, extrinsic, intrinsic
        )

        anchor_pts  = world_points[:3].reshape(-1, 3)
        anchor_conf = world_conf[:3].reshape(-1)
        anchor_f    = anchor_pts[anchor_conf > scan.conf_threshold]
        anchor_scale = float(np.mean(np.linalg.norm(anchor_f, axis=1))) if len(anchor_f) > 10 else 1.0
        logger.info("[scan:%s] anchor_scale=%.4f", scan_id, anchor_scale)

        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        from apps.scans.gcs import is_gcs_mode, upload_folder_to_gcs, gcs_public_url
        import tempfile as _tmpmod

        local_output = _tmpmod.mkdtemp()

        artifacts = _extract_floor_artifacts(
            world_points=world_points,
            world_conf=world_conf,
            conf_threshold=scan.conf_threshold,
            grid_resolution=scan.grid_resolution,
            output_dir=local_output,
        )

        ply_path, web_ply_path = _save_point_cloud(
            world_points=world_points,
            world_conf=world_conf,
            rgb_colours=rgb_for_colour,
            conf_threshold=scan.conf_threshold,
            output_dir=local_output,
        )

        # Upload outputs to GCS or keep local
        if is_gcs_mode():
            gcs_out = f"media/scans/{scan.id}/output"
            upload_folder_to_gcs(local_output, gcs_out)
            def out_url(fname):
                return gcs_public_url(f"{gcs_out}/{fname}")
            scan.floor_mask_path  = out_url("floor_mask.png")
            scan.obstacle_path    = out_url("obstacle_grid.png")
            scan.height_map_path  = out_url("height_map.png")
            scan.preview_path     = out_url("preview.jpg")
            scan.point_cloud_path = out_url("point_cloud.ply")
            scan.web_ply_path     = out_url("point_cloud_web.ply")
        else:
            scan.floor_mask_path  = artifacts["floor_mask_path"]
            scan.obstacle_path    = artifacts["obstacle_path"]
            scan.height_map_path  = artifacts["height_map_path"]
            scan.preview_path     = artifacts["preview_path"]
            scan.point_cloud_path = ply_path
            scan.web_ply_path     = web_ply_path

        scan.status        = Scan.Status.DONE
        scan.completed_at  = timezone.now()
        scan.floor_area_m2 = artifacts["floor_area_m2"]
        scan.origin_x      = artifacts["origin_x"]
        scan.origin_z      = artifacts["origin_z"]
        scan.anchor_scale  = anchor_scale
        scan.save(update_fields=[
            "status", "completed_at",
            "floor_mask_path", "obstacle_path", "height_map_path",
            "preview_path", "point_cloud_path", "web_ply_path",
            "floor_area_m2", "origin_x", "origin_z", "anchor_scale",
        ])
        logger.info(
            "[scan:%s] DONE floor_area=%.1f anchor_scale=%.4f duration=%.1fs frames=%d",
            scan_id, artifacts["floor_area_m2"], anchor_scale,
            time.time() - t0, scan.frame_count,
        )

    except Exception as exc:
        logger.exception("[scan:%s] FAILED: %s", scan_id, exc)
        scan.status        = Scan.Status.FAILED
        scan.error_message = str(exc)
        scan.completed_at  = timezone.now()
        scan.save(update_fields=["status", "error_message", "completed_at"])
        raise


def _depth_to_world_points(depth, depth_conf, extrinsic, intrinsic):
    """
    Project depth maps into 3D world-space points.
    depth:      (T, H, W, 1) or (T, 1, H, W)
    depth_conf: (T, H, W) or (T, 1, H, W)
    extrinsic:  (T, 3, 4) camera-to-world
    intrinsic:  (T, 3, 3)
    """
    # Fix depth layout: (T, H, W, 1) -> (T, 1, H, W)
    if depth.ndim == 4 and depth.shape[-1] == 1:
        depth = depth.transpose(0, 3, 1, 2)

    T, _, H, W = depth.shape

    # Fix depth_conf layout
    if depth_conf.ndim == 4 and depth_conf.shape[-1] == 1:
        depth_conf = depth_conf.squeeze(-1)
    if depth_conf.ndim == 4 and depth_conf.shape[1] == 1:
        depth_conf = depth_conf.squeeze(1)

    world_points = np.zeros((T, 3, H, W), dtype=np.float32)
    world_conf   = np.zeros((T, H, W),    dtype=np.float32)

    u  = np.arange(W, dtype=np.float32)
    v  = np.arange(H, dtype=np.float32)
    uu, vv = np.meshgrid(u, v)  # both (H, W)

    for t in range(T):
        d  = depth[t, 0]       # (H, W)
        K  = intrinsic[t]      # (3, 3)
        Rt = extrinsic[t]      # (3, 4)

        fx, fy = float(K[0, 0]), float(K[1, 1])
        cx, cy = float(K[0, 2]), float(K[1, 2])

        x_cam = (uu - cx) * d / (fx + 1e-8)
        y_cam = -((vv - cy) * d / (fy + 1e-8))
        z_cam = d

        pts_cam = np.stack([
            x_cam.reshape(-1),
            y_cam.reshape(-1),
            z_cam.reshape(-1),
        ], axis=0)  # (3, N)

        R     = Rt[:3, :3]
        t_vec = Rt[:3, 3:4]
        pts_world = R @ pts_cam + t_vec  # (3, N)

        world_points[t] = pts_world.reshape(3, H, W)
        world_conf[t]   = depth_conf[t] if depth_conf.shape[0] == T else depth_conf[0]

    return world_points, world_conf


def _collect_image_paths(folder: str) -> list:
    import glob
    paths = []
    for ext in ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"]:
        paths.extend(glob.glob(os.path.join(folder, "**", ext), recursive=True))
    return sorted(set(paths))


def _load_rgb_for_colour(paths: list, target_h: int = 378, target_w: int = 518) -> np.ndarray:
    from PIL import Image as PILImage
    frames = []
    for path in paths:
        image = PILImage.open(path).convert("RGB")
        w, h  = image.size
        scale = max(target_w / w, target_h / h)
        nw, nh = int(w * scale), int(h * scale)
        image  = image.resize((nw, nh), PILImage.BILINEAR)
        left   = (nw - target_w) // 2
        top    = (nh - target_h) // 2
        image  = image.crop((left, top, left + target_w, top + target_h))
        frames.append(np.array(image, dtype=np.uint8))
    return np.stack(frames, axis=0)


def _extract_floor_artifacts(world_points, world_conf, conf_threshold, grid_resolution, output_dir):
    from PIL import Image, ImageDraw
    from scipy.ndimage import binary_dilation, binary_fill_holes
    from scipy.spatial import ConvexHull

    pts  = world_points.transpose(0, 2, 3, 1).reshape(-1, 3)
    conf = world_conf.reshape(-1)
    pts  = pts[conf > conf_threshold]

    if len(pts) < 50:
        raise ValueError(
            f"Only {len(pts)} confident points (threshold={conf_threshold}). "
            "Walk the complete store perimeter. Minimum ~100 frames."
        )

    x, y, z   = pts[:, 0], pts[:, 1], pts[:, 2]
    y_floor   = float(np.percentile(y, 5))
    y_ceiling = float(np.percentile(y, 90))
    logger.info("[floor] y_floor=%.3f y_ceiling=%.3f", y_floor, y_ceiling)

    mid_y     = (y_floor + y_ceiling) * 0.5
    thickness = (y_ceiling - y_floor) * 0.15
    in_slice  = (y > mid_y - thickness) & (y < mid_y + thickness)
    sx, sz    = x[in_slice], z[in_slice]

    origin_x = float(x.min())
    origin_z = float(z.min())
    gw = int((x.max() - origin_x) / grid_resolution) + 1
    gh = int((z.max() - origin_z) / grid_resolution) + 1

    MAX_GRID = 4000
    if gw > MAX_GRID or gh > MAX_GRID:
        scale_factor   = MAX_GRID / max(gw, gh)
        grid_resolution = grid_resolution / scale_factor
        gw = int((x.max() - origin_x) / grid_resolution) + 1
        gh = int((z.max() - origin_z) / grid_resolution) + 1

    obstacle_grid = np.zeros((gh, gw), dtype=bool)
    xi = np.clip(((sx - origin_x) / grid_resolution).astype(int), 0, gw - 1)
    zi = np.clip(((sz - origin_z) / grid_resolution).astype(int), 0, gh - 1)
    obstacle_grid[zi, xi] = True
    obstacle_grid = binary_dilation(obstacle_grid, iterations=2)

    filled     = binary_fill_holes(obstacle_grid)
    floor_mask = filled & ~obstacle_grid

    if floor_mask.sum() == 0:
        logger.warning("[floor] binary_fill_holes empty; using convex hull fallback")
        floor_pts = pts[(y - y_floor) < (y_ceiling - y_floor) * 0.3]
        if len(floor_pts) >= 4:
            fp_x = np.clip(((floor_pts[:, 0] - origin_x) / grid_resolution).astype(int), 0, gw - 1)
            fp_z = np.clip(((floor_pts[:, 2] - origin_z) / grid_resolution).astype(int), 0, gh - 1)
            xy   = np.stack([fp_x, fp_z], axis=1)
            try:
                hull       = ConvexHull(xy)
                hull_img   = Image.new("L", (gw, gh), 0)
                draw       = ImageDraw.Draw(hull_img)
                hull_pts   = [(int(xy[v, 0]), int(xy[v, 1])) for v in hull.vertices]
                draw.polygon(hull_pts, fill=255)
                hull_mask  = np.array(hull_img) > 0
                floor_mask = hull_mask & ~obstacle_grid
            except Exception as e:
                logger.warning("[floor] convex hull failed: %s", e)

    floor_area_m2 = float(floor_mask.sum()) * (grid_resolution ** 2)
    logger.info("[floor] floor_area=%.1f (world units^2)", floor_area_m2)

    height_map  = np.zeros((gh, gw), dtype=np.float32)
    above_floor = y > (y_floor + 0.3)
    hx = np.clip(((x[above_floor] - origin_x) / grid_resolution).astype(int), 0, gw - 1)
    hz = np.clip(((z[above_floor] - origin_z) / grid_resolution).astype(int), 0, gh - 1)
    hy = y[above_floor]
    for i in range(len(hx)):
        if hy[i] > height_map[hz[i], hx[i]]:
            height_map[hz[i], hx[i]] = hy[i]
    height_map -= y_floor

    floor_mask_path = os.path.join(output_dir, "floor_mask.png")
    obstacle_path   = os.path.join(output_dir, "obstacle_grid.png")
    height_map_path = os.path.join(output_dir, "height_map.png")
    preview_path    = os.path.join(output_dir, "preview.jpg")

    Image.fromarray((floor_mask    * 255).astype(np.uint8), "L").save(floor_mask_path)
    Image.fromarray((obstacle_grid * 255).astype(np.uint8), "L").save(obstacle_path)
    height_mm = np.clip(height_map * 1000, 0, 65535).astype(np.uint16)
    Image.fromarray(height_mm, "I;16").save(height_map_path)

    preview = np.ones((gh, gw, 3), dtype=np.uint8) * 255
    preview[floor_mask]    = [220, 220, 220]
    preview[obstacle_grid] = [60,  60,  60]
    Image.fromarray(preview).save(preview_path, quality=90)

    return {
        "floor_mask_path": floor_mask_path,
        "obstacle_path":   obstacle_path,
        "height_map_path": height_map_path,
        "preview_path":    preview_path,
        "floor_area_m2":   floor_area_m2,
        "origin_x":        origin_x,
        "origin_z":        origin_z,
    }


def _save_point_cloud(world_points, world_conf, rgb_colours, conf_threshold, output_dir):
    import trimesh

    pts  = world_points.transpose(0, 2, 3, 1).reshape(-1, 3)
    conf = world_conf.reshape(-1)
    n    = len(pts)
    rgb  = rgb_colours.reshape(-1, 3)[:n]

    mask = conf > conf_threshold
    pts  = pts[mask]
    rgb  = rgb[mask]
    rgba = np.concatenate([rgb, np.full((len(rgb), 1), 255, dtype=np.uint8)], axis=1)

    cloud    = trimesh.PointCloud(vertices=pts, colors=rgba)
    ply_path = os.path.join(output_dir, "point_cloud.ply")
    cloud.export(ply_path)

    cloud_web = trimesh.PointCloud(vertices=pts[::10], colors=rgba[::10])
    web_path  = os.path.join(output_dir, "point_cloud_web.ply")
    cloud_web.export(web_path)

    return ply_path, web_path


def _extract_frames(video_path, output_dir, fps=10):
    import subprocess
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-vf", f"fps={fps}", "-q:v", "2",
         os.path.join(output_dir, "%06d.jpg")],
        check=True, capture_output=True,
    )
