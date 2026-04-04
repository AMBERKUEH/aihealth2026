import json
import math
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.utils.timezone import localtime
from .models import Patient, SafeZone, LocationLog
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Medication, MedicationDose, RefillAlert, Patient
from datetime import date, timedelta
from django.core.serializers.json import DjangoJSONEncoder
 
 
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')  # redirect to your dashboard URL name
 
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                # Redirect to 'next' param or dashboard
                next_url = request.GET.get('next', 'dashboard')
                return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = AuthenticationForm()
 
    return render(request, 'login.html', {'form': form})

# ─── Helpers ────────────────────────────────────────────────────────────────

def haversine_meters(lat1, lon1, lat2, lon2):
    """Return distance in metres between two lat/lon pairs."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _format_duration(minutes):
    if minutes < 1:
        return "Just arrived"
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}m"


def _log_to_dict(log):
    mins = int((log.last_seen_at - log.arrived_at).total_seconds() / 60)
    return {
        "id": log.id,
        "place_name": log.place_name,
        "latitude": float(log.latitude),
        "longitude": float(log.longitude),
        "arrived_at": localtime(log.arrived_at).strftime("%I:%M %p"),
        "arrived_at_iso": log.arrived_at.isoformat(),
        "last_seen_at": localtime(log.last_seen_at).strftime("%I:%M %p"),
        "duration": _format_duration(mins),
        "duration_minutes": mins,
        "is_current": log.is_current,
    }


# ─── Page View ───────────────────────────────────────────────────────────────

def location(request):
    # Ensure a default patient exists for demo purposes
    patient, _ = Patient.objects.get_or_create(id=1, defaults={"name": "Arthur Clarke"})

    current_log = LocationLog.objects.filter(patient=patient, is_current=True).first()
    safe_zone = SafeZone.objects.filter(patient=patient).first()
    recent_logs = LocationLog.objects.filter(patient=patient).order_by('-arrived_at')[:10]

    context = {
        "patient": patient,
        "current_log": current_log,
        "safe_zone": safe_zone,
        "recent_logs": recent_logs,
    }
    return render(request, "location.html", context)


# ─── API: Update / ping location ─────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def api_update_location(request):
    """
    Called by the browser every 5 minutes.
    Body: { patient_id, latitude, longitude, place_name }

    Logic:
      - If there is a current log within SAME_PLACE_THRESHOLD metres, just
        update last_seen_at on that log (same place, no new record).
      - Otherwise close the old current log and open a new one.
    """
    SAME_PLACE_THRESHOLD = 100  # metres

    try:
        data = json.loads(request.body)
        patient_id = data.get("patient_id", 1)
        lat = float(data["latitude"])
        lon = float(data["longitude"])
        place_name = data.get("place_name", "Unknown Location")
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    patient = get_object_or_404(Patient, id=patient_id)
    now = timezone.now()

    current = LocationLog.objects.filter(patient=patient, is_current=True).first()

    if current:
        dist = haversine_meters(
            float(current.latitude), float(current.longitude), lat, lon
        )
        if dist <= SAME_PLACE_THRESHOLD:
            # Same place — just refresh the timestamp
            current.last_seen_at = now
            current.save(update_fields=["last_seen_at"])
            return JsonResponse({"status": "updated", "log": _log_to_dict(current)})
        else:
            # Moved — close current log
            current.is_current = False
            current.last_seen_at = now
            current.save(update_fields=["is_current", "last_seen_at"])

    # Open a new log entry
    new_log = LocationLog.objects.create(
        patient=patient,
        latitude=lat,
        longitude=lon,
        place_name=place_name,
        arrived_at=now,
        last_seen_at=now,
        is_current=True,
    )
    return JsonResponse({"status": "new", "log": _log_to_dict(new_log)})


# ─── API: Get history logs ────────────────────────────────────────────────────

@require_http_methods(["GET"])
def api_location_logs(request):
    patient_id = request.GET.get("patient_id", 1)
    patient = get_object_or_404(Patient, id=patient_id)
    logs = LocationLog.objects.filter(patient=patient).order_by('-arrived_at')[:20]
    return JsonResponse({"logs": [_log_to_dict(l) for l in logs]})


# ─── API: Safe Zone CRUD ──────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_safe_zones(request):
    if request.method == "GET":
        patient_id = request.GET.get("patient_id", 1)
    else:
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        patient_id = body.get("patient_id", 1)

    patient = get_object_or_404(Patient, id=patient_id)

    if request.method == "GET":
        zones = SafeZone.objects.filter(patient=patient)
        data = [
            {
                "id": z.id,
                "name": z.name,
                "latitude": float(z.latitude),
                "longitude": float(z.longitude),
                "radius_meters": z.radius_meters,
                "alerts_enabled": z.alerts_enabled,
            }
            for z in zones
        ]
        return JsonResponse({"safe_zones": data})

    # POST — create or update
    zone_id = body.get("id")
    if zone_id:
        zone = get_object_or_404(SafeZone, id=zone_id, patient=patient)
    else:
        zone = SafeZone(patient=patient)

    zone.name = body.get("name", zone.name if zone_id else "New Safe Zone")
    zone.latitude = body.get("latitude", float(zone.latitude) if zone_id else 0)
    zone.longitude = body.get("longitude", float(zone.longitude) if zone_id else 0)
    zone.radius_meters = body.get("radius_meters", zone.radius_meters if zone_id else 50)
    zone.alerts_enabled = body.get("alerts_enabled", zone.alerts_enabled if zone_id else True)
    zone.save()

    return JsonResponse({
        "status": "saved",
        "id": zone.id,
        "name": zone.name,
        "latitude": float(zone.latitude),
        "longitude": float(zone.longitude),
        "radius_meters": zone.radius_meters,
        "alerts_enabled": zone.alerts_enabled,
    })


@csrf_exempt
@require_http_methods(["DELETE"])
def api_safe_zone_delete(request, zone_id):
    patient_id = request.GET.get("patient_id", 1)
    zone = get_object_or_404(SafeZone, id=zone_id, patient__id=patient_id)
    zone.delete()
    return JsonResponse({"status": "deleted"})

def home(request):
    # meds = Medication.objects.all()
    # return render(request, "home.html", {"meds": meds})
    return render(request, "dashboard.html")

def settings(request):
    return render(request, "settings.html")

@login_required
def medication(request):
    patient = Patient.objects.filter(caregiver=request.user).first()
    
    if not patient:
        return render(request, "medication.html", {
            "medications_json": "[]",
            "dose_log_json": "{}",
            "error": "No patient found.",
            "user": request.user,  # Add this
        })
 
    medications_qs = Medication.objects.filter(patient=patient)
 
    # Build a plain list that is fully JSON-serialisable.
    # DjangoJSONEncoder handles date / datetime objects automatically.
    medications_data = list(medications_qs.values(
        "id", "name", "dosage", "frequency",
        "is_active", "start_date", "end_date",
        "morning", "noon", "night",
        "total_pills", "pills_remaining", "low_stock_threshold",
        "notes",
    ))
 
    # Pre-fetch this week's dose log so the page load requires zero extra
    # API calls for the schedule grid and adherence rate.
    today = date.today()
    week_start = today - timedelta(days=(today.weekday()))        # Monday
    week_end   = week_start + timedelta(days=6)                   # Sunday
 
    doses_qs = MedicationDose.objects.filter(
        medication__patient=patient,
        scheduled_date__range=[week_start, week_end],
    ).values("medication_id", "scheduled_date", "time_slot", "status")
 
    # Build a dict keyed as "medId_YYYY-MM-DD_slot" — same format as the JS
    dose_log = {}
    for dose in doses_qs:
        key = f"{dose['medication_id']}_{dose['scheduled_date']}_{dose['time_slot']}"
        dose_log[key] = dose["status"]
 
    context = {
        "medications_json": json.dumps(medications_data, cls=DjangoJSONEncoder),
        "dose_log_json":    json.dumps(dose_log),
        "patient":          patient,
        "user": request.user,
    }
    return render(request, "medication.html", context)
 
 
# ──────────────────────────────────────────────────────────────────────────────
#  API: UPDATE A SINGLE DOSE
# ──────────────────────────────────────────────────────────────────────────────
 
@login_required
@require_http_methods(["POST"])
def update_dose(request):
    """
    Expects JSON body:
        { medication_id, date, time_slot, status }
    """
    try:
        data      = json.loads(request.body)
        med_id    = int(data["medication_id"])
        dose_date = data["date"]          # "YYYY-MM-DD" string
        time_slot = data["time_slot"]
        status    = data["status"]
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({"success": False, "error": "Invalid payload."}, status=400)
 
    # Security: make sure this medication belongs to the logged-in caregiver
    try:
        med = Medication.objects.get(id=med_id, patient__caregiver=request.user)
    except Medication.DoesNotExist:
        return JsonResponse({"success": False, "error": "Medication not found."}, status=404)
 
    dose, created = MedicationDose.objects.get_or_create(
        medication=med,
        scheduled_date=dose_date,
        time_slot=time_slot,
        defaults={"status": status},
    )
 
    if not created:
        previous_status = dose.status
        dose.status = status
        dose.taken_at = timezone.now() if status == "taken" else None
        dose.save(update_fields=["status", "taken_at"])
 
        # Decrement pill count only on a fresh "taken" transition
        if status == "taken" and previous_status != "taken":
            if med.pills_remaining > 0:
                med.pills_remaining -= 1
                med.save(update_fields=["pills_remaining"])
 
        # Restore pill count when un-marking a taken dose
        elif previous_status == "taken" and status != "taken":
            med.pills_remaining += 1
            med.save(update_fields=["pills_remaining"])
    else:
        # Freshly created as "taken" — decrement
        if status == "taken" and med.pills_remaining > 0:
            med.pills_remaining -= 1
            med.save(update_fields=["pills_remaining"])
 
    return JsonResponse({
        "success":        True,
        "pills_remaining": med.pills_remaining,
    })
 
 
# ──────────────────────────────────────────────────────────────────────────────
#  API: BULK DOSE FETCH (week range, all meds for this patient)
# ──────────────────────────────────────────────────────────────────────────────
 
@login_required
@require_http_methods(["GET"])
def get_doses(request):
    """
    Query params: start_date, end_date  (YYYY-MM-DD)
    Returns a flat dict: { "medId_date_slot": "status", ... }
 
    Fetches ALL medications for the patient in one query — no per-medication
    round trips needed from the frontend.
    """
    start_date = request.GET.get("start_date")
    end_date   = request.GET.get("end_date")
 
    if not start_date or not end_date:
        return JsonResponse({"error": "start_date and end_date are required."}, status=400)
 
    doses = MedicationDose.objects.filter(
        medication__patient__caregiver=request.user,
        scheduled_date__range=[start_date, end_date],
    ).values("medication_id", "scheduled_date", "time_slot", "status")
 
    dose_log = {}
    for dose in doses:
        key = f"{dose['medication_id']}_{dose['scheduled_date']}_{dose['time_slot']}"
        dose_log[key] = dose["status"]
 
    return JsonResponse(dose_log)
 
 
# ──────────────────────────────────────────────────────────────────────────────
#  API: ADD / EDIT MEDICATION
# ──────────────────────────────────────────────────────────────────────────────
 
@login_required
@require_http_methods(["POST"])
def save_medication(request):
    """
    Handles both create (no id) and update (id present).
    Expects JSON body matching the Medication fields.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)
 
    patient = Patient.objects.filter(caregiver=request.user).first()
    if not patient:
        return JsonResponse({"success": False, "error": "No patient found."}, status=404)
 
    med_id = data.get("id")
    fields = {
        "name":                data.get("name", "").strip(),
        "dosage":              data.get("dosage", "").strip(),
        "frequency":           data.get("frequency", "daily"),
        "is_active":           bool(data.get("isActive", True)),
        "morning":             bool(data.get("morning", False)),
        "noon":                bool(data.get("noon", False)),
        "night":               bool(data.get("night", False)),
        "total_pills":         int(data.get("totalPills", 0)),
        "pills_remaining":     int(data.get("pillsRemaining", 0)),
        "low_stock_threshold": int(data.get("lowStockThreshold", 5)),
        "start_date":          data.get("startDate"),
        "end_date":            data.get("endDate") or None,
        "notes":               data.get("notes", "").strip(),
    }
 
    if not fields["name"] or not fields["dosage"]:
        return JsonResponse({"success": False, "error": "Name and dosage are required."}, status=400)
 
    if med_id:
        # Update
        try:
            med = Medication.objects.get(id=med_id, patient=patient)
        except Medication.DoesNotExist:
            return JsonResponse({"success": False, "error": "Medication not found."}, status=404)
        for attr, value in fields.items():
            setattr(med, attr, value)
        med.save()
    else:
        # Create
        med = Medication.objects.create(patient=patient, **fields)
 
    return JsonResponse({"success": True, "id": med.id})
 
 
# ──────────────────────────────────────────────────────────────────────────────
#  API: DELETE MEDICATION
# ──────────────────────────────────────────────────────────────────────────────
 
@login_required
@require_http_methods(["POST"])
def delete_medication(request):
    try:
        data   = json.loads(request.body)
        med_id = int(data["medication_id"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({"success": False, "error": "Invalid payload."}, status=400)
 
    try:
        med = Medication.objects.get(id=med_id, patient__caregiver=request.user)
    except Medication.DoesNotExist:
        return JsonResponse({"success": False, "error": "Medication not found."}, status=404)
 
    med.delete()
    return JsonResponse({"success": True})
 
 
# ──────────────────────────────────────────────────────────────────────────────
#  API: SEND REFILL ALERT (static — wire up Django email here later)
# ──────────────────────────────────────────────────────────────────────────────
 
@login_required
@require_http_methods(["POST"])
def send_refill_alert(request):
    try:
        data   = json.loads(request.body)
        med_id = int(data["medication_id"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({"success": False, "error": "Invalid payload."}, status=400)
 
    try:
        med = Medication.objects.get(id=med_id, patient__caregiver=request.user)
    except Medication.DoesNotExist:
        return JsonResponse({"success": False, "error": "Medication not found."}, status=404)
 
    # ── Wire Django email here ──────────────────────────────────────────────
    # from django.core.mail import send_mail
    # alert_type = "Finished" if med.pills_remaining == 0 else "Low Stock"
    # send_mail(
    #     subject=f"[AmaCare] Medication {alert_type}: {med.name}",
    #     message=f"{med.name} {med.dosage} for {med.patient} has {med.pills_remaining} pills remaining.",
    #     from_email="noreply@amacare.com",
    #     recipient_list=[request.user.email],
    # )
    # ────────────────────────────────────────────────────────────────────────
 
    return JsonResponse({"success": True})

def chat(request): 
    return render(request, "chat.html")

def mood(request):
    return render(request, "mood.html")