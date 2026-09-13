from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline

from car_docs.models import CarDoc
from shop.models.attachment import Attachment


class AttachmentInline(GenericTabularInline):
    model = Attachment
    extra = 0
    fields = ('source_type', 'kind', 'file', 'url', 'display_name', 'mime_type', 'order')
    readonly_fields = ('created_at',)


@admin.register(CarDoc)
class CarDocAdmin(admin.ModelAdmin):
    list_display = ('title', 'car', 'updated_at')
    list_filter = ('car',)
    search_fields = ('title', 'content')
    inlines = (AttachmentInline,)
