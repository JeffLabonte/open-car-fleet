from django.contrib import admin
from .models import Car, Report, WorkJob


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
	list_display = ("usual_name", "make", "year", "license_plate", "vin")
	search_fields = ("usual_name", "make", "vin", "license_plate")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
	list_display = ("job_name", "car", "date_done")
	list_filter = ("date_done",)
	search_fields = ("job_name", "note")


@admin.register(WorkJob)
class WorkJobAdmin(admin.ModelAdmin):
	list_display = ("title", "car", "status", "urgency", "planned_date", "assigned_to")
	list_filter = ("status", "urgency")
	search_fields = ("title", "notes")

