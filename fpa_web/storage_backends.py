"""
Google Cloud Storage backend integration for Django.

Provides seamless file uploads/downloads from Google Cloud Storage.
Requires: pip install django-storages[google]
"""

from django.conf import settings
from django.core.files.storage import default_storage


def get_media_url(filename):
    """
    Get the full URL for a media file.
    
    Works with both local filesystem and Google Cloud Storage backends.
    
    Usage:
        from fpa_web.storage_backends import get_media_url
        url = get_media_url('scans/uuid-1234/output/pointcloud.ply')
    """
    if settings.DEBUG or 'sqlite' in settings.DATABASES['default']['ENGINE']:
        # Local development
        return f"{settings.MEDIA_URL}{filename}"
    else:
        # Google Cloud Storage
        return f"https://storage.googleapis.com/{settings.STORAGES['default']['OPTIONS']['bucket_name']}/{filename}"


def upload_to_gcs(file_obj, path):
    """
    Upload a file to Google Cloud Storage.
    
    Args:
        file_obj: File-like object or Django UploadedFile
        path: Target path in bucket (e.g., 'scans/uuid-1234/output/file.ply')
    
    Returns:
        The stored file path
    """
    return default_storage.save(path, file_obj)


def delete_from_gcs(path):
    """
    Delete a file from Google Cloud Storage.
    
    Args:
        path: Path in bucket to delete
    """
    if default_storage.exists(path):
        default_storage.delete(path)
