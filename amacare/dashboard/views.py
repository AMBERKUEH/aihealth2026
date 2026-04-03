from django.shortcuts import render
# from .models import Medication

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

def location(request):
    return render(request, "location.html")