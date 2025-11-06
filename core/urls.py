# core/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

# ---------- HTML VIEWS (templates) ----------
from core.views import (
    # auth + dashboards
    SimpleLoginView,
    instant_logout,
    signup_patient, signup_physician,
    dashboard_router,
    patient_dashboard, patient_profile_edit, record_create, record_edit,
    physician_dashboard, physician_patient_detail,
    regenerate_connect_code,

    # Calendar & legacy messaging HTML pages
    CalendarView, my_appointments,
    chat_inbox, chat_new,
    chat_start_with_user, chat_start_or_open, chat_thread, chat_send,
    chat_fetch_since, chat_room, messages_json,
    add_availability_window, create_appointment,
)

# ---------- Health ----------
from core.api.views_health import health

# ---------- Auth API ----------
from core.api.auth_views import csrf as csrf_view
from core.api.auth_views import (
    LoginView, LogoutView, MeView,
    PhysicianRegisterView, PatientRegisterView, PhysicianLookupByCodeView,
)

# ---------- Flexible availability / booking / calendar API ----------
from core.api.views_flex import (
    AvailableSlotsView,          # day helper for available start times
    FlexAppointmentCreateView,   # patient booking (start + duration)
    CalendarEventsView,          # events feed for FullCalendar
    PhysicianSlotsView,          # POST/GET raw availability windows
    MyAppointmentsView,          # JSON for React "Appointments" page
)

# ---------- DRF ViewSets (resources/legacy) ----------
# NOTE: WeeklyWindowViewSet & DateOverrideViewSet are aliases to
# PhysicianWeeklyAvailabilityViewSet and PhysicianDateOverrideViewSet
# inside core.api.views for backwards-compat with existing imports.
from core.api.views import (
    PhysicianProfileViewSet,
    PatientProfileViewSet,
    HealthRecordViewSet,
    AvailabilitySlotViewSet,
    AppointmentViewSet,
    WeeklyWindowViewSet,
    DateOverrideViewSet,
    TimeOffViewSet,
    FlexAppointmentViewSet,
    ConversationViewSet,
    MessageViewSet,
)

# ----------------------------
# DRF Router
# ----------------------------
router = DefaultRouter()

# Profiles & records
router.register(r"physician-profiles", PhysicianProfileViewSet, basename="physician-profile")
router.register(r"patient-profiles",   PatientProfileViewSet,   basename="patient-profile")
router.register(r"health-records",     HealthRecordViewSet,     basename="health-record")

# Legacy availability & appointments (kept for admin/backfill)
router.register(r"availability-slots", AvailabilitySlotViewSet, basename="availability-slot")
router.register(r"appointments",       AppointmentViewSet,      basename="appointment")

# New availability system objects
router.register(r"weekly-windows", WeeklyWindowViewSet, basename="weekly-window")
router.register(r"date-overrides", DateOverrideViewSet, basename="date-override")
router.register(r"time-off",       TimeOffViewSet,      basename="timeoff")

# Flexible appointments CRUD
router.register(r"flex-appointments", FlexAppointmentViewSet, basename="flex-appointment")

# Independent chat (JSON)
router.register(r"conversations", ConversationViewSet, basename="conversation")
router.register(r"messages",      MessageViewSet,      basename="message")


# ----------------------------
# URL Patterns
# ----------------------------
urlpatterns = [
    # ---------- HTML (auth + dashboards + pages) ----------
    path("login/",  SimpleLoginView.as_view(), name="login"),
    path("logout/", instant_logout,            name="logout"),
    path("signup/patient/",   signup_patient,   name="signup_patient"),
    path("signup/physician/", signup_physician, name="signup_physician"),

    path("",                         dashboard_router,        name="dashboard_router"),
    path("patient/",                 patient_dashboard,       name="patient_dashboard"),
    path("patient/profile/",         patient_profile_edit,    name="patient_profile_edit"),
    path("patient/records/new/",     record_create,           name="record_create"),
    path("patient/records/<int:pk>/edit/", record_edit,       name="record_edit"),

    path("physician/",                                physician_dashboard,        name="physician_dashboard"),
    path("physician/patient/<int:patient_id>/",       physician_patient_detail,   name="physician_patient_detail"),
    path("physician/connect-code/regenerate/",        regenerate_connect_code,    name="regenerate_connect_code"),

    # Calendar + legacy appointment HTML
    path("calendar/",      CalendarView.as_view(), name="calendar"),
    path("appointments/",  my_appointments,        name="my_appointments"),

    # Messaging HTML
    path("messages/",                        chat_inbox,            name="chat_inbox"),
    path("messages/new/",                    chat_new,              name="chat_new"),
    path("messages/start/u/<uuid:peer_id>/", chat_start_with_user,  name="chat_start_with_user"),
    path("messages/start/p/<uuid:patient_id>/v/<uuid:physician_id>/",
         chat_start_or_open, name="chat_start_or_open"),
    path("messages/c/<uuid:pk>/",            chat_thread,           name="chat_thread"),
    path("messages/c/<uuid:pk>/send/",       chat_send,             name="chat_send"),
    path("messages/api/c/<uuid:pk>/since/<str:ts>/",
         chat_fetch_since, name="chat_fetch_since"),
    path("chat/<uuid:peer_id>/",             chat_room,             name="chat-room"),
    path("api/chat/<uuid:conversation_id>/messages/", messages_json, name="messages-json"),

    # ---------- API: health ----------
    path("api/health/", health, name="api_health"),

    # ---------- API: auth ----------
    path("api/auth/csrf/",   csrf_view,            name="api_csrf"),
    path("api/auth/login/",  LoginView.as_view(),  name="api_login"),
    path("api/auth/logout/", LogoutView.as_view(), name="api_logout"),
    path("api/auth/me/",     MeView.as_view(),     name="api_me"),

    # Registration + physician lookup
    path("api/auth/register/physician/", PhysicianRegisterView.as_view(),  name="api_register_physician"),
    path("api/auth/register/patient/",   PatientRegisterView.as_view(),    name="api_register_patient"),
    path("api/physicians/lookup/",       PhysicianLookupByCodeView.as_view(), name="api_physician_lookup"),

    # ---------- API: flexible booking / calendar ----------
    # Day helper + booking
    path("api/clinic/slots/",             AvailableSlotsView.as_view(),        name="available-slots"),
    path("api/clinic/flex-appointments/", FlexAppointmentCreateView.as_view(), name="flex-appointment-create"),

    # Physician-scoped availability + FullCalendar event feed
    path("api/physicians/<uuid:physician_id>/slots/",        PhysicianSlotsView.as_view(), name="physician-slots"),
    path("api/physicians/<uuid:physician_id>/slots/events/", CalendarEventsView.as_view(), name="physician-slots-events"),

    # Appointments JSON for React page
    path("api/appointments/mine/", MyAppointmentsView.as_view(), name="appointments-mine"),

    # ---------- API: legacy helpers (kept) ----------
    path("api/physicians/<uuid:physician_id>/availability/", add_availability_window, name="availability-add"),
    path("api/appointments/create/", create_appointment, name="appointment-create"),

    # ---------- DRF Router mount ----------
    path("api/", include(router.urls)),
]
