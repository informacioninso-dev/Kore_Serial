"""Puente OT: aqui la senal tecnica se vuelve hecho de negocio.

Edge no reimplementa reglas del MES. Resuelve que significa una senal y
delega la escritura en los servicios de `assembly`, que siguen siendo los
duenos de la trazabilidad.
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from assembly.models import ProductiveParameterOrigin
from assembly.services import process_equipment_event, record_measurement

from .models import (
    EdgeCommand,
    EdgeCommandStatus,
    EdgeDevice,
    EdgeGateway,
    EdgeGatewayStatus,
    EdgeHealthCheck,
    EdgeRuleAction,
    EdgeSignal,
    EdgeSignalRule,
    EdgeSignalStatus,
)


DEVICE_ORIGIN = {
    "PLC": ProductiveParameterOrigin.PLC,
    "SENSOR": ProductiveParameterOrigin.SENSOR,
    "TORQUE_TOOL": ProductiveParameterOrigin.MACHINE,
    "SCANNER": ProductiveParameterOrigin.MACHINE,
}


def _to_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def authenticate_gateway(token):
    """Resuelve el gateway por su token. Devuelve None si no aplica."""
    if not token:
        return None
    return EdgeGateway.objects.filter(auth_token=token, is_active=True).first()


def register_heartbeat(
    *,
    gateway,
    actor=None,
    agent_version="",
    queue_depth=0,
    buffered_count=0,
    cpu_percent=None,
    memory_percent=None,
    latency_ms=None,
    status=EdgeGatewayStatus.ONLINE,
    detail="",
    reported_at=None,
):
    """Guarda el latido y refresca el estado del gateway."""
    reported_at = reported_at or timezone.now()
    with transaction.atomic():
        check = EdgeHealthCheck.objects.create(
            gateway=gateway,
            reported_at=reported_at,
            agent_version=agent_version,
            queue_depth=queue_depth,
            buffered_count=buffered_count,
            cpu_percent=_to_decimal(cpu_percent),
            memory_percent=_to_decimal(memory_percent),
            latency_ms=latency_ms,
            status=status,
            detail=detail,
            created_by=actor,
            updated_by=actor,
        )
        gateway.last_seen_at = reported_at
        gateway.buffered_signal_count = buffered_count
        if agent_version:
            gateway.agent_version = agent_version
        gateway.updated_by = actor
        gateway.save(
            update_fields=["last_seen_at", "buffered_signal_count", "agent_version", "updated_by", "updated_at"]
        )
    return check


def resolve_rule(device, signal_key):
    """La regla mas especifica gana: dispositivo, luego tipo, luego global."""
    candidates = EdgeSignalRule.objects.filter(signal_key=signal_key, is_active=True).order_by(
        "priority", "code"
    )
    for rule in candidates:
        if rule.matches(device, signal_key):
            return rule
    return None


def ingest_signal(
    *,
    gateway,
    device_code,
    external_id,
    signal_key,
    actor=None,
    raw_value="",
    numeric_value=None,
    unit_of_measure="",
    unit_serial_number="",
    operator_username="",
    captured_at=None,
    from_buffer=False,
    payload=None,
):
    """Recibe una senal cruda. Idempotente por external_id.

    Devuelve (signal, created). Un reenvio desde el buffer offline no vuelve a
    crear nada: esa es toda la gracia del external_id.
    """
    payload = payload or {}
    device = EdgeDevice.objects.filter(code=device_code, gateway=gateway).select_related("gateway").first()

    with transaction.atomic():
        existing = EdgeSignal.objects.filter(external_id=external_id).first()
        if existing is not None:
            return existing, False

        if device is None:
            raise ValueError(f"Dispositivo {device_code} no pertenece al gateway {gateway.code}.")
        if not device.is_active:
            raise ValueError(f"Dispositivo {device.code} inactivo.")

        signal = EdgeSignal.objects.create(
            gateway=gateway,
            device=device,
            external_id=external_id,
            signal_key=signal_key,
            raw_value=str(raw_value)[:240],
            numeric_value=_to_decimal(numeric_value if numeric_value is not None else raw_value),
            unit_of_measure=unit_of_measure,
            unit_serial_number=unit_serial_number,
            operator_username=operator_username,
            captured_at=captured_at or timezone.now(),
            from_buffer=from_buffer,
            payload=payload,
            created_by=actor,
            updated_by=actor,
        )
        device.last_seen_at = signal.captured_at
        device.updated_by = actor
        device.save(update_fields=["last_seen_at", "updated_by", "updated_at"])

    normalize_signal(signal, actor=actor)
    return signal, True


def normalize_signal(signal, actor=None):
    """Traduce la senal a un hecho de negocio segun su regla."""
    rule = resolve_rule(signal.device, signal.signal_key)
    signal.rule = rule
    signal.normalized_at = timezone.now()
    signal.updated_by = actor

    if rule is None:
        signal.status = EdgeSignalStatus.PENDING
        signal.result_detail = "Sin regla de normalizacion para esta senal."
        signal.save()
        return signal

    if rule.action == EdgeRuleAction.IGNORE:
        signal.status = EdgeSignalStatus.IGNORED
        signal.result_detail = f"Regla {rule.code}: senal ignorada por configuracion."
        signal.save()
        return signal

    value_issue = rule.value_issue(signal.numeric_value)
    if value_issue:
        signal.status = EdgeSignalStatus.REJECTED
        signal.result_detail = f"Regla {rule.code}: {value_issue}"
        signal.save()
        return signal

    try:
        if rule.action == EdgeRuleAction.STATION_EVENT:
            _apply_station_event(signal, rule, actor)
        else:
            _apply_measurement(signal, rule, actor)
    except ValueError as error:
        signal.status = EdgeSignalStatus.REJECTED
        signal.result_detail = str(error)

    signal.save()
    return signal


def _apply_station_event(signal, rule, actor):
    device = signal.device
    if not device.equipment_id:
        raise ValueError(
            f"Dispositivo {device.code} sin equipo configurado: no se puede crear el evento de estacion."
        )
    if not signal.unit_serial_number:
        raise ValueError("La senal no identifica la unidad.")
    if not signal.operator_username:
        raise ValueError("La senal no identifica al operario.")

    inbound_event, _ = process_equipment_event(
        actor=actor,
        external_id=f"edge:{signal.external_id}",
        equipment_code=device.equipment.code,
        station_code=device.station.code if device.station_id else "",
        unit_serial_number=signal.unit_serial_number,
        operator_username=signal.operator_username,
        event_type=rule.station_event_type,
        event_at=signal.captured_at,
        payload={
            "signal_key": signal.signal_key,
            "raw_value": signal.raw_value,
            "gateway": signal.gateway.code,
            "device": device.code,
            "from_buffer": signal.from_buffer,
            "original": signal.payload,
        },
        notes=f"Normalizado por Edge con la regla {rule.code}.",
    )
    signal.inbound_event = inbound_event
    if inbound_event.status == "REJECTED":
        signal.status = EdgeSignalStatus.REJECTED
        signal.result_detail = f"MES rechazo el evento: {inbound_event.result_detail}"
        return
    signal.status = EdgeSignalStatus.NORMALIZED
    signal.result_detail = f"Evento {rule.station_event_type} creado en el MES."


def _apply_measurement(signal, rule, actor):
    device = signal.device
    if not signal.unit_serial_number:
        raise ValueError("La senal no identifica la unidad.")

    measurement = record_measurement(
        actor=actor,
        unit_serial_number=signal.unit_serial_number,
        station_code=device.station.code if device.station_id else "",
        code=rule.measurement_code,
        name=rule.measurement_name or rule.name,
        value=signal.numeric_value,
        text_value="" if signal.numeric_value is not None else signal.raw_value,
        origin=DEVICE_ORIGIN.get(device.device_type, ProductiveParameterOrigin.API),
        measured_at=signal.captured_at,
        evidence_reference=signal.external_id,
        notes=f"Capturado por Edge ({device.code}) con la regla {rule.code}.",
    )
    signal.measurement = measurement
    signal.status = EdgeSignalStatus.NORMALIZED
    signal.result_detail = f"Medicion {rule.measurement_code} registrada."


def retry_signal(signal, actor=None):
    """Reintenta una senal pendiente o rechazada tras corregir la regla."""
    if signal.status == EdgeSignalStatus.NORMALIZED:
        raise ValueError("La senal ya fue normalizada.")
    return normalize_signal(signal, actor=actor)


def queue_command(*, gateway, command_type, actor=None, device=None, payload=None, expires_at=None):
    """Deja un comando en cola. El gateway lo recoge cuando puede."""
    if device is not None and device.gateway_id != gateway.pk:
        raise ValueError("El dispositivo no pertenece al gateway indicado.")
    command = EdgeCommand.objects.create(
        gateway=gateway,
        device=device,
        command_type=command_type,
        payload=payload or {},
        expires_at=expires_at,
        created_by=actor,
        updated_by=actor,
    )
    if command.expires_at is None:
        command.expires_at = command.default_expiry()
        command.save(update_fields=["expires_at"])
    return command


def claim_commands(gateway, actor=None, limit=20):
    """Entrega los comandos en cola y los marca como enviados."""
    expire_commands(gateway)
    with transaction.atomic():
        commands = list(
            EdgeCommand.objects.select_for_update()
            .filter(gateway=gateway, status=EdgeCommandStatus.QUEUED)
            .order_by("issued_at")[:limit]
        )
        now = timezone.now()
        for command in commands:
            command.status = EdgeCommandStatus.SENT
            command.sent_at = now
            command.updated_by = actor
            command.save(update_fields=["status", "sent_at", "updated_by", "updated_at"])
    return commands


def ack_command(*, command, succeeded, actor=None, response=None, detail=""):
    """Cierra el handshake con el resultado que informa el gateway."""
    if command.status in (EdgeCommandStatus.ACKED, EdgeCommandStatus.EXPIRED):
        raise ValueError("El comando ya fue cerrado.")
    command.status = EdgeCommandStatus.ACKED if succeeded else EdgeCommandStatus.FAILED
    command.acked_at = timezone.now()
    command.response = response or {}
    command.detail = detail
    command.updated_by = actor
    command.save(update_fields=["status", "acked_at", "response", "detail", "updated_by", "updated_at"])
    return command


def expire_commands(gateway=None):
    """Marca vencidos los comandos que nadie recogio a tiempo."""
    queryset = EdgeCommand.objects.filter(
        status__in=[EdgeCommandStatus.QUEUED, EdgeCommandStatus.SENT],
        expires_at__lt=timezone.now(),
    )
    if gateway is not None:
        queryset = queryset.filter(gateway=gateway)
    return queryset.update(status=EdgeCommandStatus.EXPIRED, detail="Expirado sin confirmacion.")


def gateway_health_summary():
    """Conteo por estado derivado, para el panel."""
    summary = {status.value: 0 for status in EdgeGatewayStatus}
    for gateway in EdgeGateway.objects.all():
        summary[gateway.health_status] += 1
    return summary
