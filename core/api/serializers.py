# core/api/serializers.py
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.models import PatientProfile, FlexAppointment
from core.utils.availability import get_available_slots

User = get_user_model()


# ----------------------------
# Existing: patient serializer
# ----------------------------
class PatientSerializer(serializers.ModelSerializer):
    public_id = serializers.UUIDField(read_only=True)
    physician_name = serializers.CharField(source="physician.full_name", read_only=True)

    class Meta:
        model = PatientProfile
        fields = [
            "public_id",
            "full_name",
            "date_of_birth",
            "phone",
            "address",
            "height_cm",
            "weight_kg",
            "physician_name",
        ]
        read_only_fields = ("public_id", "physician_name")

    def validate_height_cm(self, v):
        if v is not None and v < 0:
            raise serializers.ValidationError("height_cm must be ≥ 0.")
        return v

    def validate_weight_kg(self, v):
        if v is not None and v < 0:
            raise serializers.ValidationError("weight_kg must be ≥ 0.")
        return v


# ------------------------------------------------
# NEW: helpers for the dynamic availability/booking
# ------------------------------------------------
class SlotQuerySerializer(serializers.Serializer):
    """Query params for /api/clinic/slots/"""
    physician_id = serializers.UUIDField()
    date = serializers.DateField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=240, default=30)


class FlexAppointmentCreateSerializer(serializers.ModelSerializer):
    """
    Create a flexible appointment by start + duration.
    - duration_minutes is WRITE-ONLY (not a DB field)
    - end is computed; patient is taken from request.user
    """
    physician = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    start = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=240, write_only=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = FlexAppointment
        # duration_minutes is NOT a model field (write-only input)
        fields = ["id", "physician", "start", "duration_minutes", "notes", "end", "status"]
        read_only_fields = ["id", "end", "status"]

    def validate(self, attrs):
        start = attrs.get("start")
        duration = attrs.get("duration_minutes")
        physician = attrs.get("physician")

        tz = timezone.get_current_timezone()
        # normalize start to aware local
        if timezone.is_naive(start):
            start = timezone.make_aware(start, tz)
        else:
            start = start.astimezone(tz)

        end = start + timedelta(minutes=duration)
        if end <= timezone.now():
            raise serializers.ValidationError("Appointment end must be in the future.")

        # Check requested start is one of the currently available starts
        available_starts = get_available_slots(physician, start.date(), duration)
        start_norm = start.replace(second=0, microsecond=0)
        if start_norm not in [s.replace(second=0, microsecond=0) for s in available_starts]:
            raise serializers.ValidationError("Selected time is not available.")

        attrs["start"] = start
        # stash computed end for create()
        attrs["_computed_end"] = end
        return attrs

    def create(self, validated_data):
        validated_data.pop("duration_minutes", None)          # not a model field
        end = validated_data.pop("_computed_end", None)

        # set patient from request
        req = self.context.get("request")
        if not req or not req.user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")
        validated_data["patient"] = req.user
        validated_data["end"] = end

        return FlexAppointment.objects.create(**validated_data)


class FlexAppointmentReadSerializer(serializers.ModelSerializer):
    physician_name = serializers.CharField(source="physician.username", read_only=True)
    patient_name = serializers.CharField(source="patient.username", read_only=True)

    class Meta:
        model = FlexAppointment
        fields = [
            "id", "physician", "physician_name",
            "patient", "patient_name",
            "start", "end", "status", "notes",
        ]
        read_only_fields = fields
