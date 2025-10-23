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
# Users (show role)
# ----------------------------
@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username",
        "email",
        "role",
        "is_staff",
        "is_superuser",
        "date_joined",
        "last_login",
    )
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)


# ----------------------------
# Profiles & Health Records
# ----------------------------
@admin.register(PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "physician", "date_of_birth", "phone")
    search_fields = (
        "full_name",
        "user__username",
        "user__email",
        "physician__full_name",
        "physician__user__username",
    )
    list_filter = ("physician",)
    autocomplete_fields = ("user", "physician")

@admin.register(PhysicianProfile)
class PhysicianProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "specialization", "clinic_name", "connect_code")
    search_fields = (
        "full_name",
        "user__username",
        "user__email",
        "specialization",
        "clinic_name",
        "connect_code",
    )
    autocomplete_fields = ("user",)

@admin.register(HealthRecord)
class HealthRecordAdmin(admin.ModelAdmin):
    list_display = ("patient", "created_at", "systolic_bp", "diastolic_bp", "sugar_fasting", "sugar_pp")
    list_filter = ("created_at",)
    search_fields = ("patient__full_name", "patient__user__username")
    date_hierarchy = "created_at"
    autocomplete_fields = ("patient",)


# ----------------------------
# Availability & Appointments
# ----------------------------
@admin.register(AvailabilitySlot)
class AvailabilitySlotAdmin(admin.ModelAdmin):
    list_display = ("physician", "start", "end", "is_booked")
    list_filter = ("is_booked", "physician")
    search_fields = ("physician__username", "physician__email")
    ordering = ("start",)
    date_hierarchy = "start"
    autocomplete_fields = ("physician",)

@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "physician", "status", "slot_start", "slot_end", "created_at")
    list_filter = ("status", "physician", "created_at")
    search_fields = ("patient__username", "physician__username", "notes")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("patient", "physician", "slot")

    # Helpers to show slot times as columns
    def slot_start(self, obj):
        return obj.slot.start
    slot_start.short_description = "Start"

    def slot_end(self, obj):
        return obj.slot.end
    slot_end.short_description = "End"


# ----------------------------
# Chat
# ----------------------------
@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("patient", "physician", "created_at")
    search_fields = ("patient__username", "physician__username")
    list_filter = ("created_at",)
    autocomplete_fields = ("patient", "physician")
    date_hierarchy = "created_at"

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender", "created_at", "short_body")
    search_fields = (
        "sender__username",
        "conversation__physician__username",
        "conversation__patient__username",
        "body",
    )
    list_filter = ("created_at",)
    ordering = ("created_at",)
    autocomplete_fields = ("conversation", "sender")
    date_hierarchy = "created_at"

    def short_body(self, obj):
        return (obj.body or "")[:50]
    short_body.short_description = "Body"
