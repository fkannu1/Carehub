from datetime import date, timedelta
from django.core.management.base import BaseCommand
from core.models import User
from core.utils.slots import generate_slots_for_physician

class Command(BaseCommand):
    help = "Generate availability slots for ALL physicians for N upcoming weeks (defaults to 4)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--weeks",
            type=int,
            default=4,
            help="How many weeks ahead to create (default 4).",
        )

    def handle(self, *args, **opts):
        weeks = max(1, int(opts["weeks"]))
        start = date.today()
        end = start + timedelta(weeks=weeks)

        physicians = User.objects.filter(role=User.Roles.PHYSICIAN)
        if not physicians.exists():
            self.stdout.write(self.style.WARNING("No physicians found."))
            return

        total = 0
        for phys in physicians:
            created = generate_slots_for_physician(physician=phys, start_date=start, end_date=end)
            total += created
            self.stdout.write(self.style.SUCCESS(f"{phys.username}: created {created} slots ({start} → {end})"))

        self.stdout.write(self.style.MIGRATE_HEADING(f"Total slots created: {total}"))
