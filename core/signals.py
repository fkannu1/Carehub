# core/signals.py
from datetime import date, timedelta
from django.db.models.signals import post_save
from django.dispatch import receiver
from core.models import User
from core.utils.slots import generate_slots_for_physician

@receiver(post_save, sender=User)
def auto_generate_slots_for_new_physician(sender, instance, created, **kwargs):
    """
    Automatically create 4 weeks of default availability
    whenever a new physician account is created.
    """
    if not created:
        return
    if hasattr(instance, "role") and instance.role == User.Roles.PHYSICIAN:
        start = date.today()
        end = start + timedelta(weeks=4)
        created_count = generate_slots_for_physician(
            physician=instance, start_date=start, end_date=end
        )
        print(f"Auto-created {created_count} slots for new physician {instance.username}")
