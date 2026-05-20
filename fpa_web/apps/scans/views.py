import io
import os
import zipfile

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.urls import reverse
from django.views.generic import CreateView, DetailView

from apps.sites.models import JobSite

from .forms import ScanCreateForm
from .models import Scan


class ScanCreateView(LoginRequiredMixin, CreateView):
    model = Scan
    form_class = ScanCreateForm
    template_name = 'scans/create.html'

    def get_site(self):
        return get_object_or_404(JobSite, pk=self.kwargs['pk'], owner=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.get_site()
        return context

    def form_valid(self, form):
        site = self.get_site()
        scan = form.save(commit=False)
        scan.site = site

        upload = self.request.FILES.get('upload')
        if not upload:
            form.add_error(None, 'Please upload a video (.mp4) or image archive (.zip).')
            return self.form_invalid(form)

        input_dir = scan.input_path
        os.makedirs(input_dir, exist_ok=True)

        if scan.input_type == Scan.InputType.VIDEO:
            video_path = os.path.join(input_dir, 'input.mp4')
            with open(video_path, 'wb') as handle:
                for chunk in upload.chunks():
                    handle.write(chunk)
            from .tasks import _extract_frames
            _extract_frames(video_path, input_dir, fps=scan.fps)
        else:
            archive = zipfile.ZipFile(io.BytesIO(upload.read()))
            archive.extractall(input_dir)

        scan.input_dir = input_dir
        scan.save()

        from .tasks import run_scan
        run_scan.delay(str(scan.id))

        return redirect('sites:scans:detail', pk=site.pk, scan_pk=scan.pk)


class ScanDetailView(LoginRequiredMixin, DetailView):
    model = Scan
    template_name = 'scans/detail.html'
    context_object_name = 'scan'
    pk_url_kwarg = 'scan_pk'

    def get_queryset(self):
        return Scan.objects.filter(site__owner=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['site'] = self.object.site
        context['artifacts_url'] = reverse('sites:scans:artifacts', kwargs={'pk': self.object.site.pk, 'scan_pk': self.object.pk})
        return context


class ScanStatusView(LoginRequiredMixin, View):
    def get(self, request, **kwargs):
        scan = get_object_or_404(Scan, pk=kwargs['scan_pk'], site__owner=request.user)
        return JsonResponse(
            {
                'status': scan.status,
                'preview_url': scan.preview_url,
                'web_ply_url': scan.web_ply_url,
                'floor_area': round(scan.floor_area_m2, 1) if scan.floor_area_m2 else None,
                'frame_count': scan.frame_count,
                'duration': round(scan.duration_seconds) if scan.duration_seconds else None,
                'anchor_scale': scan.anchor_scale,
                'error': scan.error_message or None,
                'manifest_url': scan.scene_manifest_url,
                'camera_path_url': scan.camera_path_url,
            }
        )


class ScanArtifactsView(LoginRequiredMixin, View):
    def get(self, request, **kwargs):
        scan = get_object_or_404(Scan, pk=kwargs['scan_pk'], site__owner=request.user)
        manifest = {}
        if scan.scene_manifest_path and os.path.exists(scan.scene_manifest_path):
            with open(scan.scene_manifest_path, 'r', encoding='utf-8') as handle:
                manifest = json.load(handle)

        manifest.setdefault('scan_id', str(scan.id))
        manifest.setdefault('site_id', str(scan.site_id))
        manifest.setdefault('scan_name', scan.name)
        manifest.setdefault('status', scan.status)
        manifest.setdefault('frame_count', scan.frame_count)
        manifest.setdefault('floor_area_m2', scan.floor_area_m2)
        manifest.setdefault('anchor_scale', scan.anchor_scale)
        manifest.setdefault('grid_resolution', scan.grid_resolution)
        manifest['urls'] = {
            'preview': scan.preview_url,
            'floor_mask': scan._media_url(scan.floor_mask_path),
            'obstacle_grid': scan._media_url(scan.obstacle_path),
            'height_map': scan._media_url(scan.height_map_path),
            'point_cloud': scan.point_cloud_url,
            'web_point_cloud': scan.web_ply_url,
            'camera_path': scan.camera_path_url,
            'manifest': scan.scene_manifest_url,
            'mesh': scan.mesh_url,
        }
        return JsonResponse(manifest)


class ScanRetryView(LoginRequiredMixin, View):
    def post(self, request, **kwargs):
        scan = get_object_or_404(
            Scan,
            pk=kwargs['scan_pk'],
            site__owner=request.user,
            status=Scan.Status.FAILED,
        )
        scan.status = Scan.Status.PENDING
        scan.error_message = ''
        scan.save(update_fields=['status', 'error_message'])
        from .tasks import run_scan
        run_scan.delay(str(scan.id))
        return redirect('sites:scans:detail', pk=scan.site.pk, scan_pk=scan.pk)
