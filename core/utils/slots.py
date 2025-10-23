# core/utils/slots.py
from datetime import datetime, timedelta, time
from typing import Sequence
from django.utils import timezone
from django.db import transaction
from core.models import User, AvailabilitySlot

def _dt_on(d, t: time):
    """
    Combine date and time, return a TZ-aware datetime using Django's timezone.
    Works with zoneinfo (no .localize).
    """
    dt = datetime.combine(d, t)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt

@transaction.atomic
def generate_slots_for_physician(
    physician: User,
    start_date,
    end_date,
    weekdays: Sequence[int] = (0, 1, 2, 3, 4),  # Monday–Friday
    times: Sequence[tuple] = ((time(10, 0), time(10, 30)), (time(14, 0), time(14, 30))),
) -> int:
    """
    Generate slots for the physician between start_date..end_date on given weekdays.
    Skips overlaps automatically.
    Returns the number of slots created.
    """
    created = 0
    day = start_date
    while day <= end_date:
        if day.weekday() in weekdays:
            for start_t, end_t in times:
                start_dt = _dt_on(day, start_t)
                end_dt = _dt_on(day, end_t)

                exists = AvailabilitySlot.objects.filter(
                    physician=physician,
                    start__lt=end_dt,
                    end__gt=start_dt,
                ).exists()
                if not exists:
                    AvailabilitySlot.objects.create(
                        physician=physician, start=start_dt, end=end_dt
                    )
                    created += 1
        day += timedelta(days=1)
    return created
