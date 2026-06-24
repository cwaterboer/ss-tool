import json
import datetime

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.shortcuts import get_object_or_404

from apps.sites.models import JobSite
from .models import Scan
from .gcs import is_gcs_mode


@method_decorator(csrf_exempt, name='dispatch')
class SiteListAPIView(View):
    def get(self, request):
        sites = JobSite.objects.all().values('id', 'name', 'address')
        return JsonResponse({'sites': list(sites)})


@method_decorator(csrf_exempt, name='dispatch')
class ScanCreateAPIView(View):
    def post(self, request, site_id):
        site = get_object_or_404(JobSite, pk=site_id)
        body = json.loads(request.body)
        scan = Scan.objects.create(
            site=site,
            name=body.get('name', 'Mobile Capture'),
            frame_count=body.get('frame_count', 0),
            status=Scan.Status.PENDING,
        )
        return JsonResponse({
            'scan_id': str(scan.id),
            'site_id': str(site.id),
            'status': scan.status,
        })


@method_decorator(csrf_exempt, name='dispatch')
class SignedUrlAPIView(View):
    def get(self, request, site_id, scan_id):
        get_object_or_404(Scan, pk=scan_id, site__id=site_id)
        frame = int(request.GET.get('frame', 0))
        gcs_path = f"media/scans/{scan_id}/input/frame_{frame:05d}.jpg"

        if is_gcs_mode():
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(os.environ['GCS_BUCKET_NAME'])
            blob = bucket.blob(gcs_path)
            signed_url = blob.generate_signed_url(
                version='v4',
                expiration=datetime.timedelta(minutes=15),
                method='PUT',
                content_type='image/jpeg',
            )
        else:
            signed_url = f"http://localhost:8000/mock-upload/{gcs_path}"

        return JsonResponse({
            'signed_url': signed_url,
            'gcs_path': gcs_path,
        })


@method_decorator(csrf_exempt, name='dispatch')
class UploadCompleteAPIView(View):
    def post(self, request, site_id, scan_id):
        scan = get_object_or_404(Scan, pk=scan_id, site__id=site_id)
        body = json.loads(request.body)
        total_frames = body.get('total_frames', 0)
        scan.input_dir = f"media/scans/{scan_id}/input"
        scan.frame_count = total_frames
        scan.status = Scan.Status.PENDING
        scan.save(update_fields=['input_dir', 'frame_count', 'status'])

        from .tasks import run_scan
        run_scan.delay(str(scan.id))

        return JsonResponse({
            'status': 'processing',
            'scan_id': str(scan.id),
        })

@method_decorator(csrf_exempt, name='dispatch')
class ScanListAPIView(View):
    def get(self, request, site_id):
        site = get_object_or_404(JobSite, pk=site_id)
        scans = Scan.objects.filter(site=site).order_by('-created_at').values(
            'id', 'name', 'status', 'frame_count', 'created_at'
        )
        return JsonResponse({'scans': [
            {
                'id': str(s['id']),
                'name': s['name'],
                'status': s['status'],
                'frame_count': s['frame_count'],
                'created_at': s['created_at'].isoformat() if s['created_at'] else None,
            }
            for s in scans
        ]})


@method_decorator(csrf_exempt, name='dispatch')
class ScanDetailAPIView(View):
    def get(self, request, site_id, scan_id):
        scan = get_object_or_404(Scan, pk=scan_id, site__id=site_id)
        return JsonResponse({
            'id': str(scan.id),
            'name': scan.name,
            'status': scan.status,
            'frame_count': scan.frame_count,
            'floor_area': round(scan.floor_area_m2, 1) if scan.floor_area_m2 else None,
            'preview_url': scan.preview_url,
            'web_ply_url': scan.web_ply_url,
            'created_at': scan.created_at.isoformat() if scan.created_at else None,
        })