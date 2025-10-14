# core/views.py

from django.contrib.auth import login
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


# -------------------- Auth --------------------
class SimpleLoginView(LoginView):
    template_name = "auth/login.html"


class SimpleLogoutView(LogoutView):
    pass


def signup_patient(request):
    """
    Register a new Patient user.
    Also creates PatientProfile and (optionally) links to a Physician via connect_code.
    """
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
    """
    Register a new Physician user.
    Also creates PhysicianProfile with a connect_code that patients can use to link.
    """
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
    """
    After login or signup, send users to the correct dashboard based on role.
    """
    if request.user.is_physician():
        return redirect("physician_dashboard")
    return redirect("patient_dashboard")


# -------------------- Patient --------------------
@login_required
def patient_dashboard(request):
    """
    Patient home: see profile summary and list of personal HealthRecords.
    """
    if not request.user.is_patient():
        return redirect("physician_dashboard")

    patient = request.user.patient  # OneToOne reverse accessor from User -> PatientProfile
    records = patient.records.order_by("-created_at")
    return render(
        request,
        "patient/dashboard.html",
        {"patient": patient, "records": records},
    )


@login_required
def patient_profile_edit(request):
    """
    Edit patient profile details.
    Can also link/update physician by entering a connect_code.
    """
    if not request.user.is_patient():
        return redirect("physician_dashboard")

    patient = request.user.patient
    if request.method == "POST":
        form = PatientProfileForm(request.POST, instance=patient)
        if form.is_valid():
            p = form.save()
            # Optionally link/update physician using a code
            code = form.cleaned_data.get("physician_connect_code")
            if code:
                try:
                    doc = PhysicianProfile.objects.get(connect_code=code)
                    p.physician = doc
                    p.save()
                except PhysicianProfile.DoesNotExist:
                    # Silently ignore bad codes for now; you can show a message if you like.
                    pass
            return redirect("patient_dashboard")
    else:
        form = PatientProfileForm(instance=patient)

    return render(request, "patient/profile_form.html", {"form": form})


@login_required
def record_create(request):
    """
    Create a new HealthRecord for the logged-in patient.
    """
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
    """
    Edit an existing HealthRecord that belongs to the logged-in patient.
    """
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


# -------------------- Physician --------------------
@login_required
def physician_dashboard(request):
    """
    Physician overview: see list of linked patients.
    Includes a simple search box (name/phone/username).
    """
    if not request.user.is_physician():
        return redirect("patient_dashboard")

    doctor = request.user.physician  # OneToOne reverse accessor from User -> PhysicianProfile
    patients = doctor.patients.order_by("full_name")

    q = request.GET.get("q", "").strip()
    if q:
        patients = patients.filter(
            Q(full_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(user__username__icontains=q)
        )

    return render(
        request,
        "physician/dashboard.html",
        {"doctor": doctor, "patients": patients, "q": q},
    )


@login_required
def physician_patient_detail(request, patient_id):
    """
    Physician view of a single linked patient and all of their HealthRecords.
    """
    if not request.user.is_physician():
        return redirect("patient_dashboard")

    doctor = request.user.physician
    patient = get_object_or_404(PatientProfile, id=patient_id, physician=doctor)
    records = patient.records.order_by("-created_at")

    return render(
        request,
        "physician/patient_detail.html",
        {"patient": patient, "records": records},
    )
