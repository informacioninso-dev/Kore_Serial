from django.contrib import admin

from .models import ChangeControl, ChangeControlSignature


@admin.register(ChangeControl)
class ChangeControlAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "risk", "status", "opened_on")
    list_filter = ("status", "risk")
    search_fields = ("code", "title")


@admin.register(ChangeControlSignature)
class ChangeControlSignatureAdmin(admin.ModelAdmin):
    """Solo lectura: una firma no se edita ni se crea a mano."""
    list_display = ("change_control", "decision", "signed_by", "signed_at", "revoked_at")
    list_filter = ("decision",)
    search_fields = ("change_control__code", "signed_by__username")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
