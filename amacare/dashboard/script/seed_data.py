from dashboard.models import Patient, ChatSession, ChatMessage
from django.utils import timezone
from datetime import datetime


# ✅ Helper to create timezone-aware datetime
def dt(y, m, d, h, minute):
    return timezone.make_aware(datetime(y, m, d, h, minute))


def run():
    # Get patient
    patient = Patient.objects.get(id=1)

    # ================================
    # Session 1: Morning Routine
    # ================================
    s1 = ChatSession.objects.create(
        patient=patient,
        title="Morning Routine",
        started_at=dt(2026, 4, 5, 9, 15),
        ended_at=dt(2026, 4, 5, 9, 45),
        dominant_mood="confused",
        flags="Confusion about location, Repeated questioning",
    )

    ChatMessage.objects.bulk_create([
        ChatMessage(session=s1, sender="patient", content="Where am I?",
                    timestamp=dt(2026, 4, 5, 9, 15),
                    detected_mood="confused", flagged_keywords=["confused"]),

        ChatMessage(session=s1, sender="bot",
                    content="You are at home, Mr. Tan. You're safe.",
                    timestamp=dt(2026, 4, 5, 9, 16)),

        ChatMessage(session=s1, sender="patient",
                    content="I want to go to work now. I’m late.",
                    timestamp=dt(2026, 4, 5, 9, 18),
                    detected_mood="anxious", flagged_keywords=["anxious"]),

        ChatMessage(session=s1, sender="bot",
                    content="You are retired. There’s no need to go to work. Would you like to have breakfast?",
                    timestamp=dt(2026, 4, 5, 9, 19)),

        ChatMessage(session=s1, sender="patient",
                    content="Oh… okay… I forgot.",
                    timestamp=dt(2026, 4, 5, 9, 22),
                    detected_mood="neutral"),

        ChatMessage(session=s1, sender="patient",
                    content="Thank you.",
                    timestamp=dt(2026, 4, 5, 9, 30),
                    detected_mood="calm"),
    ])

    s1.message_count = s1.messages.count()
    s1.save()

    # ================================
    # Session 2: Afternoon Check-in
    # ================================
    s2 = ChatSession.objects.create(
        patient=patient,
        title="Afternoon Check-in",
        started_at=dt(2026, 4, 5, 14, 10),
        ended_at=dt(2026, 4, 5, 14, 40),
        dominant_mood="anxious",
        flags="Loneliness, Emotional distress",
    )

    ChatMessage.objects.bulk_create([
        ChatMessage(session=s2, sender="patient",
                    content="Why no one visit me?",
                    timestamp=dt(2026, 4, 5, 14, 10),
                    detected_mood="distressed", flagged_keywords=["lonely"]),

        ChatMessage(session=s2, sender="bot",
                    content="Your family cares about you very much. They will visit you soon.",
                    timestamp=dt(2026, 4, 5, 14, 12)),

        ChatMessage(session=s2, sender="patient",
                    content="I feel very lonely.",
                    timestamp=dt(2026, 4, 5, 14, 15),
                    detected_mood="distressed", flagged_keywords=["lonely"]),

        ChatMessage(session=s2, sender="bot",
                    content="I am here with you. Would you like to listen to some music?",
                    timestamp=dt(2026, 4, 5, 14, 18)),

        ChatMessage(session=s2, sender="patient",
                    content="Okay… maybe music is good.",
                    timestamp=dt(2026, 4, 5, 14, 25),
                    detected_mood="calm"),
    ])

    s2.message_count = s2.messages.count()
    s2.save()

    # ================================
    # Session 3: Night Confusion
    # ================================
    s3 = ChatSession.objects.create(
        patient=patient,
        title="Night Confusion",
        started_at=dt(2026, 4, 4, 23, 30),
        ended_at=dt(2026, 4, 4, 23, 55),
        dominant_mood="distressed",
        flags="Night confusion, Fear, Disorientation",
    )

    ChatMessage.objects.bulk_create([
        ChatMessage(session=s3, sender="patient",
                    content="It’s very dark… where is everyone?",
                    timestamp=dt(2026, 4, 4, 23, 30),
                    detected_mood="anxious", flagged_keywords=["scared"]),

        ChatMessage(session=s3, sender="bot",
                    content="You are at home. It’s nighttime now. Everything is okay.",
                    timestamp=dt(2026, 4, 4, 23, 31)),

        ChatMessage(session=s3, sender="patient",
                    content="I hear something… is someone there?",
                    timestamp=dt(2026, 4, 4, 23, 33),
                    detected_mood="distressed", flagged_keywords=["fear"]),

        ChatMessage(session=s3, sender="bot",
                    content="There is no danger. It might be just outside noise.",
                    timestamp=dt(2026, 4, 4, 23, 35)),

        ChatMessage(session=s3, sender="patient",
                    content="I feel scared.",
                    timestamp=dt(2026, 4, 4, 23, 40),
                    detected_mood="distressed", flagged_keywords=["scared"]),

        ChatMessage(session=s3, sender="bot",
                    content="I will stay with you. Try to relax.",
                    timestamp=dt(2026, 4, 4, 23, 45)),

        ChatMessage(session=s3, sender="patient",
                    content="Okay… don’t leave me.",
                    timestamp=dt(2026, 4, 4, 23, 50),
                    detected_mood="anxious"),
    ])

    s3.message_count = s3.messages.count()
    s3.save()

    print("✅ Seed data inserted successfully!")