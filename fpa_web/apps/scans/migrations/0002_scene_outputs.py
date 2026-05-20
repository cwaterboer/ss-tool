from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('scans', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='scan',
            name='camera_path_path',
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name='scan',
            name='mesh_path',
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name='scan',
            name='scene_manifest_path',
            field=models.CharField(blank=True, max_length=512),
        ),
    ]