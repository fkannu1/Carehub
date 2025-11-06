# core/api/views.py
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q
from rest_framework import viewsets, permissions, filters, status as http_status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser

from core.models import (
    PhysicianProfile,
    PatientProfile,
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

from core.api.serializers import (
    # profiles & records
    PhysicianProfileSerializer,
    PatientProfileSerializer,
    HealthRecordSerializer,
    # legacy availability & appts
    AvailabilitySlotSerializer,
    AppointmentSerializer,  # keep for writes; you also have AppointmentReadSerializer if needed
    # new availability system (names as in serializers.py)
    WeeklyWindowSerializer,  # <-- was PhysicianWeeklyAvailabilitySerializer
    DateOverrideSerializer,  # <-- was PhysicianDateOverrideSerializer
    TimeOffSerializer,
    # flex appointments
    FlexAppointmentCreateSerializer,
    FlexAppointmentReadSerializer,
    # chat
    ConversationSerializer,
    MessageSerializer,
)

User = get_user_model()


# ---------- Permissions ----------

class IsAuthed(permissions.IsAuthenticated):
    """Alias for readability."""


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Write access only for owners (or staff/superuser). Read is governed by queryset.
    """

    def has_object_permission(self, request, view, obj):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser or u.is_staff:
            return True

        if isinstance(obj, PatientProfile):
            return obj.user_id == u.id

        if isinstance(obj, PhysicianProfile):
            return obj.user_id == u.id

        if isinstance(obj, HealthRecord):
            # HealthRecord.patient -> PatientProfile (which has .user)
            if obj.patient.user_id == u.id:
                return True
            if getattr(obj, "physician", None) and obj.physician.user_id == u.id:
                return True
            return request.method in permissions.SAFE_METHODS

        if isinstance(obj, AvailabilitySlot):
            return obj.physician.user_id == u.id or request.method in permissions.SAFE_METHODS

        if isinstance(obj, Appointment):
            if obj.patient.user_id == u.id or obj.physician.user_id == u.id:
                return True
            return request.method in permissions.SAFE_METHODS

        # Conversation/Message handled via queryset & sender checks
        return request.method in permissions.SAFE_METHODS


# ---------- Physician Profiles ----------

class PhysicianProfileViewSet(viewsets.ModelViewSet):
    serializer_class = PhysicianProfileSerializer
    permission_classes = [IsAuthed, IsOwnerOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ["full_name", "user__username", "user__email", "specialization"]

    def get_queryset(self):
        qs = PhysicianProfile.objects.select_related("user")
        u = self.request.user
        if u.is_superuser or u.is_staff:
            return qs
        if getattr(u, "role", None) == User.Roles.PHYSICIAN:
            return qs.filter(user=u)
        if getattr(u, "role", None) == User.Roles.PATIENT:
            # Patients can browse physicians (directory)
            return qs
        return qs.none()

    @action(detail=False, methods=["get"])
    def me(self, request):
        if not request.user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=http_status.HTTP_401_UNAUTHORIZED)
        profile = PhysicianProfile.objects.filter(user=request.user).select_related("user").first()
        if not profile:
            return Response({"detail": "Profile not found."}, status=http_status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(profile).data)


# ---------- Patient Profiles ----------

class PatientProfileViewSet(viewsets.ModelViewSet):
    serializer_class = PatientProfileSerializer
    permission_classes = [IsAuthed, IsOwnerOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ["full_name", "user__username", "user__email"]

    def get_queryset(self):
        qs = PatientProfile.objects.select_related("user", "physician")
        u = self.request.user
        if u.is_superuser or u.is_staff:
            return qs
        if getattr(u, "role", None) == User.Roles.PATIENT:
            return qs.filter(user=u)
        if getattr(u, "role", None) == User.Roles.PHYSICIAN:
            # Show only patients linked to this physician
            return qs.filter(physician__user=u)
        return qs.none()

    @action(detail=False, methods=["get"])
    def me(self, request):
        if not request.user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=http_status.HTTP_401_UNAUTHORIZED)
        profile = PatientProfile.objects.filter(user=request.user).select_related("user", "physician").first()
        if not profile:
            return Response({"detail": "Profile not found."}, status=http_status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(profile).data)


# ---------- Health Records ----------

class HealthRecordViewSet(viewsets.ModelViewSet):
    """
    Patients can see/create/update only their own records (patient = their PatientProfile).
    Physicians see records for their own patients (PatientProfile.physician = this physician).
    Supports JSON and multipart (file upload on 'attachment').
    """
    serializer_class = HealthRecordSerializer
    permission_classes = [IsAuthed]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        # NOTE: patient is a PatientProfile FK
        qs = HealthRecord.objects.select_related("patient", "patient__user")
        u = self.request.user

        if u.is_superuser or u.is_staff:
            return qs

        role = getattr(u, "role", None)
        if role == User.Roles.PATIENT:
            # filter by PatientProfile of the logged-in user
            return qs.filter(patient__user=u)

        if role == User.Roles.PHYSICIAN:
            # collect PatientProfile IDs for this physician
            profile_ids = PatientProfile.objects.filter(
                physician__user=u
            ).values_list("id", flat=True)
            return qs.filter(patient_id__in=list(profile_ids))

        return qs.none()

    def perform_create(self, serializer):
        u = self.request.user
        role = getattr(u, "role", None)

        if role == User.Roles.PATIENT:
            # assign the patient's own PatientProfile
            profile = PatientProfile.objects.filter(user=u).first()
            if not profile:
                raise ValueError("No PatientProfile found for current user.")
            serializer.save(patient=profile)
        else:
            # physicians/staff: payload must include 'patient' as a PatientProfile id
            serializer.save()

    def perform_update(self, serializer):
        u = self.request.user
        role = getattr(u, "role", None)

        if role == User.Roles.PATIENT:
            profile = PatientProfile.objects.filter(user=u).first()
            if not profile:
                raise ValueError("No PatientProfile found for current user.")
            serializer.save(patient=profile)
        else:
            serializer.save()

    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request):
        ser = self.get_serializer(self.get_queryset(), many=True)
        return Response(ser.data)


# ---------- Legacy availability (fixed windows) ----------

class AvailabilitySlotViewSet(viewsets.ModelViewSet):
    serializer_class = AvailabilitySlotSerializer
    permission_classes = [IsAuthed, IsOwnerOrReadOnly]

    def get_queryset(self):
        u = self.request.user
        qs = AvailabilitySlot.objects.select_related("physician__user")
        if u.is_superuser or u.is_staff:
            return qs
        if getattr(u, "role", None) == User.Roles.PHYSICIAN:
            return qs.filter(physician__user=u)
        if getattr(u, "role", None) == User.Roles.PATIENT:
            # patients read all to show green slots
            return qs
        return qs.none()

    def perform_create(self, serializer):
        u = self.request.user
        if getattr(u, "role", None) != User.Roles.PHYSICIAN and not (u.is_staff or u.is_superuser):
            raise permissions.PermissionDenied("Only physicians can create availability slots.")
        serializer.save()


# ---------- Legacy Appointments (slot-based) ----------

class AppointmentViewSet(viewsets.ModelViewSet):
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthed, IsOwnerOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ["notes", "patient__full_name", "physician__full_name"]

    def get_queryset(self):
        u = self.request.user
        qs = Appointment.objects.select_related("patient__user", "physician__user")
        if u.is_superuser or u.is_staff:
            return qs.order_by("-start_time")
        if getattr(u, "role", None) == User.Roles.PATIENT:
            return qs.filter(patient__user=u).order_by("-start_time")
        if getattr(u, "role", None) == User.Roles.PHYSICIAN:
            return qs.filter(physician__user=u).order_by("-start_time")
        return qs.none()

    def perform_create(self, serializer):
        u = self.request.user
        if not (u.is_staff or u.is_superuser) and getattr(u, "role", None) != User.Roles.PATIENT:
            raise permissions.PermissionDenied("Only patients can book appointments (or staff).")

        start = serializer.validated_data["start_time"]
        end = serializer.validated_data["end_time"]
        physician = serializer.validated_data["physician"]

        overlap = Appointment.objects.filter(
            physician=physician, start_time__lt=end, end_time__gt=start
        ).exists()
        if overlap:
            raise permissions.PermissionDenied("This time is already booked.")

        serializer.save(created_by=u)


# ---------- New weekly templates & date overrides ----------

class PhysicianWeeklyAvailabilityViewSet(viewsets.ModelViewSet):
    """
    Uses WeeklyWindowSerializer (your name in serializers.py).
    """
    serializer_class = WeeklyWindowSerializer
    permission_classes = [IsAuthed, IsOwnerOrReadOnly]

    def get_queryset(self):
        u = self.request.user
        qs = PhysicianWeeklyAvailability.objects.select_related("physician__user")
        if u.is_superuser or u.is_staff:
            return qs
        if getattr(u, "role", None) == User.Roles.PHYSICIAN:
            return qs.filter(physician__user=u)
        return qs.none()

# Back-compat alias for core.urls imports
WeeklyWindowViewSet = PhysicianWeeklyAvailabilityViewSet


class PhysicianDateOverrideViewSet(viewsets.ModelViewSet):
    serializer_class = DateOverrideSerializer
    permission_classes = [IsAuthed, IsOwnerOrReadOnly]

    def get_queryset(self):
        u = self.request.user
        qs = PhysicianDateOverride.objects.select_related("physician__user")
        if u.is_superuser or u.is_staff:
            return qs
        if getattr(u, "role", None) == User.Roles.PHYSICIAN:
            return qs.filter(physician__user=u)
        return qs.none()

# Back-compat alias for core.urls imports
DateOverrideViewSet = PhysicianDateOverrideViewSet


class TimeOffViewSet(viewsets.ModelViewSet):
    serializer_class = TimeOffSerializer
    permission_classes = [IsAuthed, IsOwnerOrReadOnly]

    def get_queryset(self):
        u = self.request.user
        qs = TimeOff.objects.select_related("physician__user")
        if u.is_superuser or u.is_staff:
            return qs
        if getattr(u, "role", None) == User.Roles.PHYSICIAN:
            return qs.filter(physician__user=u)
        return qs.none()


# ---------- Flexible Appointments (start + duration) ----------

class FlexAppointmentViewSet(viewsets.ModelViewSet):
    """
    POST with FlexAppointmentCreateSerializer; GET/LIST with FlexAppointmentReadSerializer.
    """
    permission_classes = [IsAuthed, IsOwnerOrReadOnly]

    def get_queryset(self):
        u = self.request.user
        qs = FlexAppointment.objects.select_related("patient", "physician")
        if u.is_superuser or u.is_staff:
            return qs.order_by("-start")
        if getattr(u, "role", None) == User.Roles.PATIENT:
            return qs.filter(patient=u).order_by("-start")
        if getattr(u, "role", None) == User.Roles.PHYSICIAN:
            return qs.filter(physician=u).order_by("-start")
        return qs.none()

    def get_serializer_class(self):
        if self.request.method in ("POST", "PUT", "PATCH"):
            return FlexAppointmentCreateSerializer
        return FlexAppointmentReadSerializer

    def perform_create(self, serializer):
        # create() sets patient from request and computes end
        serializer.save()


# ---------- Conversations & Messages (independent chat) ----------

class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthed]

    def get_queryset(self):
        u = self.request.user
        if not u.is_authenticated:
            return Conversation.objects.none()
        return Conversation.objects.filter(Q(physician=u) | Q(patient=u)).order_by("-updated_at")

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        conv = self.get_object()
        u = request.user
        if not (conv.patient_id == u.id or conv.physician_id == u.id or u.is_staff or u.is_superuser):
            return Response({"detail": "Not allowed."}, status=http_status.HTTP_403_FORBIDDEN)

        text = request.data.get("text", "").strip()
        if not text:
            return Response({"detail": "Message text required."}, status=http_status.HTTP_400_BAD_REQUEST)

        msg = Message.create(conversation=conv, sender=u, body=text) if hasattr(Message, "create") \
            else Message.objects.create(conversation=conv, sender=u, body=text)

        conv.updated_at = timezone.now()
        conv.save(update_fields=["updated_at"])
        return Response(MessageSerializer(msg).data, status=http_status.HTTP_201_CREATED)


class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthed]

    def get_queryset(self):
        u = self.request.user
        return (
            Message.objects.filter(Q(conversation__physician=u) | Q(conversation__patient=u))
            .select_related("conversation", "sender")
            .order_by("created_at")
        )
