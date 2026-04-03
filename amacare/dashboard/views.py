from django.shortcuts import render
# from .models import Medication

def home(request):
    # meds = Medication.objects.all()
    # return render(request, "home.html", {"meds": meds})
    return render(request, "dashboard.html")