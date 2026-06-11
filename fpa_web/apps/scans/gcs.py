import os
import logging

logger = logging.getLogger(__name__)

GCS_AVAILABLE = False
try:
    from google.cloud import storage as gcs
    _client = gcs.Client()
    GCS_AVAILABLE = True
except Exception:
    pass


def is_gcs_mode():
    from django.conf import settings
    return bool(os.environ.get('GCS_BUCKET_NAME'))


def download_folder_from_gcs(gcs_prefix, local_dir):
    from django.conf import settings
    os.makedirs(local_dir, exist_ok=True)
    bucket = _client.bucket(os.environ['GCS_BUCKET_NAME'])
    blobs  = list(bucket.list_blobs(prefix=gcs_prefix))
    count  = 0
    for blob in blobs:
        rel = blob.name[len(gcs_prefix):].lstrip('/')
        if not rel:
            continue
        dest = os.path.join(local_dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        blob.download_to_filename(dest)
        count += 1
    logger.info(f"Downloaded {count} files from {gcs_prefix} to {local_dir}")
    return count


def upload_folder_to_gcs(local_dir, gcs_prefix):
    from django.conf import settings
    uploaded = []
    for root, _, files in os.walk(local_dir):
        for fname in files:
            local_path = os.path.join(root, fname)
            rel        = os.path.relpath(local_path, local_dir)
            gcs_name   = f"{gcs_prefix}/{rel}"
            bucket     = _client.bucket(os.environ['GCS_BUCKET_NAME'])
            blob       = bucket.blob(gcs_name)
            blob.upload_from_filename(local_path)
            uploaded.append((local_path, gcs_name))
            logger.info(f"Uploaded {local_path} to {gcs_name}")
    return uploaded


def gcs_public_url(gcs_object_name):
    from django.conf import settings
    return f"https://storage.googleapis.com/{os.environ['GCS_BUCKET_NAME']}/{gcs_object_name}"
