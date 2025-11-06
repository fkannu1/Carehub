from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.models import (
    PatientProfile,
    PhysicianProfile,
    HealthRecord,
    AvailabilitySlot,
    Appointment,
    PhysicianWeeklyAvailability,
    PhysicianDateOverride,
    TimeOff,
    FlexAppointment,
    Conversation,
    Message,
)

# If you moved this helper, update import accordingly
from core.utils.availability import get_available_slots

User = get_user_model()


# ----------------------------
# Small user serializer (auth)
# ----------------------------
class UserBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "role"]


# ----------------------------
# Profiles & records
# ----------------------------
class PhysicianProfileSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source="user", write_only=True, required=False
    )

    class Meta:
        model = PhysicianProfile
        fields = [
            "public_id",
            "user",
            "user_id",
            "full_name",
            "specialization",
            "clinic_name",
            "connect_code",
        ]
    # connect_code is auto-generated in model.save(), so expose as read-only
    read_only_fields = ["public_id", "connect_code"]


class PatientProfileSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source="user", write_only=True, required=False
    )
    physician = serializers.PrimaryKeyRelatedField(
        queryset=PhysicianProfile.objects.all(), allow_null=True, required=False
    )
    physician_name = serializers.CharField(source="physician.full_name", read_only=True)
    # Optional: let clients set physician by code when creating/updating profile
    physician_connect_code = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = PatientProfile
        fields = [
            "public_id",
            "user",
            "user_id",
            "full_name",
            "date_of_birth",
            "phone",
            "address",
            "height_cm",
            "weight_kg",
            "physician",
            "physician_name",
            "physician_connect_code",
        ]
        read_only_fields = ["public_id", "physician_name"]

    def validate_height_cm(self, v):
        if v is not None and v < 0:
            raise serializers.ValidationError("height_cm must be ≥ 0.")
        return v

    def validate_weight_kg(self, v):
        if v is not None and v < 0:
            raise serializers.ValidationError("weight_kg must be ≥ 0.")
        return v

    def create(self, validated_data):
        code = validated_data.pop("physician_connect_code", "").strip().upper() if validated_data.get("physician_connect_code") is not None else ""
        if code and not validated_data.get("physician"):
            doc = PhysicianProfile.objects.filter(connect_code=code).first()
            if not doc:
                raise serializers.ValidationError({"physician_connect_code": "Invalid physician code."})
            validated_data["physician"] = doc
        return super().create(validated_data)

    def update(self, instance, validated_data):
        code = validated_data.pop("physician_connect_code", None)
        if code is not None:
            code = code.strip().upper()
            if code == "":
                instance.physician = None
            else:
                doc = PhysicianProfile.objects.filter(connect_code=code).first()
                if not doc:
                    raise serializers.ValidationError({"physician_connect_code": "Invalid physician code."})
                instance.physician = doc
        return super().update(instance, validated_data)


class HealthRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = HealthRecord
        fields = [
            "id",
            "patient",
            "created_at",
            "systolic_bp",
            "diastolic_bp",
            "sugar_fasting",
            "sugar_pp",
            "notes",
            "attachment",
        ]
        read_only_fields = ["id", "created_at"]
        # 👇 make patient optional so patients don't have to send it
        extra_kwargs = {
            "patient": {"required": False}
        }


# ----------------------------
# Legacy availability & appts
# ----------------------------
class AvailabilitySlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvailabilitySlot
        fields = ["id", "physician", "start", "end", "is_booked", "booked_by_flex"]
        read_only_fields = ["id", "is_booked", "booked_by_flex"]


class AppointmentReadSerializer(serializers.ModelSerializer):
    """
    Read-friendly serializer for legacy Appointment that exposes the
    slot window and a human physician name so the Dashboard renders properly.
    """
    start = serializers.DateTimeField(source="slot.start", read_only=True)
    end = serializers.DateTimeField(source="slot.end", read_only=True)
    physician_name = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "start",
            "end",
            "physician",
            "physician_name",
            "patient",
            "status",
            "notes",
        ]
        read_only_fields = fields

    def get_physician_name(self, obj):
        u = getattr(obj, "physician", None)
        if not u:
            return None
        name = u.username or f"{u.first_name} {u.last_name}".strip()
        return name or str(u.id)


class AppointmentSerializer(serializers.ModelSerializer):
    """
    Kept for write paths if you still POST/PUT legacy Appointment.
    """
    class Meta:
        model = Appointment
        fields = ["id", "slot", "physician", "patient", "status", "created_at", "notes"]
        read_only_fields = ["id", "created_at"]


# ----------------------------
# New availability system
# ----------------------------
class WeeklyWindowSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhysicianWeeklyAvailability
        fields = [
            "id",
            "physician",
            "weekday",
            "start_time",
            "end_time",
            "is_active",
            "snap_minutes",
        ]
        read_only_fields = ["id"]


class DateOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhysicianDateOverride
        fields = [
            "id",
            "physician",
            "date",
            "is_closed",
            "start_time",
            "end_time",
        ]
        read_only_fields = ["id"]


class TimeOffSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimeOff
        fields = ["id", "physician", "start", "end", "reason"]
        read_only_fields = ["id"]


# ------------------------------------------------
# Flexible appointment (start + duration) helpers
# ------------------------------------------------
class SlotQuerySerializer(serializers.Serializer):
    """
    Query params for /api/clinic/slots/ to generate available starts
    for a physician on a given date and requested duration.
    """
    physician_id = serializers.UUIDField()
    date = serializers.DateField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=240, default=30)


class FlexAppointmentCreateSerializer(serializers.ModelSerializer):
    """
    Create a flexible appointment by start + duration.
    """
    physician = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    start = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=240, write_only=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = FlexAppointment
        fields = ["id", "physician", "start", "duration_minutes", "notes", "end", "status"]
        read_only_fields = ["id", "end", "status"]

    def _to_local_minute(self, dt):
        """Return dt as an aware datetime in current TZ, truncated to minute."""
        tz = timezone.get_current_timezone()
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, tz)
        else:
            dt = dt.astimezone(tz)
        return dt.replace(second=0, microsecond=0)

    def validate(self, attrs):
        start = attrs.get("start")
        duration = attrs.get("duration_minutes")
        physician = attrs.get("physician")

        if not start or not duration or not physician:
            return attrs

        tz = timezone.get_current_timezone()
        start_local = self._to_local_minute(start)
        end_local = start_local + timedelta(minutes=duration)

        if end_local <= timezone.now():
            raise serializers.ValidationError("Appointment end must be in the future.")

        available_starts = get_available_slots(physician, start_local.date(), duration)
        
        if not available_starts:
            raise serializers.ValidationError({
                "non_field_errors": [
                    "No available slots for this physician on the selected date."
                ]
            })
        
        normalized_available = set()
        for slot_dt in available_starts:
            if timezone.is_naive(slot_dt):
                slot_dt = timezone.make_aware(slot_dt, tz)
            else:
                slot_dt = slot_dt.astimezone(tz)
            
            slot_normalized = slot_dt.replace(second=0, microsecond=0)
            minute_key = int(slot_normalized.timestamp() // 60)
            normalized_available.add(minute_key)
        
        requested_minute_key = int(start_local.timestamp() // 60)
        
        if requested_minute_key not in normalized_available:
            first_available = available_starts[0]
            if timezone.is_naive(first_available):
                first_available = timezone.make_aware(first_available, tz)
            else:
                first_available = first_available.astimezone(tz)
            
            first_str = first_available.strftime('%I:%M %p on %b %d, %Y')
            requested_str = start_local.strftime('%I:%M %p on %b %d, %Y')
            
            raise serializers.ValidationError({
                "non_field_errors": [
                    f"Selected time is not available. "
                    f"You requested {requested_str}, but the first available slot is at {first_str}. "
                    f"Please refresh the calendar."
                ]
            })

        attrs["start"] = start_local
        attrs["_computed_end"] = end_local
        return attrs

    def create(self, validated_data):
        validated_data.pop("duration_minutes", None)
        end = validated_data.pop("_computed_end", None)

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


# ----------------------------
# Chat serializers - ✅ ENHANCED WITH REAL NAMES
# ----------------------------
class ConversationSerializer(serializers.ModelSerializer):
    physician = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    patient = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    
    # ✅ ADD THESE FIELDS for readable names
    physician_name = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", 
            "physician", 
            "physician_name",  # ✅ NEW
            "patient", 
            "patient_name",    # ✅ NEW
            "created_at", 
            "updated_at",
            "last_message",    # ✅ NEW
        ]
        read_only_fields = ["id", "created_at", "updated_at", "physician_name", "patient_name", "last_message"]

    def get_physician_name(self, obj):
        """Get physician's full name from their profile, fallback to username."""
        try:
            profile = PhysicianProfile.objects.get(user=obj.physician)
            return profile.full_name or obj.physician.username
        except PhysicianProfile.DoesNotExist:
            return obj.physician.username or f"Dr. {obj.physician.id}"

    def get_patient_name(self, obj):
        """Get patient's full name from their profile, fallback to username."""
        try:
            profile = PatientProfile.objects.get(user=obj.patient)
            return profile.full_name or obj.patient.username
        except PatientProfile.DoesNotExist:
            return obj.patient.username or f"Patient {obj.patient.id}"

    def get_last_message(self, obj):
        """Get preview of last message."""
        last_msg = obj.messages.order_by("-created_at").first()
        if last_msg:
            preview = last_msg.body[:50]
            return preview + "..." if len(last_msg.body) > 50 else preview
        return ""


class MessageSerializer(serializers.ModelSerializer):
    # ✅ ADD sender_username and sender_name for display
    sender_username = serializers.CharField(source="sender.username", read_only=True)
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id", 
            "conversation", 
            "sender", 
            "sender_username",  # ✅ NEW
            "sender_name",      # ✅ NEW
            "body", 
            "attachment", 
            "created_at", 
            "is_read"
        ]
        read_only_fields = ["id", "created_at", "sender_username", "sender_name"]

    def get_sender_name(self, obj):
        """Get sender's full name from their profile."""
        try:
            # Try physician profile first
            profile = PhysicianProfile.objects.get(user=obj.sender)
            return profile.full_name or obj.sender.username
        except PhysicianProfile.DoesNotExist:
            pass
        
        try:
            # Try patient profile
            profile = PatientProfile.objects.get(user=obj.sender)
            return profile.full_name or obj.sender.username
        except PatientProfile.DoesNotExist:
            pass
        
        return obj.sender.username or "Unknown"


# ----------------------------
# Registration & lookup
# ----------------------------
class PhysicianRegisterSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    full_name = serializers.CharField(required=False, allow_blank=True)
    specialization = serializers.CharField(required=False, allow_blank=True)
    clinic_name = serializers.CharField(required=False, allow_blank=True)

    def create(self, validated):
        user = User.objects.create_user(
            username=validated["username"],
            password=validated["password"],
            email=validated.get("email", ""),
            role=User.Roles.PHYSICIAN,
        )
        profile = PhysicianProfile.objects.create(
            user=user,
            full_name=validated.get("full_name", ""),
            specialization=validated.get("specialization", ""),
            clinic_name=validated.get("clinic_name", ""),
        )
        return {
            "id": str(user.id),
            "username": user.username,
            "full_name": profile.full_name,
            "connect_code": profile.connect_code,
        }


class PatientRegisterSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    full_name = serializers.CharField(required=False, allow_blank=True)
    physician_code = serializers.CharField(required=False, allow_blank=True)

    def create(self, validated):
        user = User.objects.create_user(
            username=validated["username"],
            password=validated["password"],
            email=validated.get("email", ""),
            role=User.Roles.PATIENT,
        )
        doc = None
        code = validated.get("physician_code", "").strip().upper()
        if code:
            doc = PhysicianProfile.objects.filter(connect_code=code).first()
            if not doc:
                raise serializers.ValidationError({"physician_code": "Invalid physician code."})

        profile = PatientProfile.objects.create(
            user=user,
            full_name=validated.get("full_name", ""),
            physician=doc,
        )
        return {
            "id": str(user.id),
            "username": user.username,
            "full_name": profile.full_name,
            "linked_physician_code": doc.connect_code if doc else None,
        }


class PhysicianLookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhysicianProfile
        fields = ["connect_code", "full_name", "specialization", "clinic_name"]