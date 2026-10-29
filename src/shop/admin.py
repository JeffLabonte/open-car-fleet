from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from django.utils.translation import gettext_lazy as _

from shop.models.attachment import Attachment
from shop.models.car import Car
from shop.models.fleet import Fleet, FleetInvitation, FleetMembership, KnownShop
from shop.models.inspection import Inspection
from shop.models.inspection_point import InspectionPoint
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.models.user import ShopUser


class AttachmentInline(GenericTabularInline):
    model = Attachment
    extra = 0
    fields = ("source_type", "kind", "file", "url", "display_name", "mime_type", "order")
    readonly_fields = ("created_at",)


class InspectionPointInline(admin.TabularInline):
    model = InspectionPoint
    extra = 0
    fields = ("category_label", "label", "status", "measurement", "notes")
    readonly_fields = ("category_label", "label")
    ordering = ("position",)


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    list_display = ("usual_name", "make", "year", "license_plate", "vin")
    search_fields = ("usual_name", "make", "vin", "license_plate")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("job_name", "car", "date_done", "assigned_to", "assigned_shop")
    list_filter = ("date_done",)
    search_fields = ("job_name", "note")
    inlines = (AttachmentInline,)


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ("car", "inspected_at", "mileage", "use_structured_checklist", "created_by")
    list_filter = ("inspected_at", "use_structured_checklist")
    search_fields = ("car__usual_name", "car__vin", "car__license_plate", "notes")
    inlines = (AttachmentInline, InspectionPointInline)

    def has_delete_permission(self, request, obj=None):
        return False


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


@admin.register(Fleet)
class FleetAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    search_fields = ("name",)


@admin.register(FleetMembership)
class FleetMembershipAdmin(admin.ModelAdmin):
    list_display = ("fleet", "user", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("fleet__name", "user__username", "user__email")


@admin.register(FleetInvitation)
class FleetInvitationAdmin(admin.ModelAdmin):
    list_display = ("fleet", "invited_email", "status", "invited_by", "created_at", "expires_at")
    list_filter = ("status",)
    search_fields = ("fleet__name", "invited_email", "invited_by__email")


@admin.register(KnownShop)
class KnownShopAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone")
    search_fields = ("name", "email", "phone")
    inlines = (AttachmentInline,)


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("display_name", "kind", "source_type", "parent_label")
    list_filter = ("kind", "source_type")
    search_fields = ("display_name", "url")

    @admin.display(description="Parent")
    def parent_label(self, obj):
        if obj.content_type is None:
            return _("Staged upload")
        return f"{obj.content_type.name}: {obj.object_id}"
