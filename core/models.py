from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
import uuid


class User(AbstractUser):
    class Roles(models.TextChoices):
        PATIENT = "PATIENT", "Patient"
        PHYSICIAN = "PHYSICIAN", "Physician"

    # ✅ Primary key is now UUID
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    role = models.CharField(max_length=20, choices=Roles.choices, default=Roles.PATIENT)

    def is_patient(self) -> bool:
        return self.role == self.Roles.PATIENT

    def is_physician(self) -> bool:
        return self.role == self.Roles.PHYSICIAN


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
