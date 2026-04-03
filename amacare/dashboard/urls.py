from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="dashboard"),
    path("settings/", views.settings, name="settings"),
    path("medication/", views.medication, name="medication"),
    path("chat/", views.chat, name="chat"),
    path("mood/", views.mood, name="mood"),
    path("location/", views.location, name="location"),
]