# carehub/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

from core.views import (
    SimpleLoginView,
    instant_logout,
    signup_patient, signup_physician,
    dashboard_router,
    patient_dashboard, patient_profile_edit, record_create, record_edit,
    physician_dashboard, physician_patient_detail,
    regenerate_connect_code,  # ✅ added import
)

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # Auth (HTML)
    path("login/", SimpleLoginView.as_view(), name="login"),
    path("logout/", instant_logout, name="logout"),
    path("signup/patient/", signup_patient, name="signup_patient"),
    path("signup/physician/", signup_physician, name="signup_physician"),

    # HTML dashboards
    path("", dashboard_router, name="dashboard_router"),
    path("patient/", patient_dashboard, name="patient_dashboard"),
    path("patient/profile/", patient_profile_edit, name="patient_profile_edit"),
    path("patient/records/new/", record_create, name="record_create"),
    path("patient/records/<int:pk>/edit/", record_edit, name="record_edit"),

    path("physician/", physician_dashboard, name="physician_dashboard"),
    path("physician/patient/<int:patient_id>/", physician_patient_detail, name="physician_patient_detail"),

    # ✅ new route for regenerating the connect code
    path("physician/connect-code/regenerate/", regenerate_connect_code, name="regenerate_connect_code"),

    # OAuth2
    path("o/", include("oauth2_provider.urls", namespace="oauth2_provider")),

    # REST API
    path("api/", include("core.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
