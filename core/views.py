from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.generic import FormView, TemplateView
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django.urls import reverse
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.http import Http404
import secrets
import json

from datetime import datetime, time, timedelta, timezone as dt_timezone

from .models import (
    User,
    PatientProfile,
    PhysicianProfile,
    HealthRecord,
    AvailabilitySlot,        # legacy (pre-sliced)
    Appointment,             # legacy (pre-sliced)
    Conversation,
    Message,
    PhysicianDateOverride,
    FlexAppointment,
)
from .forms import (
    PatientSignUpForm as PatientSignupForm,
    PhysicianSignUpForm as PhysicianSignupForm,
    PatientProfileForm,
    HealthRecordForm,
)

# Flexible availability (weekly windows + overrides)
from core.utils.availability import get_available_slots


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
                # ensure role is physician
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
    """Send the user to the correct dashboard based on role/profile."""
    user = request.user

    try:
        if callable(getattr(user, "is_physician", None)) and user.is_physician():
            return redirect("physician_dashboard")
        if callable(getattr(user, "is_patient", None)) and user.is_patient():
            return redirect("patient_dashboard")
    except Exception:
        pass

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

        # for template: enables drag-to-create windows
        try:
            ctx["is_physician"] = bool(user.is_physician())
        except Exception:
            ctx["is_physician"] = False

        ctx["default_physician_id"] = default_physician_id
        return ctx


def _coerce_date(s: str):
    """
    Accepts 'YYYY-MM-DD' or ISO datetimes like 'YYYY-MM-DDTHH:MM:SSZ'.
    Returns a date or None.
    """
    if not s:
        return None
    d = parse_date(s)
    if d:
        return d
    dt = parse_datetime(s)
    if dt:
        return dt.date()
    if "T" in s:
        d2 = parse_date(s.split("T", 1)[0])
        if d2:
            return d2
    return None


@login_required
def physician_slots_json(request, physician_id):
    """
    Returns dynamic available starts for a physician.
    Query:
      - ?date=YYYY-MM-DD
      - OR ?start=<iso>&end=<iso>  (FullCalendar will pass these; end exclusive)
      - &duration=<minutes>  (default 30)
    """
    try:
        physician = User.objects.get(id=physician_id)
    except User.DoesNotExist:
        return JsonResponse({"error": "Physician not found."}, status=404)

    try:
        duration = int(request.GET.get("duration", 30))
        if duration <= 0:
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "duration must be a positive integer (minutes)."}, status=400)

    date_param = request.GET.get("date")
    start_param = request.GET.get("start")
    end_param = request.GET.get("end")

    events = []

    # 1) single-day
    if date_param:
        d = _coerce_date(date_param)
        if not d:
            return JsonResponse({"error": "Invalid 'date'."}, status=400)
        for s in get_available_slots(physician, d, duration):
            e = s + timedelta(minutes=duration)
            events.append({"title": f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')} Available",
                           "start": s.isoformat(), "end": e.isoformat(), "color": "#00a65a"})
        return JsonResponse(events, safe=False)

    # 2) range (FullCalendar)
    if start_param and end_param:
        start_d = _coerce_date(start_param)
        end_d = _coerce_date(end_param)
        if not start_d or not end_d:
            return JsonResponse({"error": "Invalid 'start' or 'end'."}, status=400)
        cur = start_d
        while cur < end_d:
            for s in get_available_slots(physician, cur, duration):
                e = s + timedelta(minutes=duration)
                events.append({"title": f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')} Available",
                               "start": s.isoformat(), "end": e.isoformat(), "color": "#00a65a"})
            cur += timedelta(days=1)
        return JsonResponse(events, safe=False)

    # 3) fallback today
    today = timezone.localdate()
    for s in get_available_slots(physician, today, duration):
        e = s + timedelta(minutes=duration)
        events.append({"title": f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')} Available",
                       "start": s.isoformat(), "end": e.isoformat(), "color": "#00a65a"})
    return JsonResponse(events, safe=False)


# ---------- helpers for slot creation

def _overlap_q(start, end) -> Q:
    """ORM Q that matches anything overlapping [start, end)."""
    return Q(start__lt=end) & Q(end__gt=start)


def _aware(dt: datetime) -> datetime:
    """Make datetime timezone-aware in current TZ if naive."""
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


# Physician creates an ad-hoc FREE window by dragging on the calendar
@require_http_methods(["POST"])
@login_required
def add_availability_window(request, physician_id):
    """
    Body JSON: { "start": ISOString, "end": ISOString, "step_minutes": 30 }
    Creates concrete AvailabilitySlot rows (default 30-min slices) for the
    dragged window. We skip:
      - past slices
      - slices overlapping existing AvailabilitySlot
      - slices overlapping any Appointment/FlexAppointment
    """
    # only that physician (or staff) can create their windows
    if str(request.user.id) != str(physician_id) and not request.user.is_staff:
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "invalid json"}, status=400)

    start_dt = parse_datetime(payload.get("start") or "")
    end_dt = parse_datetime(payload.get("end") or "")
    if not start_dt or not end_dt:
        return JsonResponse({"error": "Invalid datetime format."}, status=400)

    start_dt = _aware(start_dt)
    end_dt = _aware(end_dt)

    if end_dt <= start_dt:
        return JsonResponse({"error": "End must be after start."}, status=400)

    # Keep within a single calendar day (to simplify slicing)
    if start_dt.date() != end_dt.date():
        return JsonResponse({"error": "Window must be within a single day."}, status=400)

    # Slicing granularity
    try:
        step_minutes = int(payload.get("step_minutes", 30))
        if step_minutes <= 0:
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "step_minutes must be a positive integer."}, status=400)

    step = timedelta(minutes=step_minutes)
    now = timezone.now()

    # Pre-fetch booked blocks to test overlap quickly
    booked_flex = list(
        FlexAppointment.objects.filter(
            physician_id=physician_id,
            status__in=[FlexAppointment.Status.PENDING, FlexAppointment.Status.CONFIRMED],
        ).filter(_overlap_q(start_dt, end_dt)).values("start", "end")
    )
    booked_legacy = list(
        Appointment.objects.filter(
            physician_id=physician_id,
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
            slot__start__lt=end_dt,
            slot__end__gt=start_dt,
        ).select_related("slot").values("slot__start", "slot__end")
    )

    def conflicts_with_booked(s, e) -> bool:
        for b in booked_flex:
            if b["start"] < e and b["end"] > s:
                return True
        for b in booked_legacy:
            if b["slot__start"] < e and b["slot__end"] > s:
                return True
        return False

    created = 0
    with transaction.atomic():
        cur = start_dt
        while cur + step <= end_dt:
            s = cur
            e = cur + step

            # skip past slices
            if e <= now:
                cur += step
                continue

            # skip if overlaps any booked block
            if conflicts_with_booked(s, e):
                cur += step
                continue

            # skip if an AvailabilitySlot already overlaps
            exists = AvailabilitySlot.objects.filter(
                physician_id=physician_id
            ).filter(_overlap_q(s, e)).exists()
            if not exists:
                AvailabilitySlot.objects.create(
                    physician_id=physician_id,
                    start=s,
                    end=e,
                    is_booked=False,
                )
                created += 1

            cur += step

    # (Optional) keep your date override record if you still want it for reference:
    PhysicianDateOverride.objects.get_or_create(
        physician_id=physician_id,
        date=start_dt.date(),
        is_closed=False,
        start_time=start_dt.astimezone(timezone.get_current_timezone()).time(),
        end_time=end_dt.astimezone(timezone.get_current_timezone()).time(),
    )

    return JsonResponse({"ok": True, "created": created})


# =========================
# LEGACY: fixed-slot booking (kept for backward-compat)
# =========================

@require_POST
@login_required
def create_appointment(request):
    """
    Unified booking endpoint.

    Two modes:
    1) Legacy fixed-slot (30 min):
       form or JSON: {"slot_id": "<uuid>"}
       -> creates Appointment, marks slot.is_booked = True

    2) Flexible duration (e.g., 45/60 min):
       JSON: {
         "physician": "<uuid>",                # required
         "start": "2025-10-30T13:00:00-04:00", # required, ISO
         "duration": 45,                       # minutes, required
         "notes": "optional"
       }
       -> creates FlexAppointment and blocks overlapping AvailabilitySlots.
    """
    # --- read body safely (form or JSON) ---
    payload = {}
    if request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            return HttpResponseBadRequest("invalid json")

    slot_id = request.POST.get("slot_id") or payload.get("slot_id")

    # =========================================================
    # MODE 1: Fixed pre-sliced appointment by slot_id (unchanged)
    # =========================================================
    if slot_id:
        slot = get_object_or_404(AvailabilitySlot, id=slot_id)

        if slot.is_booked:
            return HttpResponseBadRequest("This slot is already booked.")
        if slot.start <= timezone.now():
            return HttpResponseBadRequest("Cannot book a past slot.")

        me = request.user
        try:
            if hasattr(me, "is_physician") and me.is_physician():
                return HttpResponseBadRequest("Physicians cannot book appointments here.")
        except Exception:
            pass

        # patient can't overlap their own bookings (legacy + flex)
        overlaps_legacy = Appointment.objects.filter(
            patient=me,
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
            slot__start__lt=slot.end,
            slot__end__gt=slot.start,
        ).exists()
        overlaps_flex = FlexAppointment.objects.filter(
            patient=me,
            status__in=[FlexAppointment.Status.PENDING, FlexAppointment.Status.CONFIRMED],
            start__lt=slot.end,
            end__gt=slot.start,
        ).exists()
        if overlaps_legacy or overlaps_flex:
            return HttpResponseBadRequest("You already have an appointment overlapping this time.")

        appt = Appointment.objects.create(
            slot=slot,
            physician=slot.physician,
            patient=me,
            status=Appointment.Status.CONFIRMED,
            notes=(request.POST.get("notes") or payload.get("notes") or ""),
        )
        slot.is_booked = True
        slot.save(update_fields=["is_booked"])

        Conversation.objects.get_or_create(physician=slot.physician, patient=me)

        return JsonResponse({
            "ok": True,
            "mode": "fixed",
            "appointment_id": str(appt.id),
            "physician": str(appt.physician_id),
            "slot": {"start": slot.start.isoformat(), "end": slot.end.isoformat()},
            "status": appt.status,
        })

    # =========================================================
    # MODE 2: Flexible duration (45/60/etc.) by start + duration
    # =========================================================
    physician_id = payload.get("physician")
    start_str    = payload.get("start")
    duration_min = payload.get("duration")

    if not (physician_id and start_str and duration_min):
        return HttpResponseBadRequest(
            "For flexible booking provide JSON with physician, start (ISO), and duration (minutes)."
        )

    try:
        duration_min = int(duration_min)
        if duration_min <= 0:
            raise ValueError
    except ValueError:
        return HttpResponseBadRequest("duration must be a positive integer (minutes).")

    physician = get_object_or_404(User, id=physician_id)

    start_dt = parse_datetime(start_str)
    if not start_dt:
        return HttpResponseBadRequest("Invalid start datetime format.")
    if timezone.is_naive(start_dt):
        start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())

    end_dt = start_dt + timedelta(minutes=duration_min)
    now = timezone.now()
    if end_dt <= now:
        return HttpResponseBadRequest("Cannot book a past time range.")

    me = request.user
    try:
        if hasattr(me, "is_physician") and me.is_physician():
            return HttpResponseBadRequest("Physicians cannot book appointments here.")
    except Exception:
        pass

    # --------- overlap guards (patient + physician, legacy + flex) ----------
    overlap_q = Q(start__lt=end_dt) & Q(end__gt=start_dt)

    patient_overlap = (
        Appointment.objects.filter(
            patient=me,
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
            slot__start__lt=end_dt,
            slot__end__gt=start_dt,
        ).exists()
        or
        FlexAppointment.objects.filter(
            patient=me,
            status__in=[FlexAppointment.Status.PENDING, FlexAppointment.Status.CONFIRMED],
        ).filter(overlap_q).exists()
    )
    if patient_overlap:
        return HttpResponseBadRequest("You already have an appointment overlapping this time range.")

    physician_overlap = (
        Appointment.objects.filter(
            physician=physician,
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
            slot__start__lt=end_dt,
            slot__end__gt=start_dt,
        ).exists()
        or
        FlexAppointment.objects.filter(
            physician=physician,
            status__in=[FlexAppointment.Status.PENDING, FlexAppointment.Status.CONFIRMED],
        ).filter(overlap_q).exists()
    )
    if physician_overlap:
        return HttpResponseBadRequest("Physician is not available for that time range.")

    # --------- create flex appointment ----------
    f = FlexAppointment.objects.create(
        physician=physician,
        patient=me,
        start=start_dt,
        end=end_dt,
        status=FlexAppointment.Status.CONFIRMED,
        notes=(payload.get("notes") or ""),
    )

    # --------- block any pre-sliced AvailabilitySlots that intersect ----------
    AvailabilitySlot.objects.filter(
        physician=physician
    ).filter(
        Q(start__lt=end_dt) & Q(end__gt=start_dt)
    ).update(is_booked=True)

    Conversation.objects.get_or_create(physician=physician, patient=me)

    return JsonResponse({
        "ok": True,
        "mode": "flex",
        "appointment_id": str(f.id),
        "physician": str(f.physician_id),
        "start": f.start.isoformat(),
        "end": f.end.isoformat(),
        "status": f.status,
    })


# =========================
# NEW INDEPENDENT CHAT (Inbox + New + StartWithUser + Thread + Send + Poll)
# =========================

def _chat_guard(convo, user):
    if user.id not in {convo.patient_id, convo.physician_id}:
        raise Http404("Not a participant.")

def _resolve_roles_for_pair(me: User, peer: User):
    """
    Return (patient_user, physician_user) or raise Http404 for invalid role combos.
    Blocks self-DM and non patient↔physician pairs.
    """
    if me.id == peer.id:
        raise Http404("Cannot start a conversation with yourself.")

    # Prefer explicit roles
    if hasattr(User, "Roles"):
        me_role = getattr(me, "role", None)
        peer_role = getattr(peer, "role", None)
        if me_role == User.Roles.PATIENT and peer_role == User.Roles.PHYSICIAN:
            return (me, peer)
        if me_role == User.Roles.PHYSICIAN and peer_role == User.Roles.PATIENT:
            return (peer, me)

    # Fallback to helpers if roles are missing on one of them
    try:
        if callable(getattr(me, "is_patient", None)) and me.is_patient() and \
           callable(getattr(peer, "is_physician", None)) and peer.is_physician():
            return (me, peer)
        if callable(getattr(me, "is_physician", None)) and me.is_physician() and \
           callable(getattr(peer, "is_patient", None)) and peer.is_patient():
            return (peer, me)
    except Exception:
        pass

    raise Http404("Invalid role pairing for conversation (must be patient ↔ physician).")

@login_required
def chat_inbox(request):
    """List all conversations for the logged-in user."""
    convos = Conversation.objects.filter(
        Q(patient=request.user) | Q(physician=request.user)
    ).order_by("-updated_at")
    return render(request, "messaging/inbox.html", {"conversations": convos})

@login_required
def chat_new(request):
    """
    Choose someone to message BEFORE any appointment exists.
    Patients see physicians; physicians see patients.
    Supports ?q= search by username/full_name/first/last/phone.
    """
    q = (request.GET.get("q") or "").strip()
    me = request.user

    # patient → show physicians
    try:
        if hasattr(me, "is_patient") and me.is_patient():
            qs = User.objects.filter(
                Q(physicianprofile__isnull=False)
            ).exclude(id=me.id)

            if q:
                qs = qs.filter(
                    Q(username__icontains=q) |
                    Q(first_name__icontains=q) |
                    Q(last_name__icontains=q)  |
                    Q(physicianprofile__full_name__icontains=q)
                )

            qs = qs.select_related("physicianprofile").order_by("username")[:50]
            return render(request, "messaging/new.html",
                          {"peers": qs, "mode": "patient_to_physician", "q": q})
    except Exception:
        pass

    # physician → show patients
    try:
        if hasattr(me, "is_physician") and me.is_physician():
            base = User.objects.filter(Q(patientprofile__isnull=False)).exclude(id=me.id)

            if q:
                # broad search across username, names, and patient profile fields
                qs = base.filter(
                    Q(username__icontains=q) |
                    Q(first_name__icontains=q) |
                    Q(last_name__icontains=q)  |
                    Q(patientprofile__full_name__icontains=q) |
                    Q(patientprofile__phone__icontains=q)
                )
            else:
                # no query → show this physician's linked patients first
                qs = base.filter(patientprofile__physician__user=me)

            qs = qs.select_related("patientprofile").order_by("username")[:50]
            return render(request, "messaging/new.html",
                          {"peers": qs, "mode": "physician_to_patient", "q": q})
    except Exception:
        pass

    # fallback
    return render(request, "messaging/new.html",
                  {"peers": User.objects.none(), "mode": "unknown", "q": q})

@login_required
def chat_start_with_user(request, peer_id):
    """
    Start (or open) a 1:1 between the current user and `peer_id`, regardless of appointments.
    """
    me = request.user
    peer = get_object_or_404(User, pk=peer_id)

    patient_user, physician_user = _resolve_roles_for_pair(me, peer)
    convo, _ = Conversation.objects.get_or_create(patient=patient_user, physician=physician_user)
    return redirect("chat_thread", pk=convo.pk)

@login_required
def chat_start_or_open(request, patient_id, physician_id):
    """
    Create (if needed) the 1:1 thread for patient+physician and redirect to it.
    Works even with no appointment.
    """
    patient = get_object_or_404(User, pk=patient_id)
    physician = get_object_or_404(User, pk=physician_id)

    # sanity on roles (optional)
    if hasattr(User, "Roles"):
        if getattr(patient, "role", None) != getattr(User.Roles, "PATIENT", "PATIENT") or \
           getattr(physician, "role", None) != getattr(User.Roles, "PHYSICIAN", "PHYSICIAN"):
            raise Http404("Invalid roles for chat.")

    convo, _ = Conversation.objects.get_or_create(patient=patient, physician=physician)
    return redirect("chat_thread", pk=convo.pk)

@login_required
def chat_thread(request, pk):
    """Render the thread with messages."""
    convo = get_object_or_404(Conversation, pk=pk)
    _chat_guard(convo, request.user)

    msgs = convo.messages.select_related("sender").order_by("created_at")

    # Initialize last_ts with the timestamp (epoch seconds) of the latest message
    if msgs.exists():
        last_dt = msgs.last().created_at
        # ensure aware => convert to epoch seconds safely
        if timezone.is_naive(last_dt):
            last_dt = timezone.make_aware(last_dt, timezone.get_current_timezone())
        last_ts = last_dt.timestamp()
    else:
        last_ts = 0

    return render(
        request,
        "messaging/thread.html",
        {"convo": convo, "messages": msgs, "last_ts": last_ts},
    )

@login_required
@require_POST
def chat_send(request, pk):
    """Post a new message to a conversation."""
    convo = get_object_or_404(Conversation, pk=pk)
    _chat_guard(convo, request.user)

    body = (request.POST.get("body") or "").strip()
    file = request.FILES.get("attachment")
    if not body and not file:
        return redirect("chat_thread", pk=pk)

    Message.objects.create(conversation=convo, sender=request.user, body=body, attachment=file)
    # bump the inbox ordering
    Conversation.objects.filter(pk=pk).update(updated_at=timezone.now())
    return redirect("chat_thread", pk=pk)

@login_required
def chat_fetch_since(request, pk, ts):
    """
    Lightweight polling endpoint.
    Client calls with last-seen epoch seconds and receives new messages.
    """
    convo = get_object_or_404(Conversation, pk=pk)
    _chat_guard(convo, request.user)

    # ts comes from URL as a string; coerce safely.
    try:
        ts_val = float(ts)
        if ts_val < 0:
            ts_val = 0.0
    except (TypeError, ValueError):
        ts_val = 0.0

    # Use Python's datetime timezone to build an aware timestamp in UTC
    since_dt = datetime.fromtimestamp(ts_val, tz=dt_timezone.utc)

    new_msgs = (
        convo.messages
        .filter(created_at__gt=since_dt)
        .select_related("sender")
        .order_by("created_at")
    )

    data = [
        {
            "id": str(m.id),
            "body": m.body,
            "sender": str(m.sender_id),
            "sender_username": m.sender.username,
            "created": m.created_at.isoformat(),
            "attachment_url": m.attachment.url if getattr(m, "attachment", None) else None,
        }
        for m in new_msgs
    ]
    return JsonResponse({"messages": data, "server_time": timezone.now().timestamp()})


# =========================
# LEGACY CHAT (kept)
# =========================

@login_required
def chat_room(request, peer_id):
    """Open (or create) the conversation between the current user and `peer_id`."""
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
    """GET → list messages; POST → create a new message (body: {"content": "..."})"""
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
    Patients → list ALL their appointments (legacy + flex), newest first.
    Physicians → upcoming (next 30 days) by default; `?scope=today` to see only today.
    We normalize both models into one list of items for the template.
    """
    user = request.user
    now = timezone.now()
    tz = timezone.get_current_timezone()

    def _row(start_dt, end_dt, peer_user, status, conversation_peer_id):
        # normalize to current tz
        if timezone.is_aware(start_dt):
            start_local = start_dt.astimezone(tz)
        else:
            start_local = timezone.make_aware(start_dt, tz)
        if timezone.is_aware(end_dt):
            end_local = end_dt.astimezone(tz)
        else:
            end_local = timezone.make_aware(end_dt, tz)

        return {
            "date_str": start_local.strftime("%b %d, %Y"),
            "time_str": f"{start_local.strftime('%H:%M')} – {end_local.strftime('%H:%M')}",
            "peer_name": getattr(peer_user, "username", str(peer_user)),
            "status": status,
            "chat_url": reverse("chat-room", args=[conversation_peer_id]),
            "sort_key": start_local,
        }

    items = []

    # ---------------------------
    # Physician or Patient branch
    # ---------------------------
    is_physician = bool(getattr(user, "is_physician", lambda: False)())

    if is_physician:
        scope = (request.GET.get("scope") or "upcoming").lower()
        today = timezone.localdate(now)
        start_today = timezone.make_aware(datetime.combine(today, time.min), tz)
        end_today = start_today + timedelta(days=1)

        # Legacy upcoming
        if scope == "today":
            legacy_qs = Appointment.objects.filter(
                physician=user, slot__start__gte=start_today, slot__start__lt=end_today
            ).select_related("patient", "slot")
        else:
            legacy_qs = Appointment.objects.filter(
                physician=user, slot__start__gte=now, slot__start__lte=now + timedelta(days=30)
            ).select_related("patient", "slot")

        for appt in legacy_qs.order_by("slot__start"):
            items.append(
                _row(
                    appt.slot.start, appt.slot.end,
                    appt.patient, appt.status,
                    conversation_peer_id=appt.patient_id,
                )
            )

        # Flex (mirror same scope)
        if scope == "today":
            flex_qs = FlexAppointment.objects.filter(
                physician=user, start__gte=start_today, start__lt=end_today
            ).select_related("patient")
            title = "Today's Appointments"
        else:
            flex_qs = FlexAppointment.objects.filter(
                physician=user, start__gte=now, start__lte=now + timedelta(days=30)
            ).select_related("patient")
            title = "Upcoming Appointments (next 30 days)"

        for f in flex_qs.order_by("start"):
            items.append(
                _row(
                    f.start, f.end,
                    f.patient, getattr(f, "status", "CONFIRMED"),
                    conversation_peer_id=f.patient_id,
                )
            )

        peer_header = "Patient"
    else:
        # Patient view: show all (future first, but include past)
        legacy_qs = Appointment.objects.filter(
            patient=user
        ).select_related("physician", "slot").order_by("slot__start")

        for appt in legacy_qs:
            items.append(
                _row(
                    appt.slot.start, appt.slot.end,
                    appt.physician, appt.status,
                    conversation_peer_id=appt.physician_id,
                )
            )

        flex_qs = FlexAppointment.objects.filter(
            patient=user
        ).select_related("physician").order_by("start")

        for f in flex_qs:
            items.append(
                _row(
                    f.start, f.end,
                    f.physician, getattr(f, "status", "CONFIRMED"),
                    conversation_peer_id=f.physician_id,
                )
            )

        title = "My Appointments"
        peer_header = "Physician"

    # sort ascending by start time (change to reverse=True if you want newest-first)
    items.sort(key=lambda r: r["sort_key"], reverse=False)

    return render(
        request,
        "appointments_list.html",
        {"items": items, "title": title, "peer_header": peer_header},
    )
