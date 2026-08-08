from django.contrib import admin

from shop.models.car import Car
from shop.models.garage import Garage, GarageInvitation, GarageMembership, KnownShop
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.models.user import ShopUser


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
	list_display = ("usual_name", "make", "year", "license_plate", "vin")
	search_fields = ("usual_name", "make", "vin", "license_plate")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
	list_display = ("job_name", "car", "date_done", "assigned_to", "assigned_shop")
	list_filter = ("date_done",)
	search_fields = ("job_name", "note")


@admin.register(WorkJob)
class WorkJobAdmin(admin.ModelAdmin):
	list_display = ("title", "car", "status", "urgency", "planned_date", "assigned_to", "assigned_shop")
	list_filter = ("status", "urgency")
	search_fields = ("title", "notes")


@admin.register(ShopUser)
class ShopUserAdmin(admin.ModelAdmin):
	list_display = ("username", "email", "display_name", "is_mechanic", "auth_provider")
	list_filter = ("is_mechanic", "auth_provider", "is_staff", "is_active")
	search_fields = ("username", "email", "display_name", "hanko_id")


@admin.register(Garage)
class GarageAdmin(admin.ModelAdmin):
	list_display = ("name", "created_by", "created_at")
	search_fields = ("name",)


@admin.register(GarageMembership)
class GarageMembershipAdmin(admin.ModelAdmin):
	list_display = ("garage", "user", "role", "joined_at")
	list_filter = ("role",)
	search_fields = ("garage__name", "user__username", "user__email")


@admin.register(GarageInvitation)
class GarageInvitationAdmin(admin.ModelAdmin):
	list_display = ("garage", "invited_email", "status", "invited_by", "created_at", "expires_at")
	list_filter = ("status",)
	search_fields = ("garage__name", "invited_email", "invited_by__email")


@admin.register(KnownShop)
class KnownShopAdmin(admin.ModelAdmin):
	list_display = ("name", "email", "phone")
	search_fields = ("name", "email", "phone")

