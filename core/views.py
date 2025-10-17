from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden
from .models import User, PatientProfile, PhysicianProfile, HealthRecord
from .forms import (
    PatientSignUpForm as PatientSignupForm,
    PhysicianSignUpForm as PhysicianSignupForm,
    PatientProfileForm,
    HealthRecordForm,
)
from django.views.generic import FormView


# ----------------------------
# AUTHENTICATION VIEWS
# ----------------------------

class SimpleLoginView(FormView):
    template_name = "auth/login.html"

    def get(self, request):
        return render(request, "auth/login.html")

    def post(self, request):
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("dashboard_router")
        messages.error(request, "Invalid username or password.")
        return render(request, "auth/login.html")


def instant_logout(request):
    logout(request)
    return redirect("login")


# ----------------------------
# SIGNUP VIEWS
# ----------------------------

def signup_patient(request):
    if request.method == "POST":
        form = PatientSignupForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.role = "patient"
            user.save()
            PatientProfile.objects.create(user=user)
            messages.success(request, "Account created successfully! Please log in.")
            return redirect("login")
    else:
        form = PatientSignupForm()
    return render(request, "auth/signup_patient.html", {"form": form})


def signup_physician(request):
    if request.method == "POST":
        form = PhysicianSignupForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.role = "physician"
            user.save()
            PhysicianProfile.objects.create(user=user)
            messages.success(request, "Physician account created successfully! Please log in.")
            return redirect("login")
    else:
        form = PhysicianSignupForm()
    return render(request, "auth/signup_physician.html", {"form": form})


# ----------------------------
# DASHBOARD ROUTER
# ----------------------------

@login_required
def dashboard_router(request):
    """Send the user to the correct dashboard based on role."""
    if request.user.is_patient():
        return redirect("patient_dashboard")
    if request.user.is_physician():
        return redirect("physician_dashboard")
    messages.error(request, "Invalid user role. Please contact support.")
    return redirect("login")


# ----------------------------
# PATIENT DASHBOARD + PROFILE + RECORDS
# ----------------------------

@login_required
def patient_dashboard(request):
    # If a physician hits /patient/, redirect them to their dashboard
    if request.user.is_physician():
        return redirect("physician_dashboard")

    # Make this view safe if the user has no patient profile yet
    try:
        patient = request.user.patient
    except PatientProfile.DoesNotExist:
        messages.warning(request, "Please complete your patient profile.")
        return redirect("patient_profile_edit")

    records = HealthRecord.objects.filter(patient=patient)
    return render(
        request,
        "patient/dashboard.html",
        {"patient": patient, "records": records},
    )


@login_required
def patient_profile_edit(request):
    # Ensure a profile exists; create a blank one if not
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
    # Only the logged-in patient can create their own record
    patient = get_object_or_404(PatientProfile, user=request.user)

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


# ----------------------------
# PHYSICIAN DASHBOARD + PATIENT DETAIL
# ----------------------------

@login_required
def physician_dashboard(request):
    if request.user.is_patient():
        return redirect("patient_dashboard")

    physician = request.user.physician
    patients = PatientProfile.objects.filter(physician=physician)
    return render(
        request,
        "physician/dashboard.html",
        {"physician": physician, "patients": patients},
    )


@login_required
def physician_patient_detail(request, patient_id):
    if request.user.is_patient():
        return HttpResponseForbidden("Only physicians can view patient details.")

    patient = get_object_or_404(PatientProfile, id=patient_id)
    records = HealthRecord.objects.filter(patient=patient)
    return render(
        request,
        "physician/patient_detail.html",
        {"patient": patient, "records": records},
    )
