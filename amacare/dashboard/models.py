from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Patient(models.Model):
    """
    Represents a dementia patient being monitored.
    For the demo a single patient with id=1 is auto-created by the view.
    """
    caregiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='patients')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    diagnosis = models.TextField(blank=True)
    emergency_contact = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class SafeZone(models.Model):
    """
    A geographic circle that defines a safe area for a patient.
    Alerts are raised when the patient moves outside the radius.
    """
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='safe_zones')
    name = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    radius_meters = models.PositiveIntegerField(default=50)
    alerts_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.patient.first_name} {self.patient.last_name})"


class LocationLog(models.Model):
    """
    One record per distinct location visit.

    Logic (enforced in views.py):
      - When the patient stays within SAME_PLACE_THRESHOLD metres of the
        current log's position, only last_seen_at is updated.
      - When the patient moves beyond the threshold, the current log is closed
        (is_current=False) and a new one is opened.

    This lets the caregiver see exactly how long the patient spent at each
    location without duplicate entries for minor GPS drift.
    """
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='location_logs')
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    place_name = models.CharField(max_length=200, default='Unknown Location')
    arrived_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    is_current = models.BooleanField(default=True)

    class Meta:
        ordering = ['-arrived_at']

    def duration_minutes(self):
        delta = self.last_seen_at - self.arrived_at
        return int(delta.total_seconds() / 60)

    def __str__(self):
        return f"{self.patient.first_name} {self.patient.last_name} @ {self.place_name} ({self.arrived_at})"


class Medication(models.Model):
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('every_other_day', 'Every Other Day'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='medications')
    name = models.CharField(max_length=200)
    dosage = models.CharField(max_length=100)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='daily')
    is_active = models.BooleanField(default=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    # Time slots
    morning = models.BooleanField(default=False)
    noon = models.BooleanField(default=False)
    night = models.BooleanField(default=False)

    # Inventory
    total_pills = models.PositiveIntegerField(default=0)
    pills_remaining = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} {self.dosage} - {self.patient}"

    @property
    def days_remaining(self):
        """Estimate days remaining based on daily dose count."""
        if self.pills_remaining == 0:
            return 0
        doses_per_day = sum([self.morning, self.noon, self.night])
        if doses_per_day == 0:
            return 0
        return self.pills_remaining // doses_per_day

    @property
    def needs_refill(self):
        return self.pills_remaining <= self.low_stock_threshold

    @property
    def is_finished(self):
        return self.pills_remaining == 0


class MedicationDose(models.Model):
    """
    Records each individual dose event — taken, missed, or pending.
    One record per medication per time-slot per day.
    """
    TIME_SLOT_CHOICES = [
        ('morning', 'Morning'),
        ('noon', 'Noon'),
        ('night', 'Night'),
    ]
    STATUS_CHOICES = [
        ('taken', 'Taken'),
        ('missed', 'Missed'),
        ('pending', 'Pending'),
        ('skipped', 'Skipped'),
    ]

    medication = models.ForeignKey(Medication, on_delete=models.CASCADE, related_name='doses')
    scheduled_date = models.DateField()
    time_slot = models.CharField(max_length=10, choices=TIME_SLOT_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    taken_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ('medication', 'scheduled_date', 'time_slot')
        ordering = ['scheduled_date', 'time_slot']

    def __str__(self):
        return f"{self.medication.name} | {self.scheduled_date} | {self.time_slot} | {self.status}"


class RefillAlert(models.Model):
    """
    Tracks refill alert emails sent to caregivers so we don't spam.
    """
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
    ]

    medication = models.ForeignKey(Medication, on_delete=models.CASCADE, related_name='refill_alerts')
    caregiver = models.ForeignKey(User, on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=20, choices=[('low_stock', 'Low Stock'), ('finished', 'Finished')],
                                  default='low_stock')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Alert: {self.medication.name} | {self.alert_type} | {self.status}"


class Pharmacy(models.Model):
    """
    Pharmacy contact linked to a patient for display in the sidebar.
    """
    patient = models.OneToOneField(Patient, on_delete=models.CASCADE, related_name='pharmacy')
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to='pharmacy_logos/', null=True, blank=True)

    def __str__(self):
        return self.name