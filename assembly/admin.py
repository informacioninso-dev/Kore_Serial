from django.contrib import admin

from .models import AssembledProduct, ProductVersion, SerializedUnit


class AuditAdminMixin:
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AssembledProduct)
class AssembledProductAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")
    list_filter = ("is_active",)


@admin.register(ProductVersion)
class ProductVersionAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "product", "is_active")
    search_fields = ("code", "name", "product__code", "product__name")
    list_filter = ("is_active",)


@admin.register(SerializedUnit)
class SerializedUnitAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("serial_number", "version", "status", "created_at")
    search_fields = ("serial_number", "version__code", "version__product__code", "version__product__name")
    list_filter = ("status",)
