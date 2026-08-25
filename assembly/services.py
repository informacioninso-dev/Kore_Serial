from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.models import ApprovalStatus, EquipmentIntegration

from .models import (
    AssemblyRoute,
    AssemblyRouteStep,
    EquipmentInboundEvent,
    EquipmentInboundEventStatus,
    QualityGate,
    QualityGateStatus,
    ReworkOrder,
    ReworkStatus,
    SerializedUnit,
    StationEventSource,
    StationEventType,
    UnitStationEvent,
    UnitStatus,
)


def route_step_for(unit, station):
    approved_route = AssemblyRoute.objects.filter(
        version=unit.version,
        approval_status=ApprovalStatus.APPROVED,
        is_active=True,
    ).order_by("-approved_at", "code").first()
    route = approved_route or AssemblyRoute.objects.filter(version=unit.version, is_active=True).order_by("code").first()
    if route is None:
        return None, None
    step = route.steps.filter(station=station, is_active=True).select_related("station", "route").order_by("sequence").first()
    return route, step


def latest_station_event(unit, station):
    return unit.station_events.filter(station=station).select_related("operator").order_by("-event_at", "-id").first()


def available_station_actions(last_event):
    if last_event is None:
        return [StationEventType.STARTED]
    if last_event.event_type in {StationEventType.STARTED, StationEventType.RESUMED}:
        return [StationEventType.PAUSED, StationEventType.COMPLETED, StationEventType.FAILED, StationEventType.REWORK_OUT]
    if last_event.event_type == StationEventType.PAUSED:
        return [StationEventType.RESUMED, StationEventType.REWORK_OUT]
    if last_event.event_type == StationEventType.FAILED:
        return [StationEventType.REWORK_OUT, StationEventType.STARTED]
    if last_event.event_type == StationEventType.REWORK_OUT:
        return [StationEventType.REWORK_IN]
    if last_event.event_type == StationEventType.REWORK_IN:
        return [StationEventType.STARTED]
    return []


def apply_station_event_effects(unit, station, step, event_type, user, defect_code="", notes=""):
    if event_type in {StationEventType.STARTED, StationEventType.PAUSED, StationEventType.RESUMED, StationEventType.REWORK_IN}:
        unit.status = UnitStatus.IN_PROCESS
    elif event_type == StationEventType.COMPLETED:
        if station.requires_quality_gate or step.requires_quality_gate:
            QualityGate.objects.get_or_create(
                unit=unit,
                station=station,
                route_step=step,
                defaults={
                    "status": QualityGateStatus.PENDING,
                    "is_blocking": True,
                    "notes": "Control generado desde estacion.",
                    "created_by": user,
                    "updated_by": user,
                },
            )
            unit.status = UnitStatus.QUALITY_HOLD
        elif not AssemblyRouteStep.objects.filter(route=step.route, is_active=True, sequence__gt=step.sequence).exists():
            unit.status = UnitStatus.COMPLETED
        else:
            unit.status = UnitStatus.IN_PROCESS
    elif event_type == StationEventType.FAILED:
        unit.status = UnitStatus.QUALITY_HOLD
    elif event_type == StationEventType.REWORK_OUT:
        unit.status = UnitStatus.REWORK
        code = defect_code or f"RW-{unit.serial_number}-{station.code}"
        ReworkOrder.objects.get_or_create(
            unit=unit,
            station_detected=station,
            route_step_detected=step,
            defect_code=code,
            defaults={
                "description": notes or f"Retrabajo abierto desde {station.code}.",
                "status": ReworkStatus.OPEN,
                "opened_by": user,
                "opened_at": timezone.now(),
                "created_by": user,
                "updated_by": user,
            },
        )
    unit.updated_by = user
    unit.save(update_fields=["status", "updated_by", "updated_at"])


def process_equipment_event(*, actor, external_id, equipment_code, station_code, unit_serial_number, operator_username, event_type, event_at, payload, notes=""):
    """Guarda un mensaje del recolector y crea su evento operativo una sola vez."""
    with transaction.atomic():
        inbound_event, created = EquipmentInboundEvent.objects.get_or_create(
            external_id=external_id,
            defaults={
                "equipment_code": equipment_code,
                "station_code": station_code,
                "unit_serial_number": unit_serial_number,
                "operator_username": operator_username,
                "event_type": event_type,
                "event_at": event_at or timezone.now(),
                "payload": payload,
                "created_by": actor,
                "updated_by": actor,
            },
        )
        if not created:
            return inbound_event, False

        try:
            equipment = EquipmentIntegration.objects.filter(code=equipment_code).first()
            if equipment is None:
                raise ValueError(f"Equipo {equipment_code} no encontrado.")
            if not equipment.can_be_used:
                raise ValueError(f"Equipo {equipment.code} no habilitado por estado, calibracion o mantenimiento.")

            stations = equipment.assembly_stations.filter(is_active=True)
            if station_code:
                stations = stations.filter(code=station_code)
            stations = list(stations)
            if not stations:
                raise ValueError(f"El equipo {equipment.code} no tiene una estacion activa asignada.")
            if len(stations) > 1:
                raise ValueError(f"El equipo {equipment.code} tiene mas de una estacion activa asignada.")
            station = stations[0]

            unit = SerializedUnit.objects.filter(serial_number=unit_serial_number).select_related("version").first()
            if unit is None:
                raise ValueError(f"Unidad {unit_serial_number} no encontrada.")
            operator = get_user_model().objects.filter(username=operator_username, is_active=True).first()
            if operator is None:
                raise ValueError(f"Operario {operator_username} no encontrado o inactivo.")
            if not operator.is_superuser:
                if station.authorized_operators.exists() and not station.authorized_operators.filter(pk=operator.pk).exists():
                    raise ValueError(f"{station.code}: el operario no esta autorizado para la estacion.")
                operator_issue = equipment.qualification_issue_for(operator)
                if operator_issue:
                    raise ValueError(operator_issue)

            route, step = route_step_for(unit, station)
            if route is None or step is None:
                raise ValueError("La unidad no tiene un paso activo para la estacion resuelta.")
            if event_type not in available_station_actions(latest_station_event(unit, station)):
                raise ValueError("El evento no corresponde al estado actual de la unidad en la estacion.")

            station_event = UnitStationEvent.objects.create(
                unit=unit,
                station=station,
                route_step=step,
                event_type=event_type,
                event_at=inbound_event.event_at,
                operator=operator,
                source=StationEventSource.EQUIPMENT,
                external_reference=external_id,
                notes=notes,
                metadata={"collector_payload": payload, "route": route.code, "equipment_code": equipment.code},
                created_by=actor,
                updated_by=actor,
            )
            apply_station_event_effects(unit, station, step, event_type, operator, notes=notes)
            inbound_event.equipment = equipment
            inbound_event.station = station
            inbound_event.unit = unit
            inbound_event.operator = operator
            inbound_event.station_event = station_event
            inbound_event.status = EquipmentInboundEventStatus.PROCESSED
            inbound_event.result_detail = "Evento procesado."
        except ValueError as error:
            inbound_event.status = EquipmentInboundEventStatus.REJECTED
            inbound_event.result_detail = str(error)

        inbound_event.processed_at = timezone.now()
        inbound_event.updated_by = actor
        inbound_event.save()
        return inbound_event, True
