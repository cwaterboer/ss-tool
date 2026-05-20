import os
import uuid

from django.conf import settings
from django.db import models

from apps.sites.models import JobSite


class Scan(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        DONE = 'done', 'Done'
        FAILED = 'failed', 'Failed'

    class InputType(models.TextChoices):
        VIDEO = 'video', 'Video walkthrough'
        IMAGES = 'images', 'Image folder (zip)'

    class InferenceMode(models.TextChoices):
        DIRECT = 'direct', 'Direct Output (up to ~3000 frames, retail stores)'
        VO = 'vo', 'VO Mode (very long sequences >3000 frames)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(JobSite, on_delete=models.CASCADE, related_name='scans')
    name = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    input_type = models.CharField(max_length=10, choices=InputType.choices, default=InputType.VIDEO)
    celery_task_id = models.CharField(max_length=128, blank=True)
    error_message = models.TextField(blank=True)

    fps = models.IntegerField(default=10)
    mode = models.CharField(max_length=10, choices=InferenceMode.choices, default=InferenceMode.DIRECT)
    kv_window_size = models.IntegerField(default=64)
    keyframe_interval = models.IntegerField(default=1)
    conf_threshold = models.FloatField(default=1.5)

    input_dir = models.CharField(max_length=512, blank=True)
    floor_mask_path = models.CharField(max_length=512, blank=True)
    obstacle_path = models.CharField(max_length=512, blank=True)
    height_map_path = models.CharField(max_length=512, blank=True)
    point_cloud_path = models.CharField(max_length=512, blank=True)
    web_ply_path = models.CharField(max_length=512, blank=True)
    preview_path = models.CharField(max_length=512, blank=True)
    scene_manifest_path = models.CharField(max_length=512, blank=True)
    camera_path_path = models.CharField(max_length=512, blank=True)
    mesh_path = models.CharField(max_length=512, blank=True)

    floor_area_m2 = models.FloatField(null=True, blank=True)
    grid_resolution = models.FloatField(default=0.05)
    origin_x = models.FloatField(null=True, blank=True)
    origin_z = models.FloatField(null=True, blank=True)
    anchor_scale = models.FloatField(null=True, blank=True)
    frame_count = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.site.name})'

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
    def scene_manifest_url(self):
        return self._media_url(self.scene_manifest_path)

    @property
    def camera_path_url(self):
        return self._media_url(self.camera_path_path)

    @property
    def mesh_url(self):
        return self._media_url(self.mesh_path)

    @property
    def duration_seconds(self):
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
