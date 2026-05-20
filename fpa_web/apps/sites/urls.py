from django.urls import include, path

from . import views

app_name = 'sites'

urlpatterns = [
    path('', views.SiteListView.as_view(), name='list'),
    path('new/', views.SiteCreateView.as_view(), name='create'),
    path('<uuid:pk>/', views.SiteDetailView.as_view(), name='detail'),
    path('<uuid:pk>/scans/', include('apps.scans.urls', namespace='scans')),
]
