from django.contrib import admin
from .models import User, PatientProfile, PhysicianProfile, HealthRecord

admin.site.register(User)
admin.site.register(PatientProfile)
admin.site.register(PhysicianProfile)
admin.site.register(HealthRecord)
