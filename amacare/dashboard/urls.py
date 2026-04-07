from django.urls import path
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from . import views

urlpatterns = [
    # Authentication URLs
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    
    # Protected URLs (will redirect to login if not authenticated)
    path("dashboard/", login_required(views.dashboard), name="dashboard"),
    path("", views.landing, name="landing"),
    path("settings/", login_required(views.settings), name="settings"),
    path("medication/", login_required(views.medication), name="medication"),
    path("chat/", login_required(views.chat), name="chat"),
    path("mood/", login_required(views.mood_page), name="mood"),
    path("location/", login_required(views.location), name="location"),
    
    # API URLs
    path('api/location/update/', views.api_update_location, name='api_update_location'),
    path('api/location/logs/', views.api_location_logs, name='api_location_logs'),
    path('api/safe-zones/', views.api_safe_zones, name='api_safe_zones'),
    path('api/safe-zones/<int:zone_id>/delete/', views.api_safe_zone_delete, name='api_safe_zone_delete'),
    path("api/update-dose/",          views.update_dose,        name="update_dose"),
    path("api/get-doses/",            views.get_doses,          name="get_doses"),
    path("api/save-medication/",      views.save_medication,    name="save_medication"),
    path("api/delete-medication/",    views.delete_medication,  name="delete_medication"),
    path("api/send-refill-alert/",    views.send_refill_alert,  name="send_refill_alert"),
    path("api/settings-view/",       views.settings_view,      name="settings_view"),
    path('api/settings-data/', views.settings_api_data, name='settings_api_data'),
    path('settings/update_caregiver/', views.update_caregiver, name='update_caregiver'),
    path('settings/update_patient/', views.update_patient, name='update_patient'),
    path('mood/api/summary/',            views.mood_api_summary,       name='mood_api_summary'),
    path('mood/api/notes/',              views.mood_api_notes,         name='mood_api_notes'),
    path('mood/api/notes/save/',         views.mood_api_note_save,     name='mood_api_note_save'),
    path('mood/api/notes/<int:pk>/delete/', views.mood_api_note_delete, name='mood_api_note_delete'),
    path('mood/api/physical/',           views.mood_api_physical,      name='mood_api_physical'),
    path('mood/api/physical/save/',      views.mood_api_physical_save, name='mood_api_physical_save'),
    path('mood/api/physical/<int:pk>/',  views.mood_api_physical_detail, name='mood_api_physical_detail'),
    path('mood/api/ai-insights/',        views.mood_api_ai_insights,   name='mood_api_ai_insights'),
    path('session/<int:session_id>/', views.session_messages, name='session_messages'),
    path('export/<int:session_id>/', views.export_transcript, name='export_transcript'),
    path('analyse/', views.analyse_sessions, name='chat_analyse'),
]