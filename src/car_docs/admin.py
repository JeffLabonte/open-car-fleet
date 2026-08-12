from django.contrib import admin

from car_docs.models import CarDoc


@admin.register(CarDoc)
class CarDocAdmin(admin.ModelAdmin):
    list_display = ('title', 'car', 'updated_at')
    list_filter = ('car',)
    search_fields = ('title', 'content')
