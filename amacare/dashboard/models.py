from django.db import models
from django.utils import timezone


class Patient(models.Model):
    """
    Represents a dementia patient being monitored.
    For the demo a single patient with id=1 is auto-created by the view.
    """
    name = models.CharField(max_length=100)
    photo = models.ImageField(upload_to='patients/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


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
        return f"{self.name} ({self.patient.name})"


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
        return f"{self.patient.name} @ {self.place_name} ({self.arrived_at})"

class Medication(models.Model):
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=10, default="Not Taken")
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name