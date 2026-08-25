from django.contrib import admin

from .models import (
    AndonSignal,
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    EquipmentInboundEvent,
    ExternalMaterialKit,
    InstalledComponent,
    LineBalanceStudy,
    Plant,
    PlantArea,
    ProductionMeasurement,
    ProductionOrder,
    ModelMixPlan,
    ModelMixPlanItem,
    ProductVersion,
    ProductionDowntime,
    ProductionPlan,
    ProductionQueueItem,
    QualityGate,
    ReleaseApproval,
    ReworkOrder,
    RouteStepComponentRequirement,
    RouteStepParameter,
    SerializedUnit,
    StationOfflineEvent,
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


@admin.register(Plant)
class PlantAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "address", "is_active")
    search_fields = ("code", "name", "address")
    list_filter = ("is_active",)


@admin.register(PlantArea)
class PlantAreaAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "plant", "is_active")
    search_fields = ("code", "name", "plant__code", "plant__name")
    list_filter = ("plant", "is_active")
    autocomplete_fields = ("plant",)


@admin.register(ProductionOrder)
class ProductionOrderAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "product", "version", "plant", "target_quantity", "due_date", "status", "priority")
    search_fields = ("code", "external_reference", "product__code", "product__name", "version__code", "plant__code")
    list_filter = ("status", "priority", "plant", "due_date")
    autocomplete_fields = ("product", "version", "plant")


@admin.register(SerializedUnit)
class SerializedUnitAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("serial_number", "production_order", "version", "production_plan", "status", "created_at")
    search_fields = ("serial_number", "production_order__code", "version__code", "version__product__code", "version__product__name", "production_plan__code")
    list_filter = ("status", "production_order", "production_plan")
    autocomplete_fields = ("production_order", "production_plan")


@admin.register(AssemblyLine)
class AssemblyLineAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "area", "takt_time_seconds", "is_active")
    search_fields = ("code", "name", "area__code", "area__plant__code")
    list_filter = ("area", "is_active")
    autocomplete_fields = ("area",)


@admin.register(ProductionPlan)
class ProductionPlanAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "production_order", "version", "line", "planned_date", "shift", "target_quantity", "status", "priority")
    search_fields = ("code", "production_order__code", "version__code", "version__product__code", "line__code", "line__name")
    list_filter = ("status", "priority", "line", "planned_date")
    autocomplete_fields = ("production_order", "version", "line")


@admin.register(ProductionQueueItem)
class ProductionQueueItemAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("line", "sequence", "unit", "production_plan", "route", "status", "priority")
    search_fields = ("unit__serial_number", "production_plan__code", "line__code", "route__code")
    list_filter = ("status", "priority", "line")
    autocomplete_fields = ("production_plan", "unit", "line", "route")


@admin.register(LineBalanceStudy)
class LineBalanceStudyAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "line", "version", "production_plan", "status", "generated_at")
    search_fields = ("code", "line__code", "line__name", "version__code", "route__code", "production_plan__code")
    list_filter = ("status", "line")
    autocomplete_fields = ("line", "version", "route", "production_plan")
    readonly_fields = ("generated_at", "snapshot", "recommendations")


class ModelMixPlanItemInline(admin.TabularInline):
    model = ModelMixPlanItem
    extra = 0
    autocomplete_fields = ("version", "production_plan")


@admin.register(ModelMixPlan)
class ModelMixPlanAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "line", "planned_date", "shift", "status")
    search_fields = ("code", "line__code", "line__name", "shift")
    list_filter = ("status", "line", "planned_date")
    autocomplete_fields = ("line",)
    inlines = (ModelMixPlanItemInline,)


@admin.register(ModelMixPlanItem)
class ModelMixPlanItemAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("mix_plan", "version", "planned_quantity", "sequence_bias", "priority", "production_plan")
    search_fields = ("mix_plan__code", "version__code", "version__product__code", "production_plan__code")
    list_filter = ("priority",)
    autocomplete_fields = ("mix_plan", "version", "production_plan")


@admin.register(ExternalMaterialKit)
class ExternalMaterialKitAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "external_system", "version", "production_plan", "status", "expected_quantity", "received_quantity")
    search_fields = ("code", "external_reference", "container_code", "lot_number", "version__code", "production_plan__code")
    list_filter = ("status", "external_system")
    autocomplete_fields = ("version", "production_plan", "line")


@admin.register(AndonSignal)
class AndonSignalAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "line", "station", "severity", "status", "opened_at", "resolved_at")
    search_fields = ("code", "title", "description", "line__code", "station__code", "unit__serial_number")
    list_filter = ("status", "severity", "line")
    autocomplete_fields = ("line", "station", "unit", "production_plan", "opened_by", "acknowledged_by", "resolved_by")


@admin.register(ProductionDowntime)
class ProductionDowntimeAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "line", "station", "cause_category", "cause_code", "status", "started_at", "ended_at")
    search_fields = ("code", "cause_code", "cause_description", "line__code", "station__code", "unit__serial_number")
    list_filter = ("status", "cause_category", "line")
    autocomplete_fields = ("line", "station", "unit", "production_plan", "andon_signal", "opened_by", "closed_by")


@admin.register(StationOfflineEvent)
class StationOfflineEventAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("external_id", "station", "unit_serial_number", "event_type", "status", "captured_at", "synced_at")
    search_fields = ("external_id", "station__code", "unit_serial_number", "operator_username", "result_detail")
    list_filter = ("status", "event_type", "station")
    autocomplete_fields = ("station", "station_event")
    readonly_fields = ("result_detail", "synced_at", "station_event")


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


@admin.register(RouteStepParameter)
class RouteStepParameterAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("route_step", "code", "name", "parameter_type", "unit", "origin", "is_required", "is_quality_critical", "is_active")
    search_fields = ("code", "name", "route_step__name", "route_step__route__code", "route_step__station__code")
    list_filter = ("parameter_type", "origin", "is_required", "is_quality_critical", "is_active")
    autocomplete_fields = ("route_step",)


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


@admin.register(EquipmentInboundEvent)
class EquipmentInboundEventAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("external_id", "equipment_code", "unit_serial_number", "event_type", "status", "received_at")
    search_fields = ("external_id", "equipment_code", "unit_serial_number", "operator_username")
    list_filter = ("status", "event_type")
    autocomplete_fields = ("station", "unit", "operator", "station_event")
    raw_id_fields = ("equipment",)
    readonly_fields = ("received_at", "processed_at", "payload", "result_detail")


@admin.register(ProductionMeasurement)
class ProductionMeasurementAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("unit", "station", "code", "value", "unit_label", "result", "origin", "measured_at")
    search_fields = ("unit__serial_number", "station__code", "code", "name", "evidence_reference")
    list_filter = ("result", "origin", "station")
    autocomplete_fields = ("unit", "station", "route_step", "parameter", "station_event", "measured_by")


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
