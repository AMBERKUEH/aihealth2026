import json
import math
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.utils.timezone import localtime
from .models import Patient, SafeZone, LocationLog


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

def medication(request):
    return render(request, "medication.html")

def chat(request): 
    return render(request, "chat.html")

def mood(request):
    return render(request, "mood.html")