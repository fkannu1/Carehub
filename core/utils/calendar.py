# core/utils/calendar.py
from typing import List, Dict, Any

from django.utils import timezone
from django.db.models import Q
from core.models import (
    AvailabilitySlot,
    Appointment,
    FlexAppointment,
    User,
)

# ---------- shared overlap predicate
def _overlap_q(start, end) -> Q:
    return Q(start__lt=end) & Q(end__gt=start)


def get_booked_blocks_for_calendar(physician_user: User, start, end) -> List[Dict[str, Any]]:
    """
    Return all booked items (legacy slot-based + flexible) for this physician
    within [start, end), formatted for the calendar feed.
    """
    # Legacy appointments (via pre-sliced slots)
    legacy = (
        Appointment.objects
        .select_related("patient", "slot")
        .filter(
            physician=physician_user,
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
            slot__start__lt=end,
            slot__end__gt=start,
        )
        .values(
            "id", "status",
            "slot__start", "slot__end",
            "patient__username", "patient__patient__full_name",
        )
    )

    legacy_events: List[Dict[str, Any]] = []
    for appt in legacy:
        patient_name = appt["patient__patient__full_name"] or appt["patient__username"]
        legacy_events.append({
            "id": str(appt["id"]),
            "type": "BOOKED_LEGACY",
            "title": f"Booked: {patient_name}",
            "start": appt["slot__start"].isoformat(),
            "end": appt["slot__end"].isoformat(),
            "patient_name": patient_name,
            "status": appt["status"],
            "clickable": True,
        })

    # Flexible appointments (start/end)
    flex = (
        FlexAppointment.objects
        .select_related("patient")
        .filter(
            physician=physician_user,
            status__in=[FlexAppointment.Status.PENDING, FlexAppointment.Status.CONFIRMED],
        )
        .filter(_overlap_q(start, end))
        .values(
            "id", "start", "end", "status",
            "patient__username", "patient__patient__full_name",
        )
    )

    flex_events: List[Dict[str, Any]] = []
    for appt in flex:
        patient_name = appt["patient__patient__full_name"] or appt["patient__username"]
        flex_events.append({
            "id": str(appt["id"]),
            "type": "BOOKED_FLEX",
            "title": f"Booked: {patient_name}",
            "start": appt["start"].isoformat(),
            "end": appt["end"].isoformat(),
            "patient_name": patient_name,
            "status": appt["status"],
            "clickable": True,
        })

    return legacy_events + flex_events


def filter_available_presliced_slots(physician_user: User, start, end) -> List[Dict[str, Any]]:
    """
    Return pre-sliced AvailabilitySlot entries that are actually free:
      - not is_booked
      - overlap the requested window [start, end)
      - do not overlap any active appointment (legacy or flex)
    """
    # include any slot that OVERLAPS the window (not just fully inside)
    slots = list(
        AvailabilitySlot.objects.filter(
            physician=physician_user,
            is_booked=False,
        )
        .filter(start__lt=end, end__gt=start)  # <-- overlap check
        .order_by("start")
    )

    # fetch all active blocks that intersect [start, end)
    flex_blocks = list(
        FlexAppointment.objects.filter(
            physician=physician_user,
            status__in=[FlexAppointment.Status.PENDING, FlexAppointment.Status.CONFIRMED],
        )
        .filter(_overlap_q(start, end))
        .values("start", "end")
    )
    legacy_blocks = list(
        Appointment.objects.filter(
            physician=physician_user,
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
            slot__start__lt=end,
            slot__end__gt=start,
        )
        .select_related("slot")
        .values("slot__start", "slot__end")
    )

    def overlaps_any(slot_start, slot_end) -> bool:
        for b in flex_blocks:
            if b["start"] < slot_end and b["end"] > slot_start:
                return True
        for b in legacy_blocks:
            if b["slot__start"] < slot_end and b["slot__end"] > slot_start:
                return True
        return False

    available: List[Dict[str, Any]] = []
    now = timezone.now()
    for s in slots:
        if s.end <= now:           # hide past
            continue
        if overlaps_any(s.start, s.end):
            continue
        available.append({
            "id": str(s.id),
            "type": "AVAILABLE",
            "title": "Available",
            "start": s.start.isoformat(),
            "end": s.end.isoformat(),
            "clickable": True,
        })
    return available
