from django.urls import path

from . import views

app_name = 'scans'

urlpatterns = [
    path('new/', views.ScanCreateView.as_view(), name='create'),
    path('<uuid:scan_pk>/', views.ScanDetailView.as_view(), name='detail'),
    path('<uuid:scan_pk>/status/', views.ScanStatusView.as_view(), name='status'),
    path('<uuid:scan_pk>/artifacts/', views.ScanArtifactsView.as_view(), name='artifacts'),
    path('<uuid:scan_pk>/retry/', views.ScanRetryView.as_view(), name='retry'),
]
