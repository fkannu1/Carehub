from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    PatientSignUpForm,
    PhysicianSignUpForm,
    PatientProfileForm,
    HealthRecordForm,
)
from .models import PatientProfile, PhysicianProfile, HealthRecord


# ---------- Auth ----------
class SimpleLoginView(LoginView):
    template_name = "auth/login.html"


# Use this if you ever want POST-only logout:
class SimpleLogoutView(LogoutView):
    pass


def instant_logout(request):
    """Logout on GET then go back to login page (fixes 405)."""
    logout(request)
    return redirect("login")


def signup_patient(request):
    if request.method == "POST":
        form = PatientSignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard_router")
    else:
        form = PatientSignUpForm()
    return render(request, "auth/signup_patient.html", {"form": form})


def signup_physician(request):
    if request.method == "POST":
        form = PhysicianSignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard_router")
    else:
        form = PhysicianSignUpForm()
    return render(request, "auth/signup_physician.html", {"form": form})


@login_required
def dashboard_router(request):
    if request.user.is_physician():
        return redirect("physician_dashboard")
    return redirect("patient_dashboard")


# ---------- Patient ----------
@login_required
def patient_dashboard(request):
    if not request.user.is_patient():
        return redirect("physician_dashboard")
    patient = request.user.patient
    records = patient.records.order_by("-created_at")
    return render(request, "patient/dashboard.html", {"patient": patient, "records": records})


@login_required
def patient_profile_edit(request):
    if not request.user.is_patient():
        return redirect("physician_dashboard")
    patient = request.user.patient
    if request.method == "POST":
        form = PatientProfileForm(request.POST, instance=patient)
        if form.is_valid():
            p = form.save()
            code = form.cleaned_data.get("physician_connect_code")
            if code:
                try:
                    doc = PhysicianProfile.objects.get(connect_code=code)
                    p.physician = doc
                    p.save()
                except PhysicianProfile.DoesNotExist:
                    pass
            return redirect("patient_dashboard")
    else:
        form = PatientProfileForm(instance=patient)
    return render(request, "patient/profile_form.html", {"form": form})


@login_required
def record_create(request):
    if not request.user.is_patient():
        return redirect("physician_dashboard")
    patient = request.user.patient
    if request.method == "POST":
        form = HealthRecordForm(request.POST, request.FILES)
        if form.is_valid():
            rec = form.save(commit=False)
            rec.patient = patient
            rec.save()
            return redirect("patient_dashboard")
    else:
        form = HealthRecordForm()
    return render(request, "patient/record_form.html", {"form": form})


@login_required
def record_edit(request, pk):
    if not request.user.is_patient():
        return redirect("physician_dashboard")
    patient = request.user.patient
    rec = get_object_or_404(HealthRecord, pk=pk, patient=patient)
    if request.method == "POST":
        form = HealthRecordForm(request.POST, request.FILES, instance=rec)
        if form.is_valid():
            form.save()
            return redirect("patient_dashboard")
    else:
        form = HealthRecordForm(instance=rec)
    return render(request, "patient/record_form.html", {"form": form})


# ---------- Physician ----------
@login_required
def physician_dashboard(request):
    if not request.user.is_physician():
        return redirect("patient_dashboard")
    doctor = request.user.physician
    patients = doctor.patients.order_by("full_name")
    q = request.GET.get("q", "").strip()
    if q:
        patients = patients.filter(
            Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(user__username__icontains=q)
        )
    return render(request, "physician/dashboard.html", {"doctor": doctor, "patients": patients, "q": q})


@login_required
def physician_patient_detail(request, patient_id):
    if not request.user.is_physician():
        return redirect("patient_dashboard")
    doctor = request.user.physician
    patient = get_object_or_404(PatientProfile, id=patient_id, physician=doctor)
    records = patient.records.order_by("-created_at")
    return render(request, "physician/patient_detail.html", {"patient": patient, "records": records})
