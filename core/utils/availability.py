# core/utils/availability.py
# Show ONLY persisted AvailabilitySlot rows (no virtual generation)

from __future__ import annotations
from datetime import datetime, time as dtime, timedelta
from typing import List
from django.utils import timezone
from django.db.models import Q
from core.models import AvailabilitySlot, Appointment, FlexAppointment

def _local_tz():
    return timezone.get_current_timezone()

def _aware_local(date_obj, t: dtime) -> datetime:
    dt = datetime.combine(date_obj, t)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, _local_tz())
    else:
        dt = dt.astimezone(_local_tz())
    return dt

def _has_conflict(physician_user, start_dt: datetime, end_dt: datetime) -> bool:
    # legacy (slot-based) appointments
    legacy_overlap = Appointment.objects.filter(
        physician=physician_user,
        status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
        slot__start__lt=end_dt,
        slot__end__gt=start_dt,
    ).exists()
    if legacy_overlap:
        return True

    # flexible appointments
    flex_overlap = FlexAppointment.objects.filter(
        physician=physician_user,
        status__in=[FlexAppointment.Status.PENDING, FlexAppointment.Status.CONFIRMED],
    ).filter(Q(start__lt=end_dt) & Q(end__gt=start_dt)).exists()
    if flex_overlap:
        return True

    # pre-sliced availability that has been marked booked
    booked_slice_overlap = AvailabilitySlot.objects.filter(
        physician=physician_user, is_booked=True
    ).filter(start__lt=end_dt, end__gt=start_dt).exists()

    return booked_slice_overlap

def get_available_slots(physician_user, date_obj, slot_minutes: int) -> List[datetime]:
    """
    Return candidate start datetimes derived ONLY from manual AvailabilitySlot rows
    (is_booked=False) on the given local date. No weekly templates or overrides.
    """
    tz = _local_tz()
    now = timezone.now()

    day_start = _aware_local(date_obj, dtime.min)
    day_end = _aware_local(date_obj, dtime.max)

    # Pull persisted rows for the day
    rows = AvailabilitySlot.objects.filter(
        physician=physician_user,
        is_booked=False,
        start__gte=day_start,
        start__lt=day_end,
    ).order_by("start")

    starts: List[datetime] = []
    for r in rows:
        s = r.start.astimezone(tz) if timezone.is_aware(r.start) else timezone.make_aware(r.start, tz)
        e = r.end.astimezone(tz) if timezone.is_aware(r.end) else timezone.make_aware(r.end, tz)

        # skip past
        if s < now:
            continue

        # emit the exact row’s start if it can fit the requested duration and doesn’t conflict
        if (e - s) >= timedelta(minutes=slot_minutes) and not _has_conflict(physician_user, s, s + timedelta(minutes=slot_minutes)):
            starts.append(s)

    # unique + sorted
    return sorted(set(starts))
