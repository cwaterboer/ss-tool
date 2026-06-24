from django.urls import path
from . import api_views
from .views import ScanStatusView

urlpatterns = [
    path('sites/', api_views.SiteListAPIView.as_view(), name='api-sites'),
    path('sites/<uuid:site_id>/scans/', api_views.ScanCreateAPIView.as_view(), name='api-scan-create'),
    path('sites/<uuid:site_id>/scans/<uuid:scan_id>/signed-url/', api_views.SignedUrlAPIView.as_view(), name='api-signed-url'),
    path('sites/<uuid:site_id>/scans/<uuid:scan_id>/upload-complete/', api_views.UploadCompleteAPIView.as_view(), name='api-upload-complete'),
    path('sites/<uuid:site_id>/scans/<uuid:scan_id>/status/', ScanStatusView.as_view(), name='api-status'),
]