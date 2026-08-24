from django.db.models.signals import post_save
from django.dispatch import receiver

from core.audit import log_operational_event

from .models import (
    InstalledComponent,
    ProductionQueueItem,
    QualityGate,
    ReleaseApproval,
    ReworkOrder,
    SerializedUnit,
    UnitStationEvent,
)


@receiver(post_save, sender=SerializedUnit)
def log_serialized_unit_creation(sender, instance, created, **kwargs):
    if created:
        log_operational_event(
            module="PRODUCTION",
            action="CREATE",
            actor=instance.created_by,
            obj=instance,
            document_type="Unidad serializada",
            document_code=instance.serial_number,
            to_status=instance.status,
        )


@receiver(post_save, sender=UnitStationEvent)
def log_unit_station_event(sender, instance, created, **kwargs):
    if created:
        log_operational_event(
            module="PRODUCTION",
            action="STATUS_CHANGE",
            actor=instance.operator or instance.created_by,
            obj=instance.unit,
            document_type="Evento de estacion",
            document_code=instance.unit.serial_number,
            related_obj=instance.station,
            related_code=instance.station.code,
            to_status=instance.event_type,
            metadata={
                "station": instance.station.code,
                "route_step": instance.route_step_id,
                "source": instance.source,
                "external_reference": instance.external_reference,
            },
        )


@receiver(post_save, sender=InstalledComponent)
def log_installed_component(sender, instance, created, **kwargs):
    if created:
        log_operational_event(
            module="PRODUCTION",
            action="CREATE",
            actor=instance.installed_by or instance.created_by,
            obj=instance.unit,
            document_type="Componente instalado",
            document_code=instance.unit.serial_number,
            related_obj=instance.station,
            related_code=instance.station.code if instance.station_id else "",
            metadata={
                "part_code": instance.part_code,
                "serial_number": instance.serial_number,
                "lot_number": instance.lot_number,
                "quantity": instance.quantity,
                "is_critical": instance.is_critical,
            },
        )


@receiver(post_save, sender=ProductionQueueItem)
def log_production_queue_item(sender, instance, created, **kwargs):
    if created:
        log_operational_event(
            module="PRODUCTION",
            action="CREATE",
            actor=instance.created_by,
            obj=instance,
            document_type="Secuencia de linea",
            document_code=instance.unit.serial_number,
            related_obj=instance.line,
            related_code=instance.line.code,
            to_status=instance.status,
            metadata={
                "sequence": instance.sequence,
                "production_plan": instance.production_plan.code,
                "route": instance.route.code,
                "priority": instance.priority,
            },
        )


@receiver(post_save, sender=QualityGate)
def log_quality_gate(sender, instance, created, **kwargs):
    if created:
        log_operational_event(
            module="QUALITY",
            action="STATUS_CHANGE",
            actor=instance.inspected_by or instance.created_by,
            obj=instance.unit,
            document_type="Control de calidad",
            document_code=instance.unit.serial_number,
            related_obj=instance.station,
            related_code=instance.station.code if instance.station_id else "",
            to_status=instance.status,
            metadata={
                "is_blocking": instance.is_blocking,
                "route_step": instance.route_step_id,
                "evidence_reference": instance.evidence_reference,
            },
        )


@receiver(post_save, sender=ReworkOrder)
def log_rework_order(sender, instance, created, **kwargs):
    if created:
        log_operational_event(
            module="PRODUCTION",
            action="EXCEPTION",
            actor=instance.opened_by or instance.created_by,
            obj=instance.unit,
            document_type="Retrabajo",
            document_code=instance.unit.serial_number,
            related_obj=instance.station_detected,
            related_code=instance.station_detected.code if instance.station_detected_id else "",
            to_status=instance.status,
            metadata={
                "defect_code": instance.defect_code,
                "route_step": instance.route_step_detected_id,
            },
        )


@receiver(post_save, sender=ReleaseApproval)
def log_release_approval(sender, instance, created, **kwargs):
    if created:
        log_operational_event(
            module="QUALITY",
            action="RELEASE",
            actor=instance.decided_by or instance.created_by,
            obj=instance.unit,
            document_type="Liberacion de unidad",
            document_code=instance.unit.serial_number,
            to_status=instance.decision,
            metadata={
                "evidence_reference": instance.evidence_reference,
            },
        )
