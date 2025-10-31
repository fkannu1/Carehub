# core/urls.py
from django.urls import path, include
from . import views

urlpatterns = [
    # ----------------------------
    # Calendar & appointments
    # ----------------------------
    path("calendar/", views.CalendarView.as_view(), name="calendar"),

    # Physician creates an ad-hoc free window
    path(
        "api/physicians/<uuid:physician_id>/availability/",
        views.add_availability_window,
        name="availability-add",
    ),

    # Unified booking endpoint (legacy fixed-slot + new flex)
    path(
        "api/appointments/create/",
        views.create_appointment,
        name="appointment-create",
    ),

    # List appointments
    path("appointments/", views.my_appointments, name="my_appointments"),

    # ----------------------------
    # Messaging (independent of appointments)
    # ----------------------------
    path("messages/", views.chat_inbox, name="chat_inbox"),
    path("messages/new/", views.chat_new, name="chat_new"),
    path(
        "messages/start/u/<uuid:peer_id>/",
        views.chat_start_with_user,
        name="chat_start_with_user",
    ),

    # Start/open using explicit patient/physician ids (kept)
    path(
        "messages/start/p/<uuid:patient_id>/v/<uuid:physician_id>/",
        views.chat_start_or_open,
        name="chat_start_or_open",
    ),

    # Thread + send + poll
    path("messages/c/<uuid:pk>/", views.chat_thread, name="chat_thread"),
    path("messages/c/<uuid:pk>/send/", views.chat_send, name="chat_send"),
    path(
        "messages/api/c/<uuid:pk>/since/<str:ts>/",
        views.chat_fetch_since,
        name="chat_fetch_since",
    ),

    # ----------------------------
    # Legacy chat (kept)
    # ----------------------------
    path("chat/<uuid:peer_id>/", views.chat_room, name="chat-room"),
    path(
        "api/chat/<uuid:conversation_id>/messages/",
        views.messages_json,
        name="messages-json",
    ),

    # ----------------------------
    # DRF API
    # ----------------------------
    path("api/", include("core.api_urls")),
]
