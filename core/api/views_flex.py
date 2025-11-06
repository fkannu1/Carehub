# core/api/views_flex.py
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db.models import Q

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view

from core.models import (
    PhysicianProfile,
    AvailabilitySlot,
    Appointment,
    FlexAppointment,
)
from core.utils.availability import get_available_slots
from core.utils.calendar import get_booked_blocks_for_calendar
from .serializers import (
    SlotQuerySerializer,
    FlexAppointmentCreateSerializer,
    FlexAppointmentReadSerializer,
)

User = get_user_model()


# ------------------ helpers ------------------

def _day_bounds_aware(d):
    tz = timezone.get_current_timezone()
    start_dt = datetime.combine(d, time.min)
    end_dt = datetime.combine(d, time.max)
    if timezone.is_naive(start_dt):
        start_dt = timezone.make_aware(start_dt, tz)
    if timezone.is_naive(end_dt):
        end_dt = timezone.make_aware(end_dt, tz)
    end_dt = end_dt + timedelta(microseconds=1)  # end exclusive
    return start_dt, end_dt


def _resolve_physician_user(identifier: str) -> User:
    """Accept User.id OR PhysicianProfile.public_id; return User."""
    try:
        prof = PhysicianProfile.objects.select_related("user").get(public_id=identifier)
        return prof.user
    except PhysicianProfile.DoesNotExist:
        pass
    return get_object_or_404(User, id=identifier)


def _overlap_q(start, end) -> Q:
    return Q(start__lt=end) & Q(end__gt=start)


# ------------------ simple auth endpoints (kept names) ------------------

@api_view(["GET"])
def api_csrf(request):
    # touching this view ensures the csrftoken cookie is issued
    from django.middleware.csrf import get_token
    get_token(request)
    return Response({"detail": "ok"})


@api_view(["GET"])
def api_me(request):
    user = request.user if request.user.is_authenticated else None
    return Response({
        "user": {"id": str(user.id), "username": user.username, "role": getattr(user, "role", "")} if user else None
    })


# ------------------ day helper + booking ------------------

class AvailableSlotsView(APIView):
    """
    GET /api/clinic/slots/?physician_id=<uuid or public_id>&date=YYYY-MM-DD&duration_minutes=30
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        s = SlotQuerySerializer(data=request.query_params)
        s.is_valid(raise_exception=True)

        physician_user = _resolve_physician_user(str(s.validated_data["physician_id"]))
        the_date = s.validated_data["date"]
        duration = s.validated_data["duration_minutes"]

        available_starts = get_available_slots(physician_user, the_date, duration)

        day_start, day_end = _day_bounds_aware(the_date)
        booked_blocks = get_booked_blocks_for_calendar(
            physician_user=physician_user,
            start=day_start,
            end=day_end,
        )

        return Response(
            {
                "physician": str(physician_user.id),
                "date": the_date.isoformat(),
                "available": [dt.isoformat() for dt in available_starts],
                "booked": booked_blocks,
            },
            status=status.HTTP_200_OK,
        )


class FlexAppointmentCreateView(APIView):
    """
    POST /api/clinic/flex-appointments/
    { "physician": "<uuid or public_id>", "start": ISO, "duration_minutes": 30, "notes": "" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ser = FlexAppointmentCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        appt = ser.save()
        return Response(FlexAppointmentReadSerializer(appt).data, status=status.HTTP_201_CREATED)


# ------------------ physician-scoped windows + events ------------------

class PhysicianSlotsView(APIView):
    """
    GET  /api/physicians/<uuid>/slots/             -> list raw AvailabilitySlot rows
    POST /api/physicians/<uuid>/slots/ {start,end} -> create one window (conflict-checked)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, physician_id):
        physician_user = _resolve_physician_user(str(physician_id))
        qs = AvailabilitySlot.objects.filter(physician=physician_user).order_by("start")
        data = [
            {"id": str(s.id), "start": s.start.isoformat(), "end": s.end.isoformat(), "is_booked": s.is_booked}
            for s in qs
        ]
        return Response(data, status=200)

    def post(self, request, physician_id):
        physician_user = _resolve_physician_user(str(physician_id))

        start = parse_datetime(request.data.get("start") or "")
        end   = parse_datetime(request.data.get("end")   or "")

        if not start or not end:
            return Response({"detail": "start and end are required ISO datetimes"}, status=400)
        if timezone.is_naive(start) or timezone.is_naive(end):
            return Response({"detail": "start/end must be timezone-aware ISO datetimes"}, status=400)
        if end <= start:
            return Response({"end": ["must be after start"]}, status=400)

        # Conflict checks (legacy appts, flex appts, existing slices)
        legacy_overlap = Appointment.objects.filter(
            physician=physician_user,
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
        ).filter(slot__start__lt=end, slot__end__gt=start).exists()

        flex_overlap = FlexAppointment.objects.filter(
            physician=physician_user,
            status__in=[FlexAppointment.Status.PENDING, FlexAppointment.Status.CONFIRMED],
        ).filter(_overlap_q(start, end)).exists()

        slice_overlap = AvailabilitySlot.objects.filter(
            physician=physician_user
        ).filter(_overlap_q(start, end)).exists()

        if legacy_overlap or flex_overlap or slice_overlap:
            return Response({"detail": "overlaps an existing booking or slot"}, status=400)

        # IMPORTANT: make the new slice *available* to patients
        slot = AvailabilitySlot.objects.create(
            physician=physician_user,
            start=start,
            end=end,
            is_booked=False,   # <<< key fix so it shows up as green on patient calendar
        )
        return Response({"id": str(slot.id), "start": slot.start.isoformat(), "end": slot.end.isoformat()}, status=201)


class CalendarEventsView(APIView):
    """
    GET /api/physicians/<uuid>/slots/events/?start=ISO&end=ISO&duration=30
    Returns FullCalendar-ready events:
      - GREEN availability (weekly windows/overrides via get_available_slots)
      - GREEN availability (concrete AvailabilitySlot rows, is_booked=False)
      - RED   booked blocks (legacy + flex)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, physician_id):
        physician_user = _resolve_physician_user(str(physician_id))

        start_str = request.GET.get("start")
        end_str   = request.GET.get("end")
        if not start_str or not end_str:
            return Response({"error": "start and end are required ISO datetimes"}, status=400)

        start = parse_datetime(start_str)
        end   = parse_datetime(end_str)
        if not start or not end:
            return Response({"error": "Invalid start/end format"}, status=400)

        tz = timezone.get_current_timezone()
        if timezone.is_naive(start): start = timezone.make_aware(start, tz)
        if timezone.is_naive(end):   end   = timezone.make_aware(end,   tz)

        try:
            duration = int(request.GET.get("duration", 30))
            if duration <= 0:
                raise ValueError
        except ValueError:
            return Response({"error": "duration must be a positive integer (minutes)."}, status=400)

        # ---------- RED (booked) ----------
        booked = get_booked_blocks_for_calendar(physician_user, start, end)
        for ev in booked:
            ev["backgroundColor"] = "#e74c3c"
            ev["borderColor"] = ev["backgroundColor"]
            ev["display"] = "auto"
            ev["extendedProps"] = {
                "type": ev.pop("type", "BOOKED"),
                "patient_name": ev.pop("patient_name", ""),
                "status": ev.pop("status", ""),
            }

        # ---------- GREEN (available) ----------
        available_events = {}

        # A) weekly windows / overrides (computed)
        cur = start.date()
        stop = end.date()
        while cur <= stop:
            for s in get_available_slots(physician_user, cur, duration):
                e = s + timedelta(minutes=duration)
                if not (s < end and e > start):
                    continue
                key = (s.isoformat(), e.isoformat())
                if key not in available_events:
                    available_events[key] = {
                        "id": f"avail-{cur.isoformat()}-{s.isoformat()}",
                        "title": f"{s.astimezone(tz).strftime('%H:%M')} - {e.astimezone(tz).strftime('%H:%M')} - Available",
                        "start": s.isoformat(),
                        "end": e.isoformat(),
                        "backgroundColor": "#2ecc71",
                        "borderColor": "#2ecc71",
                        "display": "auto",
                        "extendedProps": {"type": "AVAILABLE"},
                    }
            cur += timedelta(days=1)

        # B) concrete AvailabilitySlot rows (unbooked slices)
        legacy_slots = (
            AvailabilitySlot.objects
            .filter(physician=physician_user, is_booked=False)
            .filter(start__lt=end, end__gt=start)
        )

        for sl in legacy_slots:
            s = sl.start if timezone.is_aware(sl.start) else timezone.make_aware(sl.start, tz)
            e = sl.end   if timezone.is_aware(sl.end)   else timezone.make_aware(sl.end,   tz)
            key = (s.isoformat(), e.isoformat())
            if key not in available_events and (s < end and e > start):
                available_events[key] = {
                    "id": f"avail-row-{sl.id}",
                    "title": f"{s.astimezone(tz).strftime('%H:%M')} - {e.astimezone(tz).strftime('%H:%M')} - Available",
                    "start": s.isoformat(),
                    "end": e.isoformat(),
                    "backgroundColor": "#2ecc71",
                    "borderColor": "#2ecc71",
                    "display": "auto",
                    "extendedProps": {"type": "AVAILABLE_ROW"},
                }

        return Response(list(available_events.values()) + booked, status=200)


class MyAppointmentsView(APIView):
    """
    GET /api/appointments/mine/
    Unified list (legacy + flex) for the logged-in user, as JSON.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        now = timezone.now()
        tz = timezone.get_current_timezone()

        def row(start_dt, end_dt, peer_user, status, chat_peer_id):
            s = start_dt.astimezone(tz) if timezone.is_aware(start_dt) else timezone.make_aware(start_dt, tz)
            e = end_dt.astimezone(tz)   if timezone.is_aware(end_dt)   else timezone.make_aware(end_dt,   tz)
            return {
                "date_str": s.strftime("%b %d, %Y"),
                "time_str": f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')}",
                "peer_name": getattr(peer_user, "username", str(peer_user)),
                "status": status,
                "chat_url": reverse("chat-room", args=[chat_peer_id]),
                "sort_key": s.isoformat(),
            }

        items = []

        # Physician?
        is_phys = False
        try:
            is_phys = bool(getattr(user, "is_physician", lambda: False)())
        except Exception:
            pass

        if is_phys:
            legacy_qs = (
                Appointment.objects.filter(
                    physician=user, slot__start__gte=now, slot__start__lte=now + timedelta(days=30)
                ).select_related("patient", "slot").order_by("slot__start")
            )
            flex_qs = (
                FlexAppointment.objects.filter(
                    physician=user, start__gte=now, start__lte=now + timedelta(days=30)
                ).select_related("patient").order_by("start")
            )

            for appt in legacy_qs:
                items.append(row(appt.slot.start, appt.slot.end, appt.patient, appt.status, appt.patient_id))
            for f in flex_qs:
                items.append(row(f.start, f.end, f.patient, getattr(f, "status", "CONFIRMED"), f.patient_id))

        else:
            legacy_qs = (
                Appointment.objects.filter(patient=user)
                .select_related("physician", "slot")
                .order_by("slot__start")
            )
            flex_qs = (
                FlexAppointment.objects.filter(patient=user)
                .select_related("physician")
                .order_by("start")
            )

            for appt in legacy_qs:
                items.append(row(appt.slot.start, appt.slot.end, appt.physician, appt.status, appt.physician_id))
            for f in flex_qs:
                items.append(row(f.start, f.end, f.physician, getattr(f, "status", "CONFIRMED"), f.physician_id))

        items.sort(key=lambda r: r["sort_key"])
        return Response(items, status=status.HTTP_200_OK)
