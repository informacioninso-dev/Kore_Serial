from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.audit import log_operational_event
from core.db_locks import lock_series

from .models import (
    InboundReceiptStatus,
    InventoryBalance,
    InventoryMovement,
    InventoryMovementType,
    InventoryState,
    AssemblyKitStatus,
    KanbanSignal,
    KanbanSignalStatus,
    MaterialLot,
    MaterialSerial,
    MaterialTraceability,
    PickMission,
    PickMissionStatus,
    PickTask,
    PickTaskStatus,
    ReplenishmentRule,
    WmsLocationProfile,
)


def _decimal(value):
    quantity = Decimal(str(value))
    if quantity <= 0:
        raise ValidationError("La cantidad debe ser mayor a cero.")
    return quantity


def _lot_for(material, lot_number, actor):
    lot_number = (lot_number or "").strip()
    if material.traceability == MaterialTraceability.LOT and not lot_number:
        raise ValidationError("El material requiere numero de lote.")
    if not lot_number:
        return None
    lot, _created = MaterialLot.objects.get_or_create(
        material=material,
        number=lot_number,
        defaults={"created_by": actor, "updated_by": actor},
    )
    return lot


def _position(material, location, state, lot, serial, actor):
    lock_series("wms-position", material.pk, location.pk, state, lot.pk if lot else 0, serial.pk if serial else 0)
    position = (
        InventoryBalance.objects.select_for_update()
        .filter(material=material, location=location, state=state, lot=lot, serial=serial)
        .first()
    )
    if position is None:
        position = InventoryBalance(
            material=material,
            location=location,
            state=state,
            lot=lot,
            serial=serial,
            quantity=Decimal("0"),
            created_by=actor,
            updated_by=actor,
        )
    return position


def _increase(material, location, state, lot, serial, quantity, actor):
    profile = WmsLocationProfile.objects.filter(
        location=location,
        is_active=True,
        allows_mixed_materials=False,
    ).first()
    if profile and InventoryBalance.objects.filter(location=location).exclude(material=material).exists():
        raise ValidationError(f"La ubicacion {location.code} no permite mezclar materiales.")
    position = _position(material, location, state, lot, serial, actor)
    position.quantity += quantity
    position.updated_by = actor
    position.full_clean()
    position.save()
    return position


def _decrease(material, location, state, lot, serial, quantity, actor):
    position = _position(material, location, state, lot, serial, actor)
    if position.pk is None or position.quantity < quantity:
        raise ValidationError("No existe saldo disponible suficiente en la ubicacion y estado de origen.")
    position.quantity -= quantity
    if position.quantity == 0:
        position.delete()
        return None
    position.updated_by = actor
    position.full_clean()
    position.save(update_fields=["quantity", "updated_by", "updated_at"])
    return position


def _log_movement(movement, actor):
    log_operational_event(
        module="WMS",
        action="CREATE",
        actor=actor,
        obj=movement,
        document_type="Movimiento de inventario",
        document_code=str(movement.pk),
        related_obj=movement.destination_location or movement.source_location,
        related_code=(movement.destination_location or movement.source_location).code
        if (movement.destination_location_id or movement.source_location_id)
        else "",
        from_status=movement.source_state,
        to_status=movement.destination_state,
        reason=movement.reason,
        metadata={
            "movement_type": movement.movement_type,
            "material": movement.material.code,
            "quantity": str(movement.quantity),
            "lot": movement.lot.number if movement.lot_id else "",
            "serial": movement.serial.number if movement.serial_id else "",
            "external_reference": movement.external_reference,
        },
    )


def record_movement(
    *,
    actor,
    movement_type,
    material,
    quantity,
    source_location=None,
    destination_location=None,
    source_state="",
    destination_state="",
    lot=None,
    serial=None,
    receipt_line=None,
    external_reference="",
    reason="",
    moved_at=None,
):
    """Registra el libro inmutable y actualiza su proyeccion de saldo bajo bloqueo."""
    quantity = _decimal(quantity)
    source_state = source_state or ""
    destination_state = destination_state or ""
    if serial is not None and quantity != Decimal("1"):
        raise ValidationError("Una serie se mueve individualmente.")

    with transaction.atomic():
        if source_location is not None:
            if not source_state:
                raise ValidationError("Indica el estado de inventario de origen.")
            _decrease(material, source_location, source_state, lot, serial, quantity, actor)
        if destination_location is not None:
            if not destination_state:
                raise ValidationError("Indica el estado de inventario de destino.")
            _increase(material, destination_location, destination_state, lot, serial, quantity, actor)

        movement = InventoryMovement(
            movement_type=movement_type,
            material=material,
            quantity=quantity,
            source_location=source_location,
            destination_location=destination_location,
            source_state=source_state,
            destination_state=destination_state,
            lot=lot,
            serial=serial,
            receipt_line=receipt_line,
            external_reference=external_reference,
            reason=reason,
            moved_at=moved_at or timezone.now(),
            created_by=actor,
            updated_by=actor,
        )
        movement.full_clean()
        movement.save()
        _log_movement(movement, actor)
        return movement


def receive_receipt_line(*, actor, receipt_line, quantity, lot_number="", serial_numbers=None, reason=""):
    """Recibe una linea CKD y crea uno o varios movimientos de recepcion."""
    quantity = _decimal(quantity)
    serial_numbers = [value.strip() for value in (serial_numbers or []) if value and value.strip()]
    material = receipt_line.material
    if receipt_line.receipt.status == InboundReceiptStatus.CANCELLED:
        raise ValidationError("No se puede recibir una recepcion cancelada.")
    if receipt_line.expected_quantity and receipt_line.received_quantity + quantity > receipt_line.expected_quantity:
        raise ValidationError("La cantidad recibida supera la cantidad esperada de la linea.")
    if material.traceability == MaterialTraceability.SERIAL:
        if len(serial_numbers) != int(quantity) or quantity != quantity.to_integral_value():
            raise ValidationError("Indica una serie por cada unidad recibida.")
        if len(set(serial_numbers)) != len(serial_numbers):
            raise ValidationError("No repitas series dentro de la misma recepcion.")
    elif serial_numbers:
        raise ValidationError("Solo un material trazado por serie acepta numeros de serie.")

    with transaction.atomic():
        lot = _lot_for(material, lot_number or receipt_line.lot_number, actor)
        movements = []
        if material.traceability == MaterialTraceability.SERIAL:
            for number in serial_numbers:
                serial, created = MaterialSerial.objects.get_or_create(
                    material=material,
                    number=number,
                    defaults={"lot": lot, "created_by": actor, "updated_by": actor},
                )
                if not created:
                    raise ValidationError(f"La serie {number} ya existe para este material.")
                movements.append(
                    record_movement(
                        actor=actor,
                        movement_type=InventoryMovementType.RECEIPT,
                        material=material,
                        quantity=Decimal("1"),
                        destination_location=receipt_line.receipt.destination_location,
                        destination_state=InventoryState.QUARANTINE,
                        lot=lot,
                        serial=serial,
                        receipt_line=receipt_line,
                        external_reference=receipt_line.receipt.asn_reference,
                        reason=reason or f"Recepcion {receipt_line.receipt.code}",
                    )
                )
        else:
            movements.append(
                record_movement(
                    actor=actor,
                    movement_type=InventoryMovementType.RECEIPT,
                    material=material,
                    quantity=quantity,
                    destination_location=receipt_line.receipt.destination_location,
                    destination_state=InventoryState.QUARANTINE,
                    lot=lot,
                    receipt_line=receipt_line,
                    external_reference=receipt_line.receipt.asn_reference,
                    reason=reason or f"Recepcion {receipt_line.receipt.code}",
                )
            )
        receipt_line.received_quantity += quantity
        if lot_number:
            receipt_line.lot_number = lot_number
        receipt_line.updated_by = actor
        receipt_line.full_clean()
        receipt_line.save(update_fields=["received_quantity", "lot_number", "updated_by", "updated_at"])
        receipt = receipt_line.receipt
        receipt.status = InboundReceiptStatus.RECEIVED
        receipt.updated_by = actor
        receipt.save(update_fields=["status", "updated_by", "updated_at"])
        return movements


def transfer_inventory(*, actor, material, quantity, source_location, destination_location, state, lot=None, serial=None, reason=""):
    return record_movement(
        actor=actor,
        movement_type=InventoryMovementType.TRANSFER,
        material=material,
        quantity=quantity,
        source_location=source_location,
        destination_location=destination_location,
        source_state=state,
        destination_state=state,
        lot=lot,
        serial=serial,
        reason=reason,
    )


def change_inventory_state(*, actor, material, quantity, location, source_state, destination_state, lot=None, serial=None, reason=""):
    if source_state == destination_state:
        raise ValidationError("El estado de destino debe ser diferente al estado de origen.")
    return record_movement(
        actor=actor,
        movement_type=InventoryMovementType.STATUS_CHANGE,
        material=material,
        quantity=quantity,
        source_location=location,
        destination_location=location,
        source_state=source_state,
        destination_state=destination_state,
        lot=lot,
        serial=serial,
        reason=reason,
    )


def adjust_inventory(*, actor, material, quantity, location, state, direction, lot=None, serial=None, reason=""):
    if not reason.strip():
        raise ValidationError("El ajuste requiere un motivo.")
    if direction == "IN":
        return record_movement(
            actor=actor,
            movement_type=InventoryMovementType.ADJUSTMENT_IN,
            material=material,
            quantity=quantity,
            destination_location=location,
            destination_state=state,
            lot=lot,
            serial=serial,
            reason=reason,
        )
    if direction == "OUT":
        return record_movement(
            actor=actor,
            movement_type=InventoryMovementType.ADJUSTMENT_OUT,
            material=material,
            quantity=quantity,
            source_location=location,
            source_state=state,
            lot=lot,
            serial=serial,
            reason=reason,
        )
    raise ValidationError("Direccion de ajuste invalida.")


def _log_line_feeding_event(*, actor, obj, action, reason="", metadata=None):
    log_operational_event(
        module="WMS",
        action=action,
        actor=actor,
        obj=obj,
        document_type=obj._meta.verbose_name.title(),
        document_code=str(obj),
        reason=reason,
        metadata=metadata or {},
    )


def _next_code(prefix, model):
    lock_series("wms-line-feeding-code", prefix)
    last_id = model.objects.order_by("-id").values_list("id", flat=True).first() or 0
    return f"{prefix}-{last_id + 1:06d}"


def release_kit(*, actor, kit):
    if kit.status != AssemblyKitStatus.DRAFT:
        raise ValidationError("Solo un kit en borrador puede liberarse.")
    if not kit.lines.exists():
        raise ValidationError("Agrega al menos una linea antes de liberar el kit.")
    kit.status = AssemblyKitStatus.RELEASED
    kit.updated_by = actor
    kit.save(update_fields=["status", "updated_by", "updated_at"])
    _log_line_feeding_event(actor=actor, obj=kit, action="RELEASE", reason="Kit liberado para picking")
    return kit


def create_pick_mission(*, actor, source_location, destination_location, kit=None, code="", notes=""):
    if kit and kit.status not in {AssemblyKitStatus.RELEASED, AssemblyKitStatus.READY}:
        raise ValidationError("La mision solo puede crearse para un kit liberado.")
    with transaction.atomic():
        mission = PickMission(
            code=(code or _next_code("PICK", PickMission)).strip(),
            kit=kit,
            source_location=source_location,
            destination_location=destination_location,
            notes=notes,
            created_by=actor,
            updated_by=actor,
        )
        mission.full_clean()
        mission.save()
        _log_line_feeding_event(actor=actor, obj=mission, action="CREATE", reason="Mision de picking creada")
        return mission


def release_pick_mission(*, actor, mission):
    if mission.status != PickMissionStatus.DRAFT:
        raise ValidationError("Solo una mision en borrador puede liberarse.")
    if not mission.tasks.exists():
        raise ValidationError("Agrega al menos una tarea antes de liberar la mision.")
    mission.status = PickMissionStatus.RELEASED
    mission.updated_by = actor
    mission.save(update_fields=["status", "updated_by", "updated_at"])
    _log_line_feeding_event(actor=actor, obj=mission, action="RELEASE", reason="Mision liberada")
    return mission


def _sync_mission_status(*, actor, mission):
    statuses = set(mission.tasks.values_list("status", flat=True))
    if not statuses:
        return mission
    if statuses <= {PickTaskStatus.PICKED, PickTaskStatus.CANCELLED}:
        new_status = PickMissionStatus.COMPLETED
    elif PickTaskStatus.PICKED in statuses:
        new_status = PickMissionStatus.IN_PROGRESS
    else:
        new_status = mission.status
    if new_status != mission.status:
        mission.status = new_status
        mission.updated_by = actor
        mission.save(update_fields=["status", "updated_by", "updated_at"])
        _log_line_feeding_event(actor=actor, obj=mission, action="UPDATE", reason=f"Mision {mission.get_status_display().lower()}")
    return mission


def _sync_kit_status(*, actor, kit):
    if kit.status not in {AssemblyKitStatus.RELEASED, AssemblyKitStatus.READY}:
        return kit
    lines = list(kit.lines.all())
    if lines and all(line.remaining_quantity == 0 for line in lines):
        if kit.status != AssemblyKitStatus.READY:
            kit.status = AssemblyKitStatus.READY
            kit.updated_by = actor
            kit.save(update_fields=["status", "updated_by", "updated_at"])
            _log_line_feeding_event(actor=actor, obj=kit, action="UPDATE", reason="Kit completo y listo para entrega")
    return kit


def complete_pick_task(*, actor, task, reason=""):
    if task.status != PickTaskStatus.PENDING:
        raise ValidationError("Solo una tarea pendiente puede recogerse.")
    if task.mission.status not in {PickMissionStatus.RELEASED, PickMissionStatus.IN_PROGRESS}:
        raise ValidationError("La mision debe estar liberada para confirmar el picking.")
    if task.kit_line_id and task.quantity > task.kit_line.remaining_quantity:
        raise ValidationError("La cantidad de la tarea supera el saldo requerido de la linea de kit.")
    with transaction.atomic():
        movement = transfer_inventory(
            actor=actor,
            material=task.material,
            quantity=task.quantity,
            source_location=task.mission.source_location,
            destination_location=task.mission.destination_location,
            state=InventoryState.AVAILABLE,
            lot=task.lot,
            serial=task.serial,
            reason=reason or f"Picking {task.mission.code}",
        )
        task.status = PickTaskStatus.PICKED
        task.picked_at = timezone.now()
        task.updated_by = actor
        task.full_clean()
        task.save(update_fields=["status", "picked_at", "updated_by", "updated_at"])
        _log_line_feeding_event(
            actor=actor,
            obj=task,
            action="PICK",
            reason=reason or "Material trasladado para abastecimiento de linea",
            metadata={"movement_id": movement.pk, "mission": task.mission.code},
        )
        _sync_mission_status(actor=actor, mission=task.mission)
        if task.kit_line_id:
            _sync_kit_status(actor=actor, kit=task.kit_line.kit)
        return movement


def deliver_kit(*, actor, kit):
    if kit.status != AssemblyKitStatus.READY:
        raise ValidationError("El kit debe estar completo antes de entregarse a la estacion.")
    kit.status = AssemblyKitStatus.DELIVERED
    kit.updated_by = actor
    kit.save(update_fields=["status", "updated_by", "updated_at"])
    _log_line_feeding_event(actor=actor, obj=kit, action="DELIVER", reason="Kit entregado a linea")
    return kit


def available_quantity(*, material, location):
    return InventoryBalance.objects.filter(
        material=material,
        location=location,
        state=InventoryState.AVAILABLE,
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")


def create_kanban_signal(*, actor, rule, reason=""):
    if not rule.is_active:
        raise ValidationError("La regla de reposicion esta inactiva.")
    current_quantity = available_quantity(material=rule.material, location=rule.destination_location)
    if current_quantity >= rule.minimum_quantity:
        raise ValidationError("El saldo actual no esta por debajo del minimo de reposicion.")
    requested_quantity = rule.maximum_quantity - current_quantity
    with transaction.atomic():
        signal = KanbanSignal(
            code=_next_code("KAN", KanbanSignal),
            rule=rule,
            requested_quantity=requested_quantity,
            reason=reason or f"Saldo {current_quantity} bajo minimo {rule.minimum_quantity}",
            created_by=actor,
            updated_by=actor,
        )
        signal.full_clean()
        signal.save()
        _log_line_feeding_event(
            actor=actor,
            obj=signal,
            action="CREATE",
            reason=signal.reason,
            metadata={"available_quantity": str(current_quantity)},
        )
        return signal


def create_kanban_pick_mission(*, actor, signal):
    if signal.status != KanbanSignalStatus.OPEN:
        raise ValidationError("Solo una senal Kanban pendiente puede convertirse en mision.")
    rule = signal.rule
    with transaction.atomic():
        mission = create_pick_mission(
            actor=actor,
            source_location=rule.source_location,
            destination_location=rule.destination_location,
            notes=f"Reposicion Kanban {signal.code}",
        )
        if rule.material.traceability != MaterialTraceability.SERIAL:
            task = PickTask(
                mission=mission,
                material=rule.material,
                quantity=signal.requested_quantity,
                created_by=actor,
                updated_by=actor,
            )
            task.full_clean()
            task.save()
        signal.pick_mission = mission
        signal.status = KanbanSignalStatus.IN_PROGRESS
        signal.updated_by = actor
        signal.save(update_fields=["pick_mission", "status", "updated_by", "updated_at"])
        _log_line_feeding_event(actor=actor, obj=signal, action="UPDATE", reason="Mision Kanban creada", metadata={"mission": mission.code})
        return mission


def fulfill_kanban_signal(*, actor, signal):
    if signal.status != KanbanSignalStatus.IN_PROGRESS or not signal.pick_mission_id:
        raise ValidationError("La senal Kanban no tiene una mision en proceso.")
    if signal.pick_mission.status != PickMissionStatus.COMPLETED:
        raise ValidationError("Completa la mision de picking antes de atender la senal Kanban.")
    signal.status = KanbanSignalStatus.FULFILLED
    signal.updated_by = actor
    signal.save(update_fields=["status", "updated_by", "updated_at"])
    _log_line_feeding_event(actor=actor, obj=signal, action="FULFILL", reason="Reposicion Kanban atendida")
    return signal
