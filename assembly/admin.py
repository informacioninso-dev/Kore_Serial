from django.contrib import admin

from .models import (
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    InstalledComponent,
    ProductVersion,
    ProductionPlan,
    ProductionQueueItem,
    QualityGate,
    ReleaseApproval,
    ReworkOrder,
    RouteStepComponentRequirement,
    SerializedUnit,
    UnitStationEvent,
)


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
    list_display = ("serial_number", "version", "production_plan", "status", "created_at")
    search_fields = ("serial_number", "version__code", "version__product__code", "version__product__name", "production_plan__code")
    list_filter = ("status", "production_plan")
    autocomplete_fields = ("production_plan",)


@admin.register(AssemblyLine)
class AssemblyLineAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "takt_time_seconds", "is_active")
    search_fields = ("code", "name")
    list_filter = ("is_active",)


@admin.register(ProductionPlan)
class ProductionPlanAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "version", "line", "planned_date", "shift", "target_quantity", "status", "priority")
    search_fields = ("code", "version__code", "version__product__code", "line__code", "line__name")
    list_filter = ("status", "priority", "line", "planned_date")
    autocomplete_fields = ("version", "line")


@admin.register(ProductionQueueItem)
class ProductionQueueItemAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("line", "sequence", "unit", "production_plan", "route", "status", "priority")
    search_fields = ("unit__serial_number", "production_plan__code", "line__code", "route__code")
    list_filter = ("status", "priority", "line")
    autocomplete_fields = ("production_plan", "unit", "line", "route")


@admin.register(AssemblyStation)
class AssemblyStationAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "line", "sequence", "requires_quality_gate", "is_active")
    search_fields = ("code", "name", "line__code", "line__name")
    list_filter = ("line", "requires_quality_gate", "is_active")
    filter_horizontal = ("equipment", "authorized_operators")


class AssemblyRouteStepInline(admin.TabularInline):
    model = AssemblyRouteStep
    extra = 0
    autocomplete_fields = ("station",)


@admin.register(AssemblyRoute)
class AssemblyRouteAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "revision", "name", "version", "approval_status", "is_active")
    search_fields = ("code", "revision", "name", "version__code", "version__product__code")
    list_filter = ("approval_status", "is_active")
    inlines = (AssemblyRouteStepInline,)


@admin.register(AssemblyRouteStep)
class AssemblyRouteStepAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("route", "sequence", "name", "station", "requires_component_trace", "requires_quality_gate", "is_active")
    search_fields = ("name", "route__code", "station__code", "station__name")
    list_filter = ("requires_component_trace", "requires_quality_gate", "is_active")
    autocomplete_fields = ("route", "station")


@admin.register(RouteStepComponentRequirement)
class RouteStepComponentRequirementAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("route_step", "part_code", "part_name", "quantity_required", "traceability", "is_critical", "is_active")
    search_fields = ("part_code", "part_name", "route_step__name", "route_step__route__code", "route_step__station__code")
    list_filter = ("traceability", "is_critical", "is_active")
    autocomplete_fields = ("route_step",)


@admin.register(UnitStationEvent)
class UnitStationEventAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("unit", "station", "event_type", "event_at", "operator", "source")
    search_fields = ("unit__serial_number", "station__code", "external_reference")
    list_filter = ("event_type", "source", "station")
    autocomplete_fields = ("unit", "station", "route_step", "operator")


@admin.register(InstalledComponent)
class InstalledComponentAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("unit", "part_code", "serial_number", "lot_number", "quantity", "station", "is_critical")
    search_fields = ("unit__serial_number", "part_code", "part_name", "serial_number", "lot_number")
    list_filter = ("is_critical", "station")
    autocomplete_fields = ("unit", "station", "route_step", "requirement", "installed_by", "source_event")


@admin.register(QualityGate)
class QualityGateAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("unit", "station", "status", "is_blocking", "inspected_by", "inspected_at")
    search_fields = ("unit__serial_number", "station__code", "evidence_reference")
    list_filter = ("status", "is_blocking", "station")
    autocomplete_fields = ("unit", "station", "route_step", "inspected_by")


@admin.register(ReworkOrder)
class ReworkOrderAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("unit", "defect_code", "status", "station_detected", "opened_at", "closed_at", "closure_evidence_reference")
    search_fields = ("unit__serial_number", "defect_code", "description", "closure_evidence_reference")
    list_filter = ("status", "station_detected")
    autocomplete_fields = ("unit", "station_detected", "route_step_detected", "opened_by", "closed_by", "reinspection_gate")


@admin.register(ReleaseApproval)
class ReleaseApprovalAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("unit", "decision", "decided_by", "decided_at", "created_at")
    search_fields = ("unit__serial_number", "evidence_reference")
    list_filter = ("decision",)
    autocomplete_fields = ("unit", "decided_by")
