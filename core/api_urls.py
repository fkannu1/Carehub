# core/api_urls.py
from django.urls import path
from core.api.views import PatientListView, PatientDetailView
from core.api.views_flex import (
    AvailableSlotsView,
    FlexAppointmentCreateView,
    CalendarEventsView,
)

urlpatterns = [
    # Existing patient endpoints
    path("patients/", PatientListView.as_view(), name="api_patient_list"),
    path("patients/<uuid:public_id>/", PatientDetailView.as_view(), name="api_patient_detail"),

    # Flexible availability (variable durations) + booking
    path("clinic/slots/", AvailableSlotsView.as_view(), name="available-slots"),
    path("clinic/flex-appointments/", FlexAppointmentCreateView.as_view(), name="flex-appointment-create"),

    # Calendar events (flat list for JS calendars). Provide both with & without trailing slash.
    path("physicians/<uuid:physician_id>/slots", CalendarEventsView.as_view(), name="physician-slots-events"),
    path("physicians/<uuid:physician_id>/slots/", CalendarEventsView.as_view(), name="physician-slots-events-slash"),
]
