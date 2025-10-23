from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import (
    User,
    PatientProfile,
    PhysicianProfile,
    HealthRecord,
    AvailabilitySlot,
    Appointment,
    Conversation,
    Message,
)

# ----------------------------
# User (show role in admin)
# ----------------------------
@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_superuser", "date_joined", "last_login")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)

# ----------------------------
# Profiles & Records
# ----------------------------
@admin.register(PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "physician", "date_of_birth", "phone")
    search_fields = ("full_name", "user__username", "user__email", "physician__full_name")
    list_filter = ("physician",)

@admin.register(PhysicianProfile)
class PhysicianProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "specialization", "clinic_name", "connect_code")
    search_fields = ("full_name", "user__username", "user__email", "specialization", "clinic_name")

@admin.register(HealthRecord)
class HealthRecordAdmin(admin.ModelAdmin):
    list_display = ("patient", "created_at", "systolic_bp", "diastolic_bp", "sugar_fasting", "sugar_pp")
    list_filter = ("created_at",)
    search_fields = ("patient__full_name", "patient__user__username")

# ----------------------------
# Availability / Appointments
# ----------------------------
@admin.register(AvailabilitySlot)
class AvailabilitySlotAdmin(admin.ModelAdmin):
    list_display = ("physician", "start", "end", "is_booked")
    list_filter = ("physician", "is_booked")
    search_fields = ("physician__username", "physician__email")
    ordering = ("start",)

@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("physician", "patient", "status", "created_at", "slot")
    list_filter = ("status", "physician")
    search_fields = ("physician__username", "patient__username", "notes")

# ----------------------------
# Chat
# ----------------------------
@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("physician", "patient", "created_at")
    search_fields = ("physician__username", "patient__username")
    list_filter = ("created_at",)

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender", "created_at")
    search_fields = (
        "sender__username",
        "conversation__physician__username",
        "conversation__patient__username",
        "body",
    )
    list_filter = ("created_at",)
    ordering = ("created_at",)
