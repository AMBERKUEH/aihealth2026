from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="dashboard"),
    path("settings/", views.settings, name="settings"),
    path("medication/", views.medication, name="medication"),
    path("chat/", views.chat, name="chat"),
    path("mood/", views.mood, name="mood"),
    path("location/", views.location, name="location"),
    path('api/location/update/', views.api_update_location, name='api_update_location'),
    path('api/location/logs/', views.api_location_logs, name='api_location_logs'),
    path('api/safe-zones/', views.api_safe_zones, name='api_safe_zones'),
    path('api/safe-zones/<int:zone_id>/delete/', views.api_safe_zone_delete, name='api_safe_zone_delete'),
]