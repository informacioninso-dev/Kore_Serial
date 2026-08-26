"""Emisores: convierten hechos operativos en eventos del bus.

Se enganchan a los modelos que ya existen en vez de pedirle a cada servicio
que publique. Asi ningun flujo del MES depende del bus para funcionar: si el
bus falla, la operacion sigue y el evento simplemente no se publica.

La clave de idempotencia sale siempre de la fila origen, de modo que
reprocesar o reintentar no duplica historia.
"""

from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import receiver

from assembly.models import (
    DowntimeStatus,
    ProductionDowntime,
    QualityGate,
    QualityGateStatus,
    ReworkOrder,
    StationEventType,
    UnitStationEvent,
)

from edge.models import EdgeSignal, EdgeSignalStatus
from wms.models import InventoryMovement

from .services import publish


def _safe_publish(**kwargs):
    """El bus nunca debe tumbar la operacion que lo dispara."""
    try:
        return publish(**kwargs)
    except Exception:  # noqa: BLE001
        return None, False


@receiver(post_save, sender=UnitStationEvent)
def emit_station_event(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.event_type == StationEventType.COMPLETED:
        code = "produccion.unidad.completada"
    elif instance.event_type == StationEventType.FAILED:
        code = "produccion.estacion.falla"
    else:
        return

    station = instance.station
    _safe_publish(
        event_code=code,
        idempotency_key=f"unitstationevent:{instance.pk}",
        occurred_at=instance.event_at,
        actor=instance.operator or instance.created_by,
        source_module="PRODUCTION",
        aggregate_type="unit",
        aggregate_id=instance.unit.serial_number,
        line=station.line if station.line_id else None,
        payload={
            "unit": instance.unit.serial_number,
            "station": station.code,
            "line": station.line.code if station.line_id else "",
            "event_type": instance.event_type,
            "source": instance.source,
        },
    )



@receiver(post_save, sender=ProductionDowntime)
def emit_downtime_closed(sender, instance, created, **kwargs):
    """Solo interesa el paro cerrado: antes no se sabe cuanto duro."""
    if instance.status != DowntimeStatus.CLOSED or not instance.ended_at:
        return
    minutes = Decimal(instance.duration_seconds or 0) / Decimal("60")
    _safe_publish(
        event_code="produccion.paro.cerrado",
        idempotency_key=f"downtime:{instance.pk}",
        occurred_at=instance.ended_at,
        actor=instance.updated_by,
        source_module="PRODUCTION",
        aggregate_type="line",
        aggregate_id=instance.line.code,
        line=instance.line,
        payload={
            "line": instance.line.code,
            "minutes": float(round(minutes, 2)),
            "cause": instance.cause_category,
            "station": instance.station.code if instance.station_id else "",
            "code": instance.code,
        },
    )


@receiver(post_save, sender=ReworkOrder)
def emit_rework_opened(sender, instance, created, **kwargs):
    if not created:
        return
    station = instance.station_detected
    _safe_publish(
        event_code="calidad.retrabajo.abierto",
        idempotency_key=f"rework:{instance.pk}",
        occurred_at=instance.opened_at,
        actor=instance.created_by,
        source_module="QUALITY",
        aggregate_type="unit",
        aggregate_id=instance.unit.serial_number,
        line=station.line if station and station.line_id else None,
        payload={
            "unit": instance.unit.serial_number,
            "line": station.line.code if station and station.line_id else "",
            "defect_code": instance.defect_code,
            "station": station.code if station else "",
        },
    )


@receiver(post_save, sender=QualityGate)
def emit_quality_result(sender, instance, created, **kwargs):
    """Se publica cuando el control deja de estar pendiente."""
    if instance.status == QualityGateStatus.PENDING:
        return
    station = instance.station
    _safe_publish(
        event_code="calidad.control.resultado",
        idempotency_key=f"qualitygate:{instance.pk}:{instance.status}",
        actor=instance.updated_by,
        source_module="QUALITY",
        aggregate_type="unit",
        aggregate_id=instance.unit.serial_number,
        line=station.line if station and station.line_id else None,
        payload={
            "unit": instance.unit.serial_number,
            "gate": str(instance.pk),
            "status": instance.status,
            "defect_code": instance.defect_code,
        },
    )


@receiver(post_save, sender=InventoryMovement)
def emit_inventory_movement(sender, instance, created, **kwargs):
    if not created:
        return
    _safe_publish(
        event_code="almacen.movimiento.registrado",
        idempotency_key=f"inventorymovement:{instance.pk}",
        occurred_at=instance.moved_at,
        actor=instance.created_by,
        source_module="WAREHOUSE",
        aggregate_type="material",
        aggregate_id=instance.material.code,
        payload={
            "material": instance.material.code,
            "quantity": float(instance.quantity),
            "movement_type": instance.movement_type,
            "source": instance.source_location.code if instance.source_location_id else "",
            "destination": instance.destination_location.code if instance.destination_location_id else "",
        },
    )


@receiver(post_save, sender=EdgeSignal)
def emit_normalized_signal(sender, instance, created, **kwargs):
    """Solo la senal ya interpretada es un hecho de negocio."""
    if instance.status != EdgeSignalStatus.NORMALIZED:
        return
    _safe_publish(
        event_code="conectividad.senal.normalizada",
        idempotency_key=f"edgesignal:{instance.pk}",
        occurred_at=instance.captured_at,
        actor=instance.updated_by,
        source_module="CONNECTIVITY",
        aggregate_type="device",
        aggregate_id=instance.device.code,
        payload={
            "gateway": instance.gateway.code,
            "device": instance.device.code,
            "signal_key": instance.signal_key,
            "unit": instance.unit_serial_number,
            "from_buffer": instance.from_buffer,
        },
    )
