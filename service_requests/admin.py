from django.contrib import admin

from .models import ServiceRequest


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ('reference_number', 'citizen', 'category', 'status', 'location', 'created_at')
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('reference_number', 'location', 'description', 'citizen__username')
    readonly_fields = ('reference_number', 'created_at', 'updated_at')
