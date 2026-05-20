from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView

from .forms import JobSiteForm
from .models import JobSite


class SiteListView(LoginRequiredMixin, ListView):
    model = JobSite
    template_name = 'sites/list.html'
    context_object_name = 'sites'

    def get_queryset(self):
        return JobSite.objects.filter(owner=self.request.user).prefetch_related('scans')


class SiteDetailView(LoginRequiredMixin, DetailView):
    model = JobSite
    template_name = 'sites/detail.html'
    context_object_name = 'site'

    def get_queryset(self):
        return JobSite.objects.filter(owner=self.request.user)


class SiteCreateView(LoginRequiredMixin, CreateView):
    model = JobSite
    form_class = JobSiteForm
    template_name = 'sites/create.html'
    success_url = reverse_lazy('sites:list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.conf import settings

        context['GOOGLE_MAPS_API_KEY'] = settings.GOOGLE_MAPS_API_KEY
        return context

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)
