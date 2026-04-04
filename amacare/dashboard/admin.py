from django.contrib import admin

# Register your models here.
from .models import Patient, SafeZone, LocationLog, Medication, MedicationDose, RefillAlert, Pharmacy

admin.site.register(Patient)
admin.site.register(SafeZone)
admin.site.register(LocationLog)
admin.site.register(Medication)
admin.site.register(MedicationDose)
admin.site.register(RefillAlert)
admin.site.register(Pharmacy)