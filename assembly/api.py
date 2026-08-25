from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AssemblyStation,
    EquipmentInboundEvent,
    EquipmentInboundEventStatus,
    ProductiveParameterOrigin,
    QualityDefectClassification,
    QualityDefectSeverity,
    QualityGateStatus,
    SerializedUnit,
    StationOfflineEvent,
    StationOfflineEventStatus,
    StationEventType,
)
from .services import (
    current_route_step_for,
    install_component,
    process_equipment_event,
    record_measurement,
    record_station_event,
    review_quality_gate,
)


API_PERMISSIONS = {
    "consult_units": "assembly.view_serializedunit",
    "register_station_events": "assembly.add_unitstationevent",
    "install_components": "assembly.add_installedcomponent",
    "review_quality": "assembly.change_qualitygate",
    "receive_equipment_events": "assembly.add_equipmentinboundevent",
    "view_equipment_events": "assembly.view_equipmentinboundevent",
    "sync_offline_events": "assembly.add_stationofflineevent",
    "record_measurements": "assembly.add_productionmeasurement",
}


def _step_payload(route, step):
    if step is None:
        return None
    return {
        "route": {"code": route.code, "revision": route.revision},
        "sequence": step.sequence,
        "name": step.name,
        "station": {"code": step.station.code, "name": step.station.name, "line_code": step.station.line.code},
        "requires_component_trace": step.requires_component_trace,
        "requires_quality_gate": step.requires_quality_gate,
        "instructions": step.instructions,
        "safety_notes": step.safety_notes,
        "acceptance_criteria": step.acceptance_criteria,
        "media_reference": step.media_reference,
        "parameters": [
            {
                "id": parameter.pk,
                "code": parameter.code,
                "name": parameter.name,
                "type": parameter.parameter_type,
                "unit": parameter.unit,
                "target_value": parameter.target_value,
                "min_value": parameter.min_value,
                "max_value": parameter.max_value,
                "origin": parameter.origin,
                "is_required": parameter.is_required,
                "is_quality_critical": parameter.is_quality_critical,
            }
            for parameter in step.parameters.filter(is_active=True).order_by("code")
        ],
    }


def _unit_payload(unit):
    route, step = current_route_step_for(unit)
    return {
        "serial_number": unit.serial_number,
        "status": unit.status,
        "status_label": unit.get_status_display(),
        "product": {"code": unit.version.product.code, "name": unit.version.product.name},
        "version": {"code": unit.version.code, "name": unit.version.name},
        "production_plan": unit.production_plan.code if unit.production_plan_id else "",
        "production_order": unit.production_order.code if unit.production_order_id else "",
        "current_step": _step_payload(route, step),
        "as_built_complete": unit.as_built_complete,
        "measurement_issues": unit.measurement_issues(),
    }


class MESAPIView(APIView):
    required_permission = ""

    def enforce_permission(self, permission=None):
        permission = permission or self.required_permission
        if permission and not self.request.user.has_perm(permission):
            raise PermissionDenied("El token no tiene permiso para esta operacion MES.")


class EquipmentEventSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=120)
    equipment_code = serializers.CharField(max_length=50)
    station_code = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    unit_serial_number = serializers.CharField(max_length=120)
    operator_username = serializers.CharField(max_length=150)
    event_type = serializers.ChoiceField(choices=StationEventType.choices)
    event_at = serializers.DateTimeField(required=False, default=timezone.now)
    payload = serializers.JSONField(required=False, default=dict)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class StationEventSerializer(serializers.Serializer):
    unit_serial_number = serializers.CharField(max_length=120)
    station_code = serializers.CharField(max_length=50)
    event_type = serializers.ChoiceField(choices=StationEventType.choices)
    operator_username = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    event_at = serializers.DateTimeField(required=False, default=timezone.now)
    external_reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    metadata = serializers.JSONField(required=False, default=dict)


class StationOfflineEventSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=120)
    station_code = serializers.CharField(max_length=50)
    unit_serial_number = serializers.CharField(max_length=120)
    operator_username = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    event_type = serializers.ChoiceField(choices=StationEventType.choices)
    captured_at = serializers.DateTimeField(required=False, default=timezone.now)
    payload = serializers.JSONField(required=False, default=dict)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    auto_sync = serializers.BooleanField(required=False, default=True)


class InstalledComponentSerializer(serializers.Serializer):
    unit_serial_number = serializers.CharField(max_length=120)
    requirement_id = serializers.IntegerField(min_value=1)
    serial_number = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    lot_number = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    quantity = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"), required=False, default=1)
    operator_username = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    installed_at = serializers.DateTimeField(required=False, default=timezone.now)
    source_event_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class MeasurementSerializer(serializers.Serializer):
    unit_serial_number = serializers.CharField(max_length=120)
    parameter_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    station_code = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    code = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    name = serializers.CharField(max_length=180, required=False, allow_blank=True, default="")
    value = serializers.DecimalField(max_digits=14, decimal_places=4, required=False, allow_null=True, default=None)
    text_value = serializers.CharField(max_length=180, required=False, allow_blank=True, default="")
    origin = serializers.ChoiceField(choices=ProductiveParameterOrigin.choices, required=False, default=ProductiveParameterOrigin.API)
    measured_at = serializers.DateTimeField(required=False, default=timezone.now)
    station_event_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    evidence_reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class QualityDecisionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[QualityGateStatus.PASSED, QualityGateStatus.FAILED, QualityGateStatus.WAIVED])
    evidence_reference = serializers.CharField(max_length=120)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    inspector_username = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    defect_code = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    defect_classification = serializers.ChoiceField(
        choices=QualityDefectClassification.choices,
        required=False,
        default=QualityDefectClassification.OTHER,
    )
    defect_severity = serializers.ChoiceField(
        choices=QualityDefectSeverity.choices,
        required=False,
        default=QualityDefectSeverity.MINOR,
    )
    root_cause = serializers.CharField(max_length=180, required=False, allow_blank=True, default="")
    responsible_area = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


class IntegrationProfileView(MESAPIView):
    def get(self, request):
        return Response(
            {
                "username": request.user.get_username(),
                "permissions": {
                    operation: request.user.has_perm(permission)
                    for operation, permission in API_PERMISSIONS.items()
                },
            }
        )


class UnitDetailView(MESAPIView):
    required_permission = API_PERMISSIONS["consult_units"]

    def get(self, request, serial_number):
        self.enforce_permission()
        unit = SerializedUnit.objects.select_related("production_order", "version__product", "production_plan").filter(serial_number=serial_number).first()
        if unit is None:
            raise NotFound("Unidad no encontrada.")
        return Response(_unit_payload(unit))


class UnitCurrentStepView(MESAPIView):
    required_permission = API_PERMISSIONS["consult_units"]

    def get(self, request, serial_number):
        self.enforce_permission()
        unit = SerializedUnit.objects.select_related("production_order", "version__product", "production_plan").filter(serial_number=serial_number).first()
        if unit is None:
            raise NotFound("Unidad no encontrada.")
        route, step = current_route_step_for(unit)
        return Response({"serial_number": unit.serial_number, "current_step": _step_payload(route, step)})


class StationEventCreateView(MESAPIView):
    required_permission = API_PERMISSIONS["register_station_events"]

    def post(self, request):
        self.enforce_permission()
        serializer = StationEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            event, created = record_station_event(actor=request.user, **serializer.validated_data)
        except ValueError as error:
            raise ValidationError({"detail": str(error)})
        return Response(
            {"id": event.pk, "unit_serial_number": event.unit.serial_number, "event_type": event.event_type, "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class StationOfflineEventSyncView(MESAPIView):
    required_permission = API_PERMISSIONS["sync_offline_events"]

    def post(self, request):
        self.enforce_permission()
        serializer = StationOfflineEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        auto_sync = data.pop("auto_sync")
        station_code = data.pop("station_code")
        station = AssemblyStation.objects.filter(code=station_code, is_active=True).first()
        if station is None:
            raise ValidationError({"detail": f"Estacion {station_code} no encontrada o inactiva."})

        offline_event, created = StationOfflineEvent.objects.get_or_create(
            external_id=data["external_id"],
            defaults={
                "station": station,
                "unit_serial_number": data["unit_serial_number"],
                "operator_username": data["operator_username"],
                "event_type": data["event_type"],
                "captured_at": data["captured_at"],
                "payload": data["payload"],
                "notes": data["notes"],
                "created_by": request.user,
                "updated_by": request.user,
            },
        )
        if auto_sync and offline_event.status != StationOfflineEventStatus.SYNCED:
            self.enforce_permission(API_PERMISSIONS["register_station_events"])
            try:
                offline_event.sync(request.user)
            except DjangoValidationError:
                pass

        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        if offline_event.status == StationOfflineEventStatus.REJECTED:
            response_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(
            {
                "external_id": offline_event.external_id,
                "status": offline_event.status,
                "detail": offline_event.result_detail,
                "station_event_id": offline_event.station_event_id,
                "created": created,
            },
            status=response_status,
        )


class InstalledComponentCreateAPIView(MESAPIView):
    required_permission = API_PERMISSIONS["install_components"]

    def post(self, request):
        self.enforce_permission()
        serializer = InstalledComponentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            component = install_component(actor=request.user, **serializer.validated_data)
        except (ValueError, DjangoValidationError) as error:
            raise ValidationError({"detail": _error_text(error)})
        return Response(
            {"id": component.pk, "unit_serial_number": component.unit.serial_number, "part_code": component.part_code},
            status=status.HTTP_201_CREATED,
        )


class ProductionMeasurementCreateAPIView(MESAPIView):
    required_permission = API_PERMISSIONS["record_measurements"]

    def post(self, request):
        self.enforce_permission()
        serializer = MeasurementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            measurement = record_measurement(actor=request.user, **serializer.validated_data)
        except (ValueError, DjangoValidationError) as error:
            raise ValidationError({"detail": _error_text(error)})
        return Response(
            {
                "id": measurement.pk,
                "unit_serial_number": measurement.unit.serial_number,
                "code": measurement.code,
                "result": measurement.result,
                "result_label": measurement.get_result_display(),
            },
            status=status.HTTP_201_CREATED,
        )


class QualityGateDecisionView(MESAPIView):
    required_permission = API_PERMISSIONS["review_quality"]

    def post(self, request, pk):
        self.enforce_permission()
        serializer = QualityDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            gate = review_quality_gate(actor=request.user, quality_gate_id=pk, **serializer.validated_data)
        except ValueError as error:
            raise ValidationError({"detail": str(error)})
        return Response({"id": gate.pk, "unit_serial_number": gate.unit.serial_number, "status": gate.status})


class EquipmentEventIngestView(MESAPIView):
    required_permission = API_PERMISSIONS["receive_equipment_events"]

    def post(self, request):
        self.enforce_permission()
        serializer = EquipmentEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inbound_event, created = process_equipment_event(actor=request.user, **serializer.validated_data)
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        if created and inbound_event.status == EquipmentInboundEventStatus.REJECTED:
            response_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(
            {
                "external_id": inbound_event.external_id,
                "status": inbound_event.status,
                "detail": inbound_event.result_detail,
                "station_event_id": inbound_event.station_event_id,
            },
            status=response_status,
        )


class EquipmentEventDetailView(MESAPIView):
    required_permission = API_PERMISSIONS["view_equipment_events"]

    def get(self, request, external_id):
        self.enforce_permission()
        inbound_event = EquipmentInboundEvent.objects.select_related("equipment", "station", "unit", "operator", "station_event").filter(
            external_id=external_id
        ).first()
        if inbound_event is None:
            raise NotFound("Evento de equipo no encontrado.")
        return Response(
            {
                "external_id": inbound_event.external_id,
                "status": inbound_event.status,
                "detail": inbound_event.result_detail,
                "equipment_code": inbound_event.equipment_code,
                "station_code": inbound_event.station.code if inbound_event.station_id else "",
                "unit_serial_number": inbound_event.unit_serial_number,
                "station_event_id": inbound_event.station_event_id,
                "processed_at": inbound_event.processed_at,
            }
        )
def _error_text(error):
    return "; ".join(error.messages) if hasattr(error, "messages") else str(error)
