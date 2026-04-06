import json
import math
import os
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.utils.timezone import datetime, localtime
from .models import Patient, SafeZone, LocationLog, Medication, MedicationDose, RefillAlert, MoodEntry, PhysicalConditionLog, ChatSession, ChatMessage
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from datetime import date, timedelta
from django.core.serializers.json import DjangoJSONEncoder
from django.contrib.auth.hashers import make_password
from django.views.decorators.http import require_GET, require_POST
from google import genai 
 
 
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

def _get_patient(user):
    """Return the first patient belonging to the logged-in caregiver."""
    return Patient.objects.filter(caregiver=user).first()
 
 
def _seven_days_ago():
    return timezone.now() - timedelta(days=7)
 
 
# ─────────────────────────────────────────────
#  Main page
# ─────────────────────────────────────────────
 
@login_required
def chat(request):
    patient = _get_patient(request.user)
 
    if patient:
        cutoff = _seven_days_ago()
        recent_sessions = ChatSession.objects.filter(
            patient=patient,
            started_at__gte=cutoff,
        ).order_by('-started_at')
 
        archived_sessions = ChatSession.objects.filter(
            patient=patient,
            started_at__lt=cutoff,
        ).order_by('-started_at')
    else:
        recent_sessions = ChatSession.objects.none()
        archived_sessions = ChatSession.objects.none()
 
    return render(request, 'chat.html', {
        'patient': patient,
        'recent_sessions': recent_sessions,
        'archived_sessions': archived_sessions,
    })
 
 
# ─────────────────────────────────────────────
#  Session detail (AJAX)
# ─────────────────────────────────────────────
 
@login_required
@require_GET
def session_messages(request, session_id):
    patient = _get_patient(request.user)
    session = get_object_or_404(ChatSession, id=session_id, patient=patient)
 
    messages = []
    for msg in session.messages.all():
        messages.append({
            'id':               msg.id,
            'sender':           msg.sender,
            'content':          msg.content,
            'timestamp':        msg.timestamp.isoformat(),
            'detected_mood':    msg.detected_mood,
            'flagged_keywords': msg.flagged_keywords or [],
        })
 
    return JsonResponse({
        'id':            session.id,
        'title':         session.title or 'Untitled Session',
        'patient_name':  f"{patient.first_name} {patient.last_name}",
        'started_at':    session.started_at.isoformat(),
        'dominant_mood': session.dominant_mood,
        'flags':         session.flags,
        'messages':      messages,
    })
 
 
# ─────────────────────────────────────────────
#  Export transcript
# ─────────────────────────────────────────────
 
@login_required
@require_GET
def export_transcript(request, session_id):
    patient = _get_patient(request.user)
    session = get_object_or_404(ChatSession, id=session_id, patient=patient)
 
    lines = [
        f"AmaCare — Session Transcript",
        f"Patient : {patient.first_name} {patient.last_name}",
        f"Session : {session.title or 'Untitled'} (ID #{session.id})",
        f"Date    : {session.started_at.strftime('%d %B %Y, %I:%M %p')}",
        f"Mood    : {session.dominant_mood.capitalize() if session.dominant_mood else '—'}",
        f"Flags   : {session.flags or 'None'}",
        "─" * 60,
        "",
    ]
 
    for msg in session.messages.all():
        sender_label = {
            'bot':     'CareBot',
            'patient': f"{patient.first_name} (Patient)",
            'system':  '[ System ]',
        }.get(msg.sender, msg.sender)
 
        ts = msg.timestamp.strftime('%I:%M %p')
        lines.append(f"[{ts}] {sender_label}:")
        lines.append(f"  {msg.content}")
        if msg.detected_mood:
            lines.append(f"  (Mood detected: {msg.detected_mood})")
        if msg.flagged_keywords:
            lines.append(f"  (Flagged: {', '.join(msg.flagged_keywords)})")
        lines.append("")
 
    content = "\n".join(lines)
    filename = f"amacare_session_{session_id}_{session.started_at.strftime('%Y%m%d')}.txt"
 
    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
 
 
# ─────────────────────────────────────────────
#  AI Analysis
# ─────────────────────────────────────────────
 
@login_required
@require_POST
def analyse_sessions(request):
    """
    Accepts:
        question  (str)  — caregiver's question
        from_date (str)  — ISO date string, optional
        to_date   (str)  — ISO date string, optional
        history   (list) — previous turns for follow-up support
    Returns:
        { answer: str }  or  { error: str }
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)
 
    question  = (body.get('question') or '').strip()
    from_date = body.get('from_date')
    to_date   = body.get('to_date')
    history   = body.get('history') or []
 
    if not question:
        return JsonResponse({'error': 'Question cannot be empty.'}, status=400)
 
    patient = _get_patient(request.user)
    if not patient:
        return JsonResponse({'error': 'No patient linked to your account.'}, status=404)
 
    # ── Gather sessions in the requested range ──
    qs = ChatSession.objects.filter(patient=patient)
    if from_date:
        try:
            from_date = datetime.fromisoformat(from_date).date()
            qs = qs.filter(started_at__date__gte=from_date)
        except ValueError:
            pass
    if to_date:
        try:
            to_date = datetime.fromisoformat(to_date).date()
            qs = qs.filter(started_at__date__lte=to_date)
        except ValueError:
            pass
 
    sessions = qs.prefetch_related('messages').order_by('started_at')
 
    if not sessions.exists():
        return JsonResponse({'answer': 'No sessions found for the selected date range.'})
 
    # ── Build transcript context for Claude ──
    transcript_blocks = []
    for sess in sessions:
        block = [
            f"--- Session: {sess.title or 'Untitled'} | {sess.started_at.strftime('%d %b %Y %I:%M %p')} ---",
            f"Overall Mood: {sess.dominant_mood or 'Unknown'}",
            f"Flags: {sess.flags or 'None'}",
        ]
        for msg in sess.messages.all():
            sender_label = {
                'bot':     'CareBot',
                'patient': f"{patient.first_name}",
                'system':  '[System]',
            }.get(msg.sender, msg.sender)
            ts = msg.timestamp.strftime('%H:%M')
            line = f"[{ts}] {sender_label}: {msg.content}"
            if msg.detected_mood:
                line += f" (mood: {msg.detected_mood})"
            if msg.flagged_keywords:
                line += f" [flagged: {', '.join(msg.flagged_keywords)}]"
            block.append(line)
        transcript_blocks.append("\n".join(block))
 
    full_transcript = "\n\n".join(transcript_blocks)
 
    # Cap transcript to ~80k chars to stay within context limits
    MAX_CHARS = 80_000
    if len(full_transcript) > MAX_CHARS:
        full_transcript = full_transcript[:MAX_CHARS] + "\n\n[... transcript truncated for length ...]"
 
    system_prompt = f"""You are a clinical AI assistant helping a caregiver understand conversations between their elderly patient with dementia and a care companion chatbot (CareBot).
 
Patient: {patient.first_name} {patient.last_name}
Date of Birth: {patient.date_of_birth}
Diagnosis: {patient.diagnosis or 'Dementia'}
 
Your role is to:
- Summarise emotional patterns and recurring topics clearly and compassionately
- Highlight clinical concerns (pain, confusion, refusal of medication, distress, isolation)
- Identify positive moments (engagement, calm, responsiveness)
- Be factual and evidence-based — reference specific messages where helpful
- Use plain, professional language suitable for a caregiver without clinical training
- Keep responses concise but thorough — use short paragraphs, not bullet lists unless essential
 
Here are the conversation logs for this analysis:
 
{full_transcript}"""
 
    # ── Build message list (support follow-up turns) ──
    # history already contains prior turns; strip to last 8 for token efficiency
    safe_history = history[-8:] if len(history) > 8 else history
 
    # Replace the last user message in history with the current question
    # (history arrives with the current question already appended by JS)
    messages = safe_history + [{'role': 'user', 'content': question}]
 
    # Ensure history alternates roles correctly
    clean_messages = []
    for turn in messages:
        role = turn.get('role', '')
        content = turn.get('content', '')
        if role in ('user', 'assistant') and content:
            clean_messages.append({'role': role, 'content': content})
 
    if not clean_messages:
        clean_messages = [{'role': 'user', 'content': question}]
 
    try:
        api_key = getattr(settings, 'GEMINI_API_KEY', os.environ.get('GEMINI_API_KEY', ''))
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=[
                {"role": "user", "parts": [{"text": system_prompt}]},
                *[
                    {"role": m["role"], "parts": [{"text": m["content"]}]}
                    for m in clean_messages
                ]
            ],
            config={
                "max_output_tokens": 1500
            }
        )
        try:
            answer = response.text
        except AttributeError:
            answer = str(response)
        return JsonResponse({'answer': answer})
 
    except Exception as e:
        return JsonResponse({'error': f'Unexpected error during analysis: {str(e)}'}, status=500)

# def _get_patient(user):
#     """Return the first patient belonging to the logged-in caregiver."""
#     return Patient.objects.filter(caregiver=user).first()
 
 
def _mood_score(entries):
    """Average mood score across a queryset of MoodEntry objects."""
    if not entries.exists():
        return 0
    scores = [e.mood_score() for e in entries]
    return round(sum(scores) / len(scores))
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Page
# ─────────────────────────────────────────────────────────────────────────────
 
@login_required
def mood_page(request):
    patient = _get_patient(request.user)
    return render(request, 'mood.html', {'patient': patient})
 
 
# ─────────────────────────────────────────────────────────────────────────────
# API – Summary (score + weekly trend)
# ─────────────────────────────────────────────────────────────────────────────
 
@login_required
def mood_api_summary(request):
    patient = _get_patient(request.user)
    if not patient:
        return JsonResponse({'score': 0, 'label': 'No Data', 'trend': [], 'alert': None})
 
    today = timezone.localdate()
    recent = MoodEntry.objects.filter(patient=patient, logged_at__date=today)
    score  = _mood_score(recent) if recent.exists() else _mood_score(
        MoodEntry.objects.filter(patient=patient).order_by('-logged_at')[:5]
    )
 
    # Score label
    if score >= 75:
        label = 'Stability High'
    elif score >= 50:
        label = 'Moderate'
    elif score >= 30:
        label = 'Low'
    else:
        label = 'Critical'
 
    # Weekly trend (last 7 days)
    trend = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_entries = MoodEntry.objects.filter(patient=patient, logged_at__date=day)
        trend.append({
            'label': day.strftime('%a').upper(),
            'score': _mood_score(day_entries) if day_entries.exists() else None,
            'date':  day.strftime('%b %d'),
        })
 
    # 3-day negative trend check
    alert = None
    last3 = []
    for i in range(2, -1, -1):
        day      = today - timedelta(days=i)
        day_ents = MoodEntry.objects.filter(patient=patient, logged_at__date=day)
        last3.append(_mood_score(day_ents) if day_ents.exists() else None)
 
    valid3 = [s for s in last3 if s is not None]
    if len(valid3) >= 2 and all(s < 50 for s in valid3):
        alert = {
            'type':    'negative_trend',
            'message': f'Low mood scores detected over the past {len(valid3)} days. Consider scheduling a specialist review.',
        }
 
    # Last assessment time
    last_entry = MoodEntry.objects.filter(patient=patient).first()
    last_assessed = (
        last_entry.logged_at.strftime('Today, %I:%M %p')
        if last_entry and last_entry.logged_at.date() == today
        else (last_entry.logged_at.strftime('%b %d, %I:%M %p') if last_entry else 'No assessments yet')
    )
 
    return JsonResponse({
        'score':         score,
        'label':         label,
        'trend':         trend,
        'alert':         alert,
        'last_assessed': last_assessed,
    })
 
 
# ─────────────────────────────────────────────────────────────────────────────
# API – Mood Notes (CRUD)
# ─────────────────────────────────────────────────────────────────────────────
 
@login_required
def mood_api_notes(request):
    patient = _get_patient(request.user)
    if not patient:
        return JsonResponse({'notes': []})
 
    entries = MoodEntry.objects.filter(patient=patient).order_by('-logged_at')[:20]
    data = []
    for e in entries:
        data.append({
            'id':        e.pk,
            'mood':      e.get_mood_display(),
            'mood_key':  e.mood,
            'mood_icon': e.mood_icon(),
            'notes':     e.notes,
            'logged_at': e.logged_at.strftime('%b %d, %Y • %I:%M %p'),
            'score':     e.mood_score(),
        })
    return JsonResponse({'notes': data})
 
 
@login_required
@require_http_methods(['POST'])
def mood_api_note_save(request):
    patient = _get_patient(request.user)
    if not patient:
        return JsonResponse({'ok': False, 'error': 'No patient found'}, status=400)
 
    body = json.loads(request.body)
    pk   = body.get('id')
 
    if pk:
        entry = get_object_or_404(MoodEntry, pk=pk, patient=patient)
    else:
        entry = MoodEntry(patient=patient, caregiver=request.user)
 
    entry.mood      = body.get('mood', entry.mood)
    entry.notes     = body.get('notes', '')
    raw_dt          = body.get('logged_at')
    if raw_dt:
        from django.utils.dateparse import parse_datetime
        entry.logged_at = parse_datetime(raw_dt) or timezone.now()
    entry.save()
 
    return JsonResponse({'ok': True, 'id': entry.pk})
 
 
@login_required
@require_http_methods(['DELETE'])
def mood_api_note_delete(request, pk):
    patient = _get_patient(request.user)
    entry   = get_object_or_404(MoodEntry, pk=pk, patient=patient)
    entry.delete()
    return JsonResponse({'ok': True})
 
 
# ─────────────────────────────────────────────────────────────────────────────
# API – Physical Condition Logs
# ─────────────────────────────────────────────────────────────────────────────
 
@login_required
def mood_api_physical(request):
    patient = _get_patient(request.user)
    if not patient:
        return JsonResponse({'logs': []})
 
    logs = PhysicalConditionLog.objects.filter(patient=patient).order_by('-logged_at')[:10]
    data = []
    for l in logs:
        data.append({
            'id':          l.pk,
            'logged_at':   l.logged_at.strftime('%b %d, %Y • %I:%M %p'),
            'bp':          l.blood_pressure,
            'heart_rate':  l.heart_rate,
            'temp':        str(l.temperature_celsius) if l.temperature_celsius else None,
            'spo2':        l.oxygen_saturation,
            'appetite':    l.get_appetite_display() if l.appetite else None,
            'sleep':       l.get_sleep_display()    if l.sleep    else None,
            'pain':        l.pain_level,
            'mobility_ok': l.mobility_ok,
            'fall_risk':   l.fall_risk,
            'notes':       l.notes,
        })
    return JsonResponse({'logs': data})
 
 
@login_required
@require_http_methods(['POST'])
def mood_api_physical_save(request):
    patient = _get_patient(request.user)
    if not patient:
        return JsonResponse({'ok': False, 'error': 'No patient found'}, status=400)
 
    body = json.loads(request.body)
 
    def _int(v):
        try: return int(v) if v not in (None, '') else None
        except: return None
 
    def _dec(v):
        try:
            from decimal import Decimal
            return Decimal(str(v)) if v not in (None, '') else None
        except: return None
 
    log = PhysicalConditionLog(patient=patient, caregiver=request.user)
    log.blood_pressure_systolic  = _int(body.get('bp_sys'))
    log.blood_pressure_diastolic = _int(body.get('bp_dia'))
    log.heart_rate               = _int(body.get('heart_rate'))
    log.temperature_celsius      = _dec(body.get('temp'))
    log.oxygen_saturation        = _int(body.get('spo2'))
    log.appetite     = body.get('appetite', '')
    log.sleep        = body.get('sleep', '')
    log.pain_level   = str(body.get('pain', '0'))
    log.mobility_ok  = bool(body.get('mobility_ok', True))
    log.fall_risk    = bool(body.get('fall_risk', False))
    log.notes        = body.get('notes', '')
 
    raw_dt = body.get('logged_at')
    if raw_dt:
        from django.utils.dateparse import parse_datetime
        log.logged_at = parse_datetime(raw_dt) or timezone.now()
 
    log.save()
    return JsonResponse({'ok': True, 'id': log.pk})
 
 
@login_required
def mood_api_physical_detail(request, pk):
    patient = _get_patient(request.user)
    log = get_object_or_404(PhysicalConditionLog, pk=pk, patient=patient)
    return JsonResponse({
        'id':          log.pk,
        'logged_at':   log.logged_at.strftime('%b %d, %Y • %I:%M %p'),
        'bp':          log.blood_pressure,
        'bp_sys':      log.blood_pressure_systolic,
        'bp_dia':      log.blood_pressure_diastolic,
        'heart_rate':  log.heart_rate,
        'temp':        str(log.temperature_celsius) if log.temperature_celsius else '',
        'spo2':        log.oxygen_saturation,
        'appetite':    log.appetite,
        'sleep':       log.sleep,
        'pain':        log.pain_level,
        'mobility_ok': log.mobility_ok,
        'fall_risk':   log.fall_risk,
        'notes':       log.notes,
    })
 
 
# ─────────────────────────────────────────────────────────────────────────────
# API – Gemini AI Insights
# ─────────────────────────────────────────────────────────────────────────────
 
@login_required
def mood_api_ai_insights(request):
    """
    Calls Google Gemini (gemini-1.5-flash) with recent mood + physical data
    and returns a structured insight object.
 
    Set GEMINI_API_KEY in your Django settings (or as an environment variable).
    """
    from google import genai
    from django.conf import settings
 
    patient = _get_patient(request.user)
    if not patient:
        return JsonResponse({'ok': False, 'insight': 'No patient data available.'})
 
    # Gather last 7 days of mood entries
    seven_days_ago = timezone.now() - timedelta(days=7)
    mood_entries   = MoodEntry.objects.filter(patient=patient, logged_at__gte=seven_days_ago).order_by('logged_at')
    phys_logs      = PhysicalConditionLog.objects.filter(patient=patient, logged_at__gte=seven_days_ago).order_by('logged_at')
 
    if not mood_entries.exists() and not phys_logs.exists():
        return JsonResponse({'ok': True, 'insight': 'Not enough data has been recorded in the past 7 days to generate an insight. Please log mood notes and physical conditions regularly.'})
 
    # Build context string
    mood_text = "\n".join(
        f"- {e.logged_at.strftime('%a %b %d %H:%M')}: {e.get_mood_display()} (score {e.mood_score()}/100). Notes: {e.notes or 'none'}"
        for e in mood_entries
    ) or "No mood entries this week."
 
    phys_text = "\n".join(
        f"- {l.logged_at.strftime('%a %b %d %H:%M')}: BP {l.blood_pressure or 'N/A'}, HR {l.heart_rate or 'N/A'} bpm, "
        f"SpO2 {l.oxygen_saturation or 'N/A'}%, Temp {l.temperature_celsius or 'N/A'}°C, "
        f"Pain {l.pain_level}/10, Sleep: {l.get_sleep_display() if l.sleep else 'N/A'}, "
        f"Appetite: {l.get_appetite_display() if l.appetite else 'N/A'}. Notes: {l.notes or 'none'}"
        for l in phys_logs
    ) or "No physical logs this week."
 
    prompt = f"""You are a clinical assistant AI supporting a caregiver of an elderly dementia patient.
Below is a 7-day log of mood observations and physical condition records.
 
MOOD LOG:
{mood_text}
 
PHYSICAL CONDITION LOG:
{phys_text}
 
Based on this data, provide a concise clinical insight (3-5 sentences) covering:
1. The dominant mood pattern and any concerning trends.
2. Notable physical findings and potential correlations with mood.
3. One or two specific, actionable recommendations for the caregiver.
 
Write in a calm, professional, empathetic tone. Do not use bullet points. Do not use emojis. Speak directly to the caregiver."""
 
    try:
        api_key = getattr(settings, 'GEMINI_API_KEY', os.environ.get('GEMINI_API_KEY', ''))
        # genai.configure(api_key=api_key)
        client = genai.Client(api_key=api_key)
        resp   = client.models.generate_content(
            model="gemini-3-flash-preview", contents=prompt
        )
        insight = resp.text.strip()
        return JsonResponse({'ok': True, 'insight': insight})
    except Exception as exc:
        return JsonResponse({'ok': False, 'insight': f'Unable to generate insight: {exc}'})

@login_required
def settings_view(request):
    caregiver = request.user

    # Force a fresh fetch from the database, not the cached request.user object
    from django.contrib.auth.models import User
    caregiver = User.objects.get(pk=request.user.pk)

    patient = Patient.objects.filter(caregiver=caregiver).first()
    if not patient:
        patient = Patient.objects.create(
            caregiver=caregiver,
            first_name="Arthur",
            last_name="Miller",
            date_of_birth=date(1942, 3, 15),
            diagnosis="Alzheimer's Disease"
        )

    full_name = f"{caregiver.first_name} {caregiver.last_name}".strip() or caregiver.username

    context = {
        'caregiver_full_name': full_name,
        'caregiver_email': caregiver.email or '',
        'caregiver_phone': getattr(caregiver, 'profile', None) and caregiver.profile.phone or request.session.get('caregiver_phone', ''),
        'caregiver_username': caregiver.username,

        'patient_first_name': patient.first_name,
        'patient_last_name': patient.last_name,
        'patient_dob': patient.date_of_birth,
        'patient_diagnosis': patient.diagnosis,
        'patient_created_at': patient.created_at,

        'patient_emergency_contact': request.session.get('patient_emergency_contact', ''),
        # 'patient_medical_notes': request.session.get('patient_medical_notes', ''),
    }

    # Temporary debug — remove after confirming
    print("DEBUG caregiver:", caregiver.username, caregiver.first_name, caregiver.last_name, caregiver.email)
    print("DEBUG patient:", patient.first_name, patient.last_name, patient.diagnosis)

    return render(request, 'settings.html', context)

@login_required
def update_caregiver(request):
    """
    Handle caregiver profile updates (full_name, email, phone, password).
    """
    if request.method == 'POST':
        user = request.user
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '').strip()
        
        # Update user fields
        if full_name:
            # Split full_name into first_name and last_name
            name_parts = full_name.split(' ', 1)
            user.first_name = name_parts[0]
            user.last_name = name_parts[1] if len(name_parts) > 1 else ''
            user.save()
        
        if email:
            user.email = email
            user.save()
        
        if phone:
            request.session['caregiver_phone'] = phone
        
        if password:
            user.password = make_password(password)
            user.save()
            messages.success(request, 'Password updated. Please log in again.')
            return redirect('login')
        
        messages.success(request, 'Caregiver profile updated successfully.')
    return redirect('settings')


@login_required
def update_patient(request):
    """
    Handle patient profile updates (first_name, last_name, date_of_birth, diagnosis, emergency_contact, medical_notes).
    """
    if request.method == 'POST':
        caregiver = request.user
        patient = Patient.objects.filter(caregiver=caregiver).first()
        
        if patient:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            date_of_birth = request.POST.get('date_of_birth', '')
            diagnosis = request.POST.get('diagnosis', '').strip()
            emergency_contact = request.POST.get('emergency_contact', '').strip()
            medical_notes = request.POST.get('medical_notes', '').strip()
            
            if first_name:
                patient.first_name = first_name
            if last_name:
                patient.last_name = last_name
            if date_of_birth:
                from datetime import datetime
                try:
                    patient.date_of_birth = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
                except ValueError:
                    pass
            if diagnosis:
                patient.diagnosis = diagnosis
            if emergency_contact:
                patient.emergency_contact = emergency_contact    
            patient.save()
            
            # Store non-model fields in session (extend Patient model in production)
            # if medical_notes:
            #     request.session['patient_medical_notes'] = medical_notes
            
            messages.success(request, 'Patient profile updated successfully.')
        else:
            messages.error(request, 'Patient record not found.')
    return redirect('settings')

@login_required
def settings_api_data(request):
    """API endpoint to return settings data as JSON"""
    caregiver = request.user
    patient = Patient.objects.filter(caregiver=caregiver).first()
    
    full_name = f"{caregiver.first_name} {caregiver.last_name}".strip() or caregiver.username
    
    data = {
        'caregiver_full_name': full_name,
        'caregiver_email': caregiver.email or '',
        'caregiver_phone': getattr(caregiver, 'profile', None) and caregiver.profile.phone or request.session.get('caregiver_phone', ''),
        'caregiver_username': caregiver.username,
        'patient_first_name': patient.first_name if patient else '',
        'patient_last_name': patient.last_name if patient else '',
        'patient_dob': patient.date_of_birth.strftime('%Y-%m-%d') if patient and patient.date_of_birth else '',
        'patient_diagnosis': patient.diagnosis if patient else '',
        'patient_emergency_contact': patient.emergency_contact if patient else '',
        # 'patient_medical_notes': patient.medical_notes if patient else request.session.get('patient_medical_notes', ''),
        'patient_created_at': patient.created_at.strftime('%b %Y') if patient and patient.created_at else '',
    }
    return JsonResponse(data)