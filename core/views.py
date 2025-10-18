# core/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.generic import FormView
from django.db import transaction
import secrets

from .models import User, PatientProfile, PhysicianProfile, HealthRecord
from .forms import (
    PatientSignUpForm as PatientSignupForm,
    PhysicianSignUpForm as PhysicianSignupForm,
    PatientProfileForm,
    HealthRecordForm,
)

# =========================
# AUTHENTICATION
# =========================

class SimpleLoginView(FormView):
    template_name = "auth/login.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is None:
            messages.error(request, "Invalid username or password.")
            return render(request, self.template_name)

        login(request, user)
        return dashboard_router(request)  # central role routing


def instant_logout(request):
    logout(request)
    messages.success(request, "Logged out.")
    return redirect("login")


# =========================
# SIGNUP FLOWS
# =========================

def signup_patient(request):
    """Create a User + PatientProfile via the form's save(), then (optionally) auto-login."""
    if request.method == "POST":
        form = PatientSignupForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # form.save() handles:
                # - user creation and role
                # - PatientProfile creation (height/weight/etc)
                # - optional physician linking via connect_code
                user = form.save(commit=True)

            messages.success(request, "Patient account created.")
            # optional auto-login
            raw_pw = form.cleaned_data.get("password1") or form.cleaned_data.get("password")
            if raw_pw:
                authed = authenticate(username=user.username, password=raw_pw)
                if authed:
                    login(request, authed)
                    return redirect("patient_dashboard")
            return redirect("login")
    else:
        form = PatientSignupForm()

    return render(request, "auth/signup_patient.html", {"form": form})


def signup_physician(request):
    """Create a User + PhysicianProfile and (optionally) auto-login."""
    if request.method == "POST":
        form = PhysicianSignupForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=True)
                # In case your custom User model has a role field and the form didn't set it:
                if hasattr(user, "role") and getattr(user, "role", None) != getattr(User.Roles, "PHYSICIAN", "physician"):
                    user.role = getattr(User.Roles, "PHYSICIAN", "physician")
                    user.save(update_fields=["role"])
                PhysicianProfile.objects.get_or_create(user=user)

            messages.success(request, "Physician account created.")
            raw_pw = form.cleaned_data.get("password1") or form.cleaned_data.get("password")
            if raw_pw:
                authed = authenticate(username=user.username, password=raw_pw)
                if authed:
                    login(request, authed)
                    return redirect("physician_dashboard")
            return redirect("login")
    else:
        form = PhysicianSignupForm()

    return render(request, "auth/signup_physician.html", {"form": form})


# =========================
# ROLE ROUTER
# =========================

@login_required
def dashboard_router(request):
    """
    Send the user to the correct dashboard based on role/profile.
    Works whether you rely on user.role helpers or related profiles.
    """
    user = request.user

    # If your custom User exposes helpers
    try:
        if callable(getattr(user, "is_physician", None)) and user.is_physician():
            return redirect("physician_dashboard")
        if callable(getattr(user, "is_patient", None)) and user.is_patient():
            return redirect("patient_dashboard")
    except Exception:
        pass

    # Fallback: inspect related profiles safely
    if hasattr(user, "physician") or PhysicianProfile.objects.filter(user=user).exists():
        return redirect("physician_dashboard")
    if hasattr(user, "patient") or PatientProfile.objects.filter(user=user).exists():
        return redirect("patient_dashboard")

    messages.error(request, "Invalid user role. Please contact support.")
    return redirect("login")


# =========================
# PATIENT VIEWS
# =========================

@login_required
def patient_dashboard(request):
    # Physicians shouldn’t land here
    try:
        if request.user.is_physician():
            return redirect("physician_dashboard")
    except Exception:
        pass

    # Ensure a profile exists; create a blank one if missing
    patient, _ = PatientProfile.objects.get_or_create(user=request.user)
    records = (
        HealthRecord.objects.filter(patient=patient)
        .select_related("patient")
        .order_by("-id")
    )
    return render(
        request,
        "patient/dashboard.html",
        {"patient": patient, "records": records},
    )


@login_required
def patient_profile_edit(request):
    patient, _ = PatientProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = PatientProfileForm(request.POST, instance=patient)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect("patient_dashboard")
    else:
        form = PatientProfileForm(instance=patient)

    return render(request, "patient/profile_form.html", {"form": form})


@login_required
def record_create(request):
    patient, _ = PatientProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = HealthRecordForm(request.POST, request.FILES)
        if form.is_valid():
            rec = form.save(commit=False)
            rec.patient = patient
            rec.save()
            messages.success(request, "Record added successfully.")
            return redirect("patient_dashboard")
    else:
        form = HealthRecordForm()

    return render(request, "patient/record_form.html", {"form": form})


@login_required
def record_edit(request, pk):
    # A patient can only edit their own record
    record = get_object_or_404(HealthRecord, pk=pk, patient__user=request.user)

    if request.method == "POST":
        form = HealthRecordForm(request.POST, request.FILES, instance=record)
        if form.is_valid():
            form.save()
            messages.success(request, "Record updated successfully.")
            return redirect("patient_dashboard")
    else:
        form = HealthRecordForm(instance=record)

    return render(request, "patient/record_form.html", {"form": form})


# =========================
# PHYSICIAN VIEWS
# =========================

@login_required
def physician_dashboard(request):
    # Patients shouldn’t land here
    try:
        if request.user.is_patient():
            return redirect("patient_dashboard")
    except Exception:
        pass

    physician, _ = PhysicianProfile.objects.get_or_create(user=request.user)

    # Search support (?q=)
    q = (request.GET.get("q") or "").strip()
    patients = PatientProfile.objects.filter(physician=physician)
    if q:
        patients = patients.filter(full_name__icontains=q)

    patients = patients.order_by("full_name")

    return render(
        request,
        "physician/dashboard.html",
        {"physician": physician, "patients": patients, "q": q},
    )


@login_required
def physician_patient_detail(request, patient_id):
    # Only physicians, and only for their own patients
    try:
        if request.user.is_patient():
            return redirect("patient_dashboard")
    except Exception:
        pass

    physician, _ = PhysicianProfile.objects.get_or_create(user=request.user)
    patient = get_object_or_404(PatientProfile, id=patient_id, physician=physician)
    records = HealthRecord.objects.filter(patient=patient).order_by("-id")
    return render(
        request,
        "physician/patient_detail.html",
        {"patient": patient, "records": records},
    )


@login_required
def regenerate_connect_code(request):
    """
    Generate a new connect_code for the logged-in physician.
    Add a 'Regenerate' button/link in the physician dashboard that points here.
    """
    # Patients shouldn’t access this
    try:
        if request.user.is_patient():
            messages.error(request, "Only physicians can regenerate a connect code.")
            return redirect("patient_dashboard")
    except Exception:
        pass

    physician, _ = PhysicianProfile.objects.get_or_create(user=request.user)
    physician.connect_code = secrets.token_hex(4)  # 8 chars, e.g., 'a1b2c3d4'
    physician.save(update_fields=["connect_code"])
    messages.success(request, "New connect code generated.")
    return redirect("physician_dashboard")
