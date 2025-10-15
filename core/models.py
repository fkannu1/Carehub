from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

class User(AbstractUser):
    class Roles(models.TextChoices):
        PATIENT = "PATIENT", "Patient"
        PHYSICIAN = "PHYSICIAN", "Physician"

    role = models.CharField(max_length=20, choices=Roles.choices, default=Roles.PATIENT)

    def is_patient(self): return self.role == self.Roles.PATIENT
    def is_physician(self): return self.role == self.Roles.PHYSICIAN


class PhysicianProfile(models.Model):
    user = models.OneToOneField("core.User", on_delete=models.CASCADE, related_name="physician")
    full_name = models.CharField(max_length=150)
    specialization = models.CharField(max_length=150, blank=True)
    clinic_name = models.CharField(max_length=150, blank=True)
    connect_code = models.CharField(max_length=12, unique=True)

    def __str__(self):
        return self.full_name or self.user.username


class PatientProfile(models.Model):
    user = models.OneToOneField("core.User", on_delete=models.CASCADE, related_name="patient")
    full_name = models.CharField(max_length=150)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)

    physician = models.ForeignKey(
        PhysicianProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="patients"
    )

    height_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    def __str__(self):
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

    def __str__(self):
        return f"Record {self.id} - {self.patient}"
