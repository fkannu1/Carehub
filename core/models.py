from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
import uuid


# ----------------------------
# AUTH USER
# ----------------------------
class User(AbstractUser):
    class Roles(models.TextChoices):
        PATIENT = "PATIENT", "Patient"
        PHYSICIAN = "PHYSICIAN", "Physician"

    # ✅ UUID as primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # role field (matches your existing code)
    role = models.CharField(max_length=20, choices=Roles.choices, default=Roles.PATIENT)

    def is_patient(self) -> bool:
        return self.role == self.Roles.PATIENT

    def is_physician(self) -> bool:
        return self.role == self.Roles.PHYSICIAN


# ----------------------------
# PROFILES & RECORDS (existing)
# ----------------------------
class PhysicianProfile(models.Model):
    # Public-safe identifier for APIs (separate from PKs)
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    # Use AUTH_USER_MODEL so the FK type matches the UUID PK
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="physician")

    full_name = models.CharField(max_length=150)
    specialization = models.CharField(max_length=150, blank=True)
    clinic_name = models.CharField(max_length=150, blank=True)
    connect_code = models.CharField(max_length=12, unique=True)

    def __str__(self) -> str:
        return self.full_name or self.user.username


class PatientProfile(models.Model):
    # Public-safe identifier for APIs
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="patient")
    full_name = models.CharField(max_length=150)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)

    physician = models.ForeignKey(
        PhysicianProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="patients"
    )

    height_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    def __str__(self) -> str:
        return self.full_name or self.user.username


class HealthRecord(models.Model):
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name="records")
    created_at = models.DateTimeField(default=timezone.now)

    systolic_bp = models.IntegerField(null=True, blank=True)
    diastolic_bp = models.IntegerField(null=True, blank=True)
    sugar_fasting = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    sugar_pp = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="lab_files/", null=True, blank=True)

    def __str__(self) -> str:
        return f"Record {self.id} - {self.patient}"


# ----------------------------
# AVAILABILITY / APPOINTMENTS
# ----------------------------
class AvailabilitySlot(models.Model):
    """
    Open time block that a physician exposes to patients.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="availability_slots"
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    is_booked = models.BooleanField(default=False)

    class Meta:
        ordering = ["start"]
        indexes = [
            models.Index(fields=["physician", "start"]),
            models.Index(fields=["physician", "end"]),
        ]

    @property
    def is_past(self) -> bool:
        return self.end <= timezone.now()

    def clean(self):
        # basic order check
        if self.start >= self.end:
            raise ValidationError("Slot start must be before end.")

        # ensure the FK is a physician account (soft check; avoids circular imports)
        if hasattr(self.physician, "role") and getattr(self.physician, "role") != User.Roles.PHYSICIAN:
            raise ValidationError("Availability slots may only belong to physicians.")

        # prevent overlapping open slots for the same physician
        # (SQLite can't enforce exclusion constraints; validate here)
        overlap_qs = AvailabilitySlot.objects.filter(
            physician=self.physician,
            start__lt=self.end,
            end__gt=self.start,
        ).exclude(pk=self.pk)
        if overlap_qs.exists():
            raise ValidationError("This slot overlaps with an existing slot for this physician.")

    def save(self, *args, **kwargs):
        # always run model validation when saving from code/admin
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.physician} | {self.start:%Y-%m-%d %H:%M} → {self.end:%H:%M}"


class Appointment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slot = models.OneToOneField(
        AvailabilitySlot, on_delete=models.PROTECT, related_name="appointment"
    )
    physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="physician_appointments"
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="patient_appointments"
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["slot__start"]
        indexes = [
            models.Index(fields=["physician", "status"]),
            models.Index(fields=["patient", "status"]),
        ]

    def clean(self):
        # Ensure slot belongs to the same physician
        if self.slot.physician_id != self.physician_id:
            raise ValidationError("Slot physician mismatch.")

        # Disallow double-booking
        if self.slot.is_booked:
            raise ValidationError("Slot already booked.")

        # Can't book past
        if self.slot.start <= timezone.now():
            raise ValidationError("Cannot book a past slot.")

    def save(self, *args, **kwargs):
        creating = self._state.adding
        # validate before saving
        self.full_clean()
        super().save(*args, **kwargs)
        if creating:
            # mark slot as booked
            AvailabilitySlot.objects.filter(pk=self.slot_id).update(is_booked=True)

    def __str__(self):
        return f"Appt {self.patient} → {self.physician} @ {self.slot.start:%Y-%m-%d %H:%M}"


# ----------------------------
# CHAT (1:1 patient ↔ physician)
# ----------------------------
class Conversation(models.Model):
    """
    One conversation per patient+physician pair.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations_as_physician"
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations_as_patient"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("physician", "patient")

    def __str__(self):
        return f"Chat: {self.patient} ↔ {self.physician}"


class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages"
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender}: {self.body[:30]}"
