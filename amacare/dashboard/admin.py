from django.contrib import admin

# Register your models here.
from .models import Patient, SafeZone, LocationLog, Medication, MedicationDose, RefillAlert, Pharmacy, MoodEntry, PhysicalConditionLog, ChatSession, ChatMessage

admin.site.register(Patient)
admin.site.register(SafeZone)
admin.site.register(LocationLog)
admin.site.register(Medication)
admin.site.register(MedicationDose)
admin.site.register(RefillAlert)
admin.site.register(Pharmacy)
# @admin.register(MoodEntry)
# class MoodEntryAdmin(admin.ModelAdmin):
#     list_display = ['patient', 'mood', 'logged_at', 'caregiver']
#     list_filter  = ['mood', 'logged_at']

# @admin.register(PhysicalConditionLog)
# class PhysicalConditionLogAdmin(admin.ModelAdmin):
#     list_display = ['patient', 'logged_at', 'blood_pressure', 'heart_rate', 'pain_level']
#     list_filter  = ['logged_at', 'fall_risk']
admin.site.register(MoodEntry)
admin.site.register(PhysicalConditionLog)
admin.site.register(ChatSession)
admin.site.register(ChatMessage)