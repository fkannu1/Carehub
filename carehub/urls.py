# carehub/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    # OAuth2 (keep here if you use it)
    path("o/", include("oauth2_provider.urls", namespace="oauth2_provider")),

    # Everything else (HTML + API) lives in core.urls
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
