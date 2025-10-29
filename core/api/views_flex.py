# core/api/views_flex.py
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PhysicianProfile
from core.utils.availability import get_available_slots
from core.utils.calendar import (
    get_booked_blocks_for_calendar,
    filter_available_presliced_slots,  # kept if you still use elsewhere
)
from .serializers import (
    SlotQuerySerializer,
    FlexAppointmentCreateSerializer,
    FlexAppointmentReadSerializer,
)

User = get_user_model()


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
    """
    Accepts either:
      - User.id (UUID of the auth user who is a physician), or
      - PhysicianProfile.public_id (UUID shown in your UI).
    Returns the physician's User object.
    """
    try:
        prof = PhysicianProfile.objects.select_related("user").get(public_id=identifier)
        return prof.user
    except PhysicianProfile.DoesNotExist:
        pass
    return get_object_or_404(User, id=identifier)


class AvailableSlotsView(APIView):
    """
    GET /api/clinic/slots/?physician_id=<uuid>&date=YYYY-MM-DD&duration_minutes=30
    Returns:
      - available start datetimes (ISO) for that duration
      - booked blocks (with patient names) for coloring in UI
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        s = SlotQuerySerializer(data=request.query_params)
        s.is_valid(raise_exception=True)

        physician_user = _resolve_physician_user(str(s.validated_data["physician_id"]))
        the_date = s.validated_data["date"]
        duration = s.validated_data["duration_minutes"]

        # NOTE: get_available_slots(physician, date_obj, duration_minutes) expects positional args
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


class CalendarEventsView(APIView):
    """
    FullCalendar data source (green AVAILABLE + red BOOKED).
    Supports ?duration=<minutes> to render 30/45/60-min availability windows.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, physician_id):
        physician_user = _resolve_physician_user(str(physician_id))

        # FullCalendar sends an ISO range; we also accept a custom ?duration=
        start_str = request.GET.get("start")
        end_str = request.GET.get("end")
        try:
            duration = int(request.GET.get("duration", 30))
            if duration <= 0:
                raise ValueError
        except ValueError:
            return Response({"error": "duration must be a positive integer (minutes)."}, status=400)

        if not start_str or not end_str:
            return Response({"error": "start and end are required ISO datetimes"}, status=400)

        start = parse_datetime(start_str)
        end = parse_datetime(end_str)
        if not start or not end:
            return Response({"error": "Invalid start/end format"}, status=400)

        tz = timezone.get_current_timezone()
        if timezone.is_naive(start):
            start = timezone.make_aware(start, tz)
        if timezone.is_naive(end):
            end = timezone.make_aware(end, tz)

        # -------- red (booked) blocks: legacy + flex --------
        booked = get_booked_blocks_for_calendar(
            physician_user=physician_user,
            start=start,
            end=end,
        )
        for ev in booked:
            ev["backgroundColor"] = "#e74c3c"
            ev["borderColor"] = ev["backgroundColor"]
            ev["display"] = "auto"
            ev["extendedProps"] = {
                "type": ev.pop("type", "BOOKED"),
                "patient_name": ev.pop("patient_name", ""),
                "status": ev.pop("status", ""),
            }

        # -------- green (available) blocks: duration-aware from windows/overrides --------
        cur = start.date()
        stop = end.date()
        available = []
        while cur < stop:
            # NOTE: positional call to match signature
            for s in get_available_slots(physician_user, cur, duration):
                e = s + timedelta(minutes=duration)
                # keep only those that actually intersect [start, end)
                if not (s < end and e > start):
                    continue
                available.append({
                    "id": f"avail-{cur.isoformat()}-{s.isoformat()}",
                    "title": f"{s.astimezone(tz).strftime('%H:%M')} - {e.astimezone(tz).strftime('%H:%M')} - Available",
                    "start": s.isoformat(),
                    "end": e.isoformat(),
                    "backgroundColor": "#2ecc71",
                    "borderColor": "#2ecc71",
                    "display": "auto",
                    "extendedProps": {"type": "AVAILABLE"},
                })
            cur += timedelta(days=1)

        return Response(available + booked, status=200)


class FlexAppointmentCreateView(APIView):
    """
    POST /api/clinic/flex-appointments/
    {
      "physician": "<uuid>",           # User.id OR PhysicianProfile.public_id
      "start": "2025-10-28T10:30:00-04:00",
      "duration_minutes": 30,
      "notes": "First visit"
    }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ser = FlexAppointmentCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        appt = ser.save()  # model logic prevents overlaps and blocks pre-sliced slots
        return Response(FlexAppointmentReadSerializer(appt).data, status=status.HTTP_201_CREATED)
