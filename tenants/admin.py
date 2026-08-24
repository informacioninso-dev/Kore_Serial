from django.contrib import admin

from .models import Client, Domain, Plan, TenantHealthCheck, TenantMembership, TenantModule


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "min_users", "max_users", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


class TenantModuleInline(admin.TabularInline):
    model = TenantModule
    extra = 0
    fields = ("module", "enabled", "updated_at")
    readonly_fields = ("updated_at",)
    verbose_name = "Módulo opcional"
    verbose_name_plural = "Módulos opcionales"

    def get_extra(self, request, obj=None, **kwargs):
        if obj and obj.modules.exists():
            return 0
        return len(TenantModule._meta.get_field("module").choices)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "schema_name", "plan", "is_active", "modules_summary", "created_on")
    list_filter = ("plan", "is_active")
    search_fields = ("name", "schema_name")
    readonly_fields = ("schema_name", "created_on")
    inlines = [TenantModuleInline]

    def modules_summary(self, obj):
        enabled = obj.modules.filter(enabled=True).values_list("module", flat=True)
        if not enabled:
            return "—"
        return ", ".join(enabled)
    modules_summary.short_description = "Módulos activos"

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Asegurar que existan registros para todos los módulos disponibles
        TenantModule.ensure_all_exist(form.instance)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("domain", "tenant__name", "tenant__schema_name")


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ("tenant", "user", "is_admin", "is_active")
    list_filter = ("is_admin", "is_active")
    search_fields = ("tenant__name", "tenant__schema_name", "user__username", "user__email")


@admin.register(TenantHealthCheck)
class TenantHealthCheckAdmin(admin.ModelAdmin):
    list_display = ("checked_at", "tenant", "state", "status_code", "latency_ms", "domain")
    list_filter = ("state", "checked_at")
    search_fields = ("tenant__name", "tenant__schema_name", "domain", "error")
    readonly_fields = (
        "tenant",
        "domain",
        "url",
        "state",
        "status_code",
        "latency_ms",
        "schema_name",
        "status_value",
        "error",
        "checked_at",
    )

    def has_add_permission(self, request):
        return False
