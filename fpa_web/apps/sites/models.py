import uuid

from django.contrib.auth.models import User
from django.db import models


class JobSite(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sites')
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=512)
    place_id = models.CharField(max_length=255, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    store_type = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.address}'

    @property
    def scan_count(self):
        return self.scans.count()

    @property
    def latest_scan(self):
        return self.scans.order_by('-created_at').first()
