# core/utils/availability.py
from __future__ import annotations

from datetime import datetime, timedelta, time as dtime
from typing import Iterable, List, Tuple

from django.utils import timezone
from django.db.models import Q

from core.models import (
    PhysicianWeeklyAvailability,
    PhysicianDateOverride,
    Appointment,
)

# Internal type for a daily free window: (start_dt, end_dt, step_minutes)
Window = Tuple[datetime, datetime, int]


def _local_tz():
    return timezone.get_current_timezone()


def _aware_local(date_obj, t: dtime) -> datetime:
    """
    Combine a date and a time and return a TZ-AWARE datetime in the current tz.
    Works for both naive and tz-aware `time` values.
    """
    dt = datetime.combine(date_obj, t)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, _local_tz())
    else:
        dt = dt.astimezone(_local_tz())
    return dt


def _day_windows_for_physician(physician_user, date_obj) -> List[Window]:
    """
    Collect free-time windows for a given local calendar date from:
      1) Date overrides (highest precedence)
      2) Weekly repeating availability
    Returns list of (start_dt, end_dt, step_minutes).
    """
    # 1) Date overrides
    override_qs = PhysicianDateOverride.objects.filter(
        physician=physician_user,
        date=date_obj,
    )

    # If explicitly closed, no windows that day
    if override_qs.filter(is_closed=True).exists():
        return []

    override_windows = override_qs.filter(is_closed=False).order_by("start_time")
    if override_windows.exists():
        return [
            (_aware_local(date_obj, o.start_time), _aware_local(date_obj, o.end_time), 15)
            for o in override_windows
        ]

    # 2) Weekly availability (when no override present)
    weekday = date_obj.weekday()  # Mon=0 .. Sun=6
    weekly_qs = PhysicianWeeklyAvailability.objects.filter(
        physician=physician_user, weekday=weekday, is_active=True
    ).order_by("start_time")

    windows: List[Window] = []
    for w in weekly_qs:
        start_dt = _aware_local(date_obj, w.start_time)
        end_dt = _aware_local(date_obj, w.end_time)
        if end_dt > start_dt:
            windows.append((start_dt, end_dt, 15))
    return windows


def _round_up_to_step(dt: datetime, step_minutes: int) -> datetime:
    """
    Round a datetime UP to the next multiple of `step_minutes` from midnight,
    preserving timezone.
    """
    # snap to minute boundary first
    base = dt.replace(second=0, microsecond=0)
    minutes_from_midnight = base.hour * 60 + base.minute
    remainder = minutes_from_midnight % step_minutes
    if remainder == 0 and base >= dt:
        return base
    bump = (step_minutes - remainder) % step_minutes
    snapped = base + timedelta(minutes=bump)
    if snapped <= dt:  # guard when dt had seconds/micros
        snapped += timedelta(minutes=step_minutes)
    return snapped


def _iter_candidates(window: Window, slot_minutes: int) -> Iterable[datetime]:
    """
    Yield duration-aligned, NON-overlapping candidate starts inside `window`.
    The step is the requested slot size (30/45/60), not the window's native step.
    """
    start, end, _ignored_step = window
    step_td = timedelta(minutes=slot_minutes)

    cur = _round_up_to_step(start, slot_minutes)
    latest_start = end - timedelta(minutes=slot_minutes)

    while cur <= latest_start:
        yield cur
        cur += step_td


def _has_conflict(physician_user, start_dt: datetime, end_dt: datetime) -> bool:
    """
    A conflict exists if the physician has any confirmed/pending appointment overlapping
    [start_dt, end_dt). (Legacy Appointment model is used to prevent overbooking.)
    """
    return Appointment.objects.filter(
        physician=physician_user,
        status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
    ).filter(
        Q(slot__start__lt=end_dt) & Q(slot__end__gt=start_dt)
    ).exists()


def get_available_slots(physician_user, date_obj, slot_minutes: int) -> List[datetime]:
    """
    Compute available start datetimes (TZ-aware) for `slot_minutes` inside
    the physician's windows for `date_obj`, aligned to the duration grid.
    """
    now = timezone.now()
    result: List[datetime] = []

    windows = _day_windows_for_physician(physician_user, date_obj)
    if not windows:
        return result

    for win in windows:
        for start in _iter_candidates(win, slot_minutes):
            end = start + timedelta(minutes=slot_minutes)

            # Skip past times (don't offer a start that's already in the past)
            if start < now:
                continue

            # Skip conflicts with existing appointments
            if _has_conflict(physician_user, start, end):
                continue

            result.append(start)

    result.sort()
    return result
