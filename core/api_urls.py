from django.urls import path
from core.api.views import PatientListView, PatientDetailView

urlpatterns = [
    path("patients/", PatientListView.as_view(), name="api_patient_list"),
    path("patients/<int:pk>/", PatientDetailView.as_view(), name="api_patient_detail"),
]
