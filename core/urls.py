# core/urls.py
from django.urls import path, include
from . import views

urlpatterns = [
    # Calendar & slots
    path("calendar/", views.CalendarView.as_view(), name="calendar"),
    path("api/physicians/<uuid:physician_id>/slots/", views.physician_slots_json, name="physician-slots-json"),
    path("api/appointments/create/", views.create_appointment, name="appointment-create"),
    path("appointments/", views.my_appointments, name="my_appointments"),

    # Chat
    path("chat/<uuid:peer_id>/", views.chat_room, name="chat-room"),  # peer = the other user
    path("api/chat/<uuid:conversation_id>/messages/", views.messages_json, name="messages-json"),
    # (No separate /send/ route; POST to the messages endpoint above.)

    # Mount your existing DRF endpoints
    path("api/", include("core.api_urls")),
]
