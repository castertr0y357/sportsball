from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('sw.js', TemplateView.as_view(
        template_name='sw.js',
        content_type='application/javascript'
    ), name='service_worker'),
    path('', include('core.urls')),
    path('users/', include('users.urls')),
    path('leagues/', include('leagues.urls')),
    path('stats/', include('stats.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
