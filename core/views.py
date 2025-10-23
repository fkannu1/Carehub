from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.generic import FormView, TemplateView
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
import secrets
import json

from datetime import datetime, time, timedelta

from .models import (
    User,
    PatientProfile,
    PhysicianProfile,
    HealthRecord,
    AvailabilitySlot,
    Appointment,
    Conversation,
    Message,
)
from .forms import (
    PatientSignUpForm as PatientSignupForm,
    PhysicianSignUpForm as PhysicianSignupForm,  # <- use the alias consistently
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
        form = PhysicianSignupForm(request.POST)  # <- fixed name
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=True)
                # ensure role is physician when using custom role field
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
    try:
        if request.user.is_physician():
            return redirect("physician_dashboard")
    except Exception:
        pass

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
    try:
        if request.user.is_patient():
            return redirect("patient_dashboard")
    except Exception:
        pass

    physician, _ = PhysicianProfile.objects.get_or_create(user=request.user)

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
    try:
        if request.user.is_patient():
            messages.error(request, "Only physicians can regenerate a connect code.")
            return redirect("patient_dashboard")
    except Exception:
        pass

    physician, _ = PhysicianProfile.objects.get_or_create(user=request.user)
    physician.connect_code = secrets.token_hex(4)  # 8 chars
    physician.save(update_fields=["connect_code"])
    messages.success(request, "New connect code generated.")
    return redirect("physician_dashboard")


# =========================
# CALENDAR / APPOINTMENTS
# =========================

@method_decorator(login_required, name="dispatch")
class CalendarView(TemplateView):
    template_name = "calendar.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        default_physician_id = None

        try:
            if hasattr(user, "is_physician") and user.is_physician():
                default_physician_id = str(user.id)
            elif hasattr(user, "is_patient") and user.is_patient():
                patient = PatientProfile.objects.filter(user=user).first()
                if patient and patient.physician and patient.physician.user:
                    default_physician_id = str(patient.physician.user.id)
        except Exception:
            pass

        ctx["default_physician_id"] = default_physician_id
        return ctx


@login_required
def physician_slots_json(request, physician_id):
    physician = get_object_or_404(User, id=physician_id)
    now = timezone.now()
    qs = (
        AvailabilitySlot.objects
        .filter(physician=physician, end__gte=now, is_booked=False)
        .order_by("start")
        .values("id", "start", "end")
    )
    slots = [
        {
            "id": str(row["id"]),
            "start": row["start"].isoformat(),
            "end": row["end"].isoformat(),
        }
        for row in qs
    ]
    return JsonResponse({"slots": slots})


@require_POST
@login_required
def create_appointment(request):
    slot_id = request.POST.get("slot_id")
    if not slot_id and request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
            slot_id = payload.get("slot_id")
        except Exception:
            pass

    if not slot_id:
        return HttpResponseBadRequest("slot_id is required")

    slot = get_object_or_404(AvailabilitySlot, id=slot_id)
    if slot.is_booked:
        return HttpResponseBadRequest("This slot is already booked.")
    if slot.start <= timezone.now():
        return HttpResponseBadRequest("Cannot book a past slot.")

    user = request.user
    try:
        if hasattr(user, "is_physician") and user.is_physician():
            return HttpResponseBadRequest("Physicians cannot book appointments here.")
    except Exception:
        pass

    conflict_exists = Appointment.objects.filter(
        patient=user,
        status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
        slot__start__lt=slot.end,
        slot__end__gt=slot.start,
    ).exists()
    if conflict_exists:
        return HttpResponseBadRequest("You already have an appointment overlapping this time.")

    appt = Appointment.objects.create(
        slot=slot,
        physician=slot.physician,
        patient=user,
        status=Appointment.Status.CONFIRMED,
        notes="",
    )
    slot.is_booked = True
    slot.save(update_fields=["is_booked"])

    # ensure a conversation exists for this patient ↔ physician pair
    Conversation.objects.get_or_create(
        physician=slot.physician,
        patient=user,
    )

    return JsonResponse({
        "ok": True,
        "appointment_id": str(appt.id),
        "physician": str(appt.physician_id),
        "slot": {"start": slot.start.isoformat(), "end": slot.end.isoformat()},
        "status": appt.status,
    })


# =========================
# CHAT
# =========================

@login_required
def chat_room(request, peer_id):
    """
    Open (or create) the conversation between the current user and `peer_id`.
    Renders the chat room and passes existing messages.
    """
    peer = get_object_or_404(User, id=peer_id)
    me = request.user

    if hasattr(me, "is_physician") and me.is_physician():
        physician_user = me
        patient_user = peer
    else:
        physician_user = peer
        patient_user = me

    convo, _ = Conversation.objects.get_or_create(
        physician=physician_user,
        patient=patient_user,
    )

    messages_qs = Message.objects.filter(conversation=convo).select_related("sender").order_by("created_at")

    return render(request, "chat/room.html", {
        "peer": peer,
        "conversation": convo,
        "messages": messages_qs,
    })


@csrf_exempt  # allow simple fetch() without CSRF token
@login_required
def messages_json(request, conversation_id):
    """
    GET → list messages for a conversation
    POST → create a new message; body: {"content": "..."}
    """
    convo = get_object_or_404(Conversation, id=conversation_id)

    if request.method == "POST":
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"error": "invalid json"}, status=400)

        content = (payload.get("content") or "").strip()
        if not content:
            return JsonResponse({"error": "empty message"}, status=400)

        msg = Message.objects.create(conversation=convo, sender=request.user, body=content)
        return JsonResponse({
            "id": str(msg.id),
            "sender": msg.sender.username,
            "content": msg.body,
            "timestamp": msg.created_at.strftime("%H:%M"),
        })

    # GET -> list
    msgs = Message.objects.filter(conversation=convo).select_related("sender").order_by("created_at")
    data = [
        {
            "id": str(m.id),
            "sender": m.sender.username,
            "content": m.body,
            "timestamp": m.created_at.strftime("%H:%M"),
        }
        for m in msgs
    ]
    return JsonResponse({"messages": data})


# =========================
# APPOINTMENTS LIST PAGES
# =========================

@login_required
def my_appointments(request):
    """
    Patients → list ALL their appointments.
    Physicians → list UPCOMING (next 30 days) by default; `?scope=today` to see only today.
    """
    user = request.user
    now = timezone.now()

    if hasattr(user, "is_physician") and user.is_physician():
        scope = (request.GET.get("scope") or "upcoming").lower()

        tz = timezone.get_current_timezone()
        today = timezone.localdate(now)
        start_today = timezone.make_aware(datetime.combine(today, time.min), tz)
        end_today = start_today + timedelta(days=1)

        if scope == "today":
            qs = Appointment.objects.filter(
                physician=user,
                slot__start__gte=start_today,
                slot__start__lt=end_today,
            ).select_related("patient", "slot").order_by("slot__start")
            title = "Today's Appointments"
        else:
            end = now + timedelta(days=30)
            qs = Appointment.objects.filter(
                physician=user,
                slot__start__gte=now,
                slot__start__lte=end,
            ).select_related("patient", "slot").order_by("slot__start")
            title = "Upcoming Appointments (next 30 days)"
    else:
        # Patient: show all (future first)
        qs = Appointment.objects.filter(
            patient=user
        ).select_related("physician", "slot").order_by("slot__start")
        title = "My Appointments"

    return render(request, "appointments_list.html", {"appointments": qs, "title": title})