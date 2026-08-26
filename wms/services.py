from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.audit import log_operational_event
from core.db_locks import lock_series

from .models import (
    InboundReceiptStatus,
    InventoryBalance,
    InventoryMovement,
    InventoryMovementType,
    InventoryState,
    MaterialLot,
    MaterialSerial,
    MaterialTraceability,
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
