from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from datetime import timedelta
import uuid
import secrets


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
# helpers
# ----------------------------
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # avoid 0/1/O/I for readability


def generate_connect_code(n: int = 8) -> str:
    """Collision-resistant, human-friendly code."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


# ----------------------------
# PROFILES & RECORDS
# ----------------------------
class PhysicianProfile(models.Model):
    # Public-safe identifier for APIs (separate from PKs)
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    # Use AUTH_USER_MODEL so the FK type matches the UUID PK
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="physician")

    full_name = models.CharField(max_length=150)
    specialization = models.CharField(max_length=150, blank=True)
    clinic_name = models.CharField(max_length=150, blank=True)

    # Unique connect code used by patients to link to this physician
    connect_code = models.CharField(max_length=12, unique=True, blank=True, db_index=True)

    def save(self, *args, **kwargs):
        # Auto-generate a unique connect_code if missing
        if not self.connect_code:
            code = generate_connect_code()
            while PhysicianProfile.objects.filter(connect_code=code).exists():
                code = generate_connect_code()
            self.connect_code = code
        super().save(*args, **kwargs)

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

    # Linked physician via exclusive code flow
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


# -------------------------------------------------------
# LEGACY PRE-SLICED AVAILABILITY + APPOINTMENT (kept)
# -------------------------------------------------------
class AvailabilitySlot(models.Model):
    """
    Pre-sliced open time block a physician exposes to patients.
    We mark these as booked if a flexible appointment overlaps them
    so the calendar never shows confusing overlaps.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # NOTE: historically this pointed to User; keep it for compatibility
    physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="availability_slots"
    )
    start = models.DateTimeField()
    end = models.DateTimeField()

    # Booked by legacy Appointment or blocked by a FlexAppointment
    is_booked = models.BooleanField(default=False)

    # NEW: which FlexAppointment blocked this slot (if any)
    booked_by_flex = models.ForeignKey(
        "FlexAppointment", null=True, blank=True, on_delete=models.SET_NULL, related_name="blocked_slots"
    )

    class Meta:
        ordering = ["start"]
        indexes = [
            models.Index(fields=["physician", "start"]),
            models.Index(fields=["physician", "end"]),
            models.Index(fields=["is_booked"]),
        ]

    @property
    def is_past(self) -> bool:
        return self.end <= timezone.now()

    def _validate_physician_role(self):
        # physician here is a User
        if hasattr(self.physician, "role") and getattr(self.physician, "role") != User.Roles.PHYSICIAN:
            raise ValidationError("Availability slots may only belong to physicians.")

    def clean(self):
        if self.start >= self.end:
            raise ValidationError("Slot start must be before end.")
        self._validate_physician_role()

        # no overlapping raw slots for same physician (keeps the data clean)
        overlap_qs = AvailabilitySlot.objects.filter(
            physician=self.physician,
            start__lt=self.end,
            end__gt=self.start,
        ).exclude(pk=self.pk)
        if overlap_qs.exists():
            raise ValidationError("This slot overlaps an existing slot for this physician.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.physician} | {self.start:%Y-%m-%d %H:%M} → {self.end:%H:%M}"


class Appointment(models.Model):
    """
    LEGACY appointment bound to a single AvailabilitySlot (kept for compat).
    """
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
        # basic alignments
        if self.slot.physician_id != self.physician_id:
            raise ValidationError("Slot physician mismatch.")
        if self.slot.is_booked:
            raise ValidationError("Slot already booked.")
        if self.slot.start <= timezone.now():
            raise ValidationError("Cannot book a past slot.")

        # Also prevent conflict with any Confirmed/Pending FlexAppointment
        conflict = FlexAppointment.objects.filter(
            physician=self.physician,
            status__in=[FlexAppointment.Status.PENDING, FlexAppointment.Status.CONFIRMED],
            start__lt=self.slot.end,
            end__gt=self.slot.start,
        ).exists()
        if conflict:
            raise ValidationError("This time conflicts with another appointment.")

    def save(self, *args, **kwargs):
        creating = self._state.adding
        self.full_clean()
        super().save(*args, **kwargs)
        if creating:
            # Mark slot as booked by legacy flow
            AvailabilitySlot.objects.filter(pk=self.slot_id).update(is_booked=True, booked_by_flex=None)

    def __str__(self):
        return f"Appt {self.patient} → {self.physician} @ {self.slot.start:%Y-%m-%d %H:%M}"


# -------------------------------------------------------
# NEW WINDOW + FLEXIBLE APPOINTMENTS (no overlaps)
# -------------------------------------------------------
class PhysicianWeeklyAvailability(models.Model):
    """
    Repeating weekly free-time window for a physician.
    Example: weekday=3 (Thu), 09:00–17:00. Patients can pick arbitrary
    30/45/60-min times inside these windows (frontend/API can generate starts).
    """
    WEEKDAYS = [
        (0, "Mon"),
        (1, "Tue"),
        (2, "Wed"),
        (3, "Thu"),
        (4, "Fri"),
        (5, "Sat"),
        (6, "Sun"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="weekly_windows"
    )
    weekday = models.IntegerField(choices=WEEKDAYS)
    start_time = models.TimeField()  # e.g., 09:00
    end_time = models.TimeField()    # e.g., 17:00
    is_active = models.BooleanField(default=True)
    snap_minutes = models.PositiveIntegerField(default=15, help_text="Snap start times to this granularity.")

    class Meta:
        ordering = ["physician", "weekday", "start_time"]
        unique_together = ("physician", "weekday", "start_time", "end_time")

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError("Window start_time must be before end_time.")
        if hasattr(self.physician, "role") and getattr(self.physician, "role") != User.Roles.PHYSICIAN:
            raise ValidationError("Weekly windows may only belong to physicians.")

    def __str__(self):
        return f"{self.physician} | {self.get_weekday_display()} {self.start_time}–{self.end_time} ({'on' if self.is_active else 'off'})"


class PhysicianDateOverride(models.Model):
    """
    Date-specific override. If `is_closed=True`, physician is unavailable that date.
    Otherwise, defines an extra (or replacement) window for the given date.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="date_overrides"
    )
    date = models.DateField()
    is_closed = models.BooleanField(default=False)

    # If not closed, define a specific window for that date:
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    class Meta:
        ordering = ["physician", "date", "start_time"]
        indexes = [
            models.Index(fields=["physician", "date"]),
        ]
        unique_together = ("physician", "date", "start_time", "end_time")

    def clean(self):
        if self.is_closed:
            return
        if not self.start_time or not self.end_time:
            raise ValidationError("Provide start_time and end_time when the day is not closed.")
        if self.start_time >= self.end_time:
            raise ValidationError("Override start_time must be before end_time.")
        if hasattr(self.physician, "role") and getattr(self.physician, "role") != User.Roles.PHYSICIAN:
            raise ValidationError("Date overrides may only belong to physicians.")

    def __str__(self):
        if self.is_closed:
            return f"{self.physician} | {self.date} CLOSED"
        return f"{self.physician} | {self.date} {self.start_time}–{self.end_time}"


class TimeOff(models.Model):
    """
    Arbitrary time-off ranges (vacation, lunch, conferences).
    These are subtracted from weekly windows when computing availability.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="time_off"
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["start"]
        indexes = [
            models.Index(fields=["physician", "start"]),
            models.Index(fields=["physician", "end"]),
        ]

    def clean(self):
        if self.end <= self.start:
            raise ValidationError("TimeOff end must be after start.")
        if hasattr(self.physician, "role") and getattr(self.physician, "role") != User.Roles.PHYSICIAN:
            raise ValidationError("TimeOff may only belong to physicians.")

    def __str__(self):
        return f"{self.physician} | {self.start:%Y-%m-%d %H:%M}–{self.end:%H:%M} ({self.reason or 'time off'})"


# ----------------------------
# FLEXIBLE APPOINTMENT (no overlaps of ANY length)
# ----------------------------
class FlexAppointment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="flex_appointments_as_physician"
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="flex_appointments_as_patient"
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start"]
        indexes = [
            models.Index(fields=["physician", "start"]),
            models.Index(fields=["patient", "start"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.CheckConstraint(check=models.Q(end__gt=models.F("start")), name="flexappt_end_gt_start"),
        ]

    # ---- helpers
    @staticmethod
    def _overlap_q(start, end):
        """Return a Q object representing strict time overlap."""
        return models.Q(start__lt=end) & models.Q(end__gt=start)

    def _validate_physician_role(self):
        if hasattr(self.physician, "role") and getattr(self.physician, "role") != User.Roles.PHYSICIAN:
            raise ValidationError("Appointments must belong to a physician.")

    def clean(self):
        # 1) basic
        if self.end <= self.start:
            raise ValidationError("End must be after start.")
        self._validate_physician_role()

        active_states = [self.Status.PENDING, self.Status.CONFIRMED]

        # 2) no overlap with other FlexAppointments
        flex_conflict = FlexAppointment.objects.filter(
            physician=self.physician,
            status__in=active_states
        ).filter(self._overlap_q(self.start, self.end)).exclude(pk=self.pk).exists()
        if flex_conflict:
            raise ValidationError("This appointment overlaps another appointment.")

        # 3) no overlap with legacy Appointment (via its slot range)
        legacy_conflict = Appointment.objects.filter(
            physician=self.physician,
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED]
        ).filter(
            models.Q(slot__start__lt=self.end) & models.Q(slot__end__gt=self.start)
        ).exists()
        if legacy_conflict:
            raise ValidationError("This appointment conflicts with an existing booked slot.")

    def duration_minutes(self) -> int:
        return int((self.end - self.start) / timedelta(minutes=1))

    def _block_overlapping_slots(self):
        """
        Mark any pre-sliced AvailabilitySlots that overlap this confirmed FlexAppointment
        as booked and attribute them to this FlexAppointment. This keeps the calendar clean.
        """
        if self.status != self.Status.CONFIRMED:
            return
        AvailabilitySlot.objects.filter(
            physician=self.physician,
            start__lt=self.end,
            end__gt=self.start,
        ).update(is_booked=True, booked_by_flex=self)

    def _release_blocked_slots(self):
        """
        Release only the slots we previously blocked (avoid touching legacy-booked slots).
        """
        AvailabilitySlot.objects.filter(booked_by_flex=self).update(is_booked=False, booked_by_flex=None)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            creating = self._state.adding
            old_status = None
            if not creating:
                old = FlexAppointment.objects.select_for_update().get(pk=self.pk)
                old_status = old.status

            self.full_clean()
            super().save(*args, **kwargs)

            # If newly created or status changed, adjust slots
            if self.status == self.Status.CONFIRMED:
                self._block_overlapping_slots()
            # If moved to CANCELLED, release any blocks we created
            if old_status and old_status != self.status and self.status == self.Status.CANCELLED:
                self._release_blocked_slots()

    def delete(self, using=None, keep_parents=False):
        with transaction.atomic():
            self._release_blocked_slots()
            return super().delete(using=using, keep_parents=keep_parents)

    def __str__(self):
        return f"{self.patient} → {self.physician} | {self.start:%Y-%m-%d %H:%M}–{self.end:%H:%M} [{self.status}]"


# ----------------------------
# CHAT (1:1 patient ↔ physician) — independent of appointments
# ----------------------------
class Conversation(models.Model):
    """
    Exactly one conversation per (patient, physician) pair.
    This exists regardless of appointments; appointments can simply link to it.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations_as_physician"
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations_as_patient"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # helps sort inbox by recent activity

    class Meta:
        unique_together = ("physician", "patient")
        indexes = [
            models.Index(fields=["physician", "patient"]),
            models.Index(fields=["updated_at"]),
        ]

    def participant_ids(self):
        return {self.physician_id, self.patient_id}

    def other_party_for(self, user):
        return self.physician if user.id == self.patient_id else self.patient

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
    body = models.TextField(blank=True)
    attachment = models.FileField(upload_to="chat_attachments/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self):
        preview = (self.body or "").strip().replace("\n", " ")
        return f"{self.sender}: {preview[:30]}"
