# Generated manually to match COPILOT_CONTEXT.md

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('sites', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Scan',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
                ('notes', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('done', 'Done'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('input_type', models.CharField(choices=[('video', 'Video walkthrough'), ('images', 'Image folder (zip)')], default='video', max_length=10)),
                ('celery_task_id', models.CharField(blank=True, max_length=128)),
                ('error_message', models.TextField(blank=True)),
                ('fps', models.IntegerField(default=10)),
                ('mode', models.CharField(choices=[('direct', 'Direct Output (up to ~3000 frames, retail stores)'), ('vo', 'VO Mode (very long sequences >3000 frames)')], default='direct', max_length=10)),
                ('kv_window_size', models.IntegerField(default=64)),
                ('keyframe_interval', models.IntegerField(default=1)),
                ('conf_threshold', models.FloatField(default=1.5)),
                ('input_dir', models.CharField(blank=True, max_length=512)),
                ('floor_mask_path', models.CharField(blank=True, max_length=512)),
                ('obstacle_path', models.CharField(blank=True, max_length=512)),
                ('height_map_path', models.CharField(blank=True, max_length=512)),
                ('point_cloud_path', models.CharField(blank=True, max_length=512)),
                ('web_ply_path', models.CharField(blank=True, max_length=512)),
                ('preview_path', models.CharField(blank=True, max_length=512)),
                ('floor_area_m2', models.FloatField(blank=True, null=True)),
                ('grid_resolution', models.FloatField(default=0.05)),
                ('origin_x', models.FloatField(blank=True, null=True)),
                ('origin_z', models.FloatField(blank=True, null=True)),
                ('anchor_scale', models.FloatField(blank=True, null=True)),
                ('frame_count', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scans', to='sites.jobsite')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
