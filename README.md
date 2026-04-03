# AmaCare
AmaCare is an AI-powered companion system designed to support elderly care and enable semi-independent living for elderly or Alzheimer's patients. The system integrates an AI robot, caregiver dashboard, and real-time monitoring features, providing peace of mind to families and caregivers while empowering patients.

#### Features
* Robot Connection & Status: Monitor ESP32 robot online/offline status, battery, and last heartbeat. Uses MQTT/WebSocket for real-time updates.
* Medication Schedule & Compliance: Set weekly medication schedules. Robot confirms patient acknowledgment via voice; caregiver sees taken/missed logs with timestamps.
* Chat History Log: All conversations are logged, timestamped, and viewable by caregivers. Detects distress keywords like pain, help, confused, scared.
* GPS Location & Safe Zones: Track patient's location on a live map. Alert caregivers if patient exits a defined safe zone.
* Mood & Wellbeing Tracking: Generate mood scores from conversation sentiment. Show weekly mood trends and alert caregivers if the patient shows prolonged distress.
#### Future Version
* Earphone Integration & Subscription: Stream AI voice via Bluetooth earphones. Family plans and premium features available through subscription.
#### App Screens
* Dashboard: Patient status, last seen location, today's meds, quick alerts.
* Location: Live GPS map, safe zone setup, movement history.
* Medication: Weekly schedule, dose log, refill reminders.
* Chat History: AI robot conversations, mood indicators, exportable logs.
* Settings: Robot config, safe zones, medication schedule, alert preferences.
* Mood & Wellbeing: (Planned) Sentiment trends and weekly mood charts.
#### Technical Stack
