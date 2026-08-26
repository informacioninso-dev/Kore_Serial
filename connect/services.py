"""Connect: conversar con sistemas ajenos sin contaminar la logica del MES.

Nada sale de aqui por accidente. Un conector nace con transporte `LOG`, que
deja el mensaje armado y registrado pero no lo envia; recien cuando alguien
configura un endpoint y elige HTTP el mensaje viaja de verdad.
"""

import json
import urllib.error
import urllib.request

from django.db import transaction
from django.utils import timezone

from eventbus.models import DomainEvent

from .models import (
    Connector,
    ConnectorContract,
    ConnectorDirection,
    ConnectorTransport,
    InboundMessage,
    InboundStatus,
    MessageStatus,
    OutboundMessage,
    ReconciliationRun,
)


def contracts_for(event):
    """Contratos de salida vivos que escuchan este evento."""
    return ConnectorContract.objects.filter(
        is_active=True,
        direction=ConnectorDirection.OUTBOUND,
        event_type_id=event.event_type_id,
        connector__is_active=True,
    ).select_related("connector")


def queue_from_event(event, actor=None):
    """Arma un mensaje por cada contrato que escuche el evento.

    La clave de idempotencia junta contrato y evento: reprocesar el mismo
    hecho no genera un segundo envio al mismo sistema.
    """
    messages = []
    for contract in contracts_for(event):
        connector = contract.connector
        if not connector.sends:
            continue
        key = f"{contract.code}:{event.idempotency_key}"
        with transaction.atomic():
            existing = OutboundMessage.objects.filter(idempotency_key=key).first()
            if existing is not None:
                messages.append(existing)
                continue
            messages.append(
                OutboundMessage.objects.create(
                    connector=connector,
                    contract=contract,
                    event=event,
                    idempotency_key=key,
                    payload=contract.render(event.payload),
                    created_by=actor,
                    updated_by=actor,
                )
            )
    return messages


def _transport_send(connector, body):
    """Devuelve (ok, codigo, respuesta). Aisla el efecto de red en un solo lugar."""
    if connector.transport == ConnectorTransport.LOG:
        return True, None, "Registrado sin enviar (transporte LOG)."

    request = urllib.request.Request(
        connector.endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if connector.auth_header and connector.auth_token:
        request.add_header(connector.auth_header, connector.auth_token)
    try:
        with urllib.request.urlopen(request, timeout=connector.timeout_seconds) as response:
            return True, response.status, response.read().decode("utf-8", "ignore")[:2000]
    except urllib.error.HTTPError as error:
        return False, error.code, error.read().decode("utf-8", "ignore")[:2000]
    except Exception as error:  # noqa: BLE001 - cualquier fallo de red es un fallo de envio
        return False, None, str(error)


def send_message(message, actor=None):
    """Intenta enviar un mensaje y programa el siguiente intento si falla."""
    if message.status == MessageStatus.SENT:
        raise ValueError("El mensaje ya fue enviado.")
    if message.status == MessageStatus.DISCARDED:
        raise ValueError("El mensaje fue descartado.")

    ok, status_code, body = _transport_send(message.connector, message.payload)
    message.attempts += 1
    message.response_status = status_code
    message.response_body = body if ok else ""
    if ok:
        message.status = MessageStatus.SENT
        message.sent_at = timezone.now()
        message.next_attempt_at = None
        message.last_error = ""
    else:
        message.last_error = body
        if message.attempts >= message.connector.max_attempts:
            message.status = MessageStatus.DISCARDED
            message.next_attempt_at = None
        else:
            message.status = MessageStatus.FAILED
            message.next_attempt_at = timezone.now() + message.connector.backoff_for(message.attempts)
    message.updated_by = actor
    message.save()
    return message


def flush_outbound(limit=100, actor=None, connector=None):
    """Envia lo que esta en cola y los reintentos que ya cumplieron su espera."""
    queryset = OutboundMessage.objects.filter(
        status__in=[MessageStatus.QUEUED, MessageStatus.FAILED]
    ).select_related("connector", "contract")
    if connector is not None:
        queryset = queryset.filter(connector=connector)

    sent = failed = 0
    for message in queryset.order_by("id")[:limit]:
        if not message.is_due:
            continue
        send_message(message, actor=actor)
        if message.status == MessageStatus.SENT:
            sent += 1
        else:
            failed += 1
    return sent, failed


def receive_inbound(*, connector, external_id, payload, contract=None, actor=None):
    """Guarda un mensaje externo. Idempotente por identificador externo."""
    if not connector.receives:
        raise ValueError(f"El conector {connector.code} no acepta entrada.")

    with transaction.atomic():
        existing = InboundMessage.objects.filter(external_id=external_id).first()
        if existing is not None:
            return existing, False
        message = InboundMessage.objects.create(
            connector=connector,
            contract=contract,
            external_id=external_id,
            payload=payload or {},
            created_by=actor,
            updated_by=actor,
        )
    return message, True


def mark_inbound_processed(message, *, succeeded, detail="", actor=None):
    message.status = InboundStatus.PROCESSED if succeeded else InboundStatus.REJECTED
    message.result_detail = detail
    message.processed_at = timezone.now()
    message.updated_by = actor
    message.save(
        update_fields=["status", "result_detail", "processed_at", "updated_by", "updated_at"]
    )
    return message


def authenticate_connector(token):
    if not token:
        return None
    return Connector.objects.filter(inbound_token=token, is_active=True).first()


def reconcile(*, connector, date_from, date_to, actor=None):
    """Compara los hechos ocurridos contra lo que realmente salio.

    Un conector puede fallar en silencio: los eventos ocurren, los mensajes se
    encolan y nadie nota que ninguno llego. Esto lo hace visible.
    """
    contracts = list(
        connector.contracts.filter(is_active=True, direction=ConnectorDirection.OUTBOUND)
    )
    event_type_ids = [c.event_type_id for c in contracts if c.event_type_id]

    events = DomainEvent.objects.filter(
        event_type_id__in=event_type_ids,
        occurred_at__date__gte=date_from,
        occurred_at__date__lte=date_to,
    )
    expected_keys = set(events.values_list("idempotency_key", flat=True))

    messages = OutboundMessage.objects.filter(
        connector=connector, event__idempotency_key__in=expected_keys
    )
    sent_keys = set(
        messages.filter(status=MessageStatus.SENT).values_list("event__idempotency_key", flat=True)
    )

    run = ReconciliationRun.objects.create(
        connector=connector,
        date_from=date_from,
        date_to=date_to,
        expected_count=len(expected_keys),
        queued_count=messages.filter(status=MessageStatus.QUEUED).count(),
        sent_count=len(sent_keys),
        failed_count=messages.filter(
            status__in=[MessageStatus.FAILED, MessageStatus.DISCARDED]
        ).count(),
        missing_keys=sorted(expected_keys - sent_keys)[:200],
        created_by=actor,
        updated_by=actor,
    )
    return run


def requeue_missing(run, actor=None):
    """Vuelve a encolar los eventos que la reconciliacion encontro sin enviar."""
    events = DomainEvent.objects.filter(idempotency_key__in=run.missing_keys)
    created = 0
    for event in events:
        for message in queue_from_event(event, actor=actor):
            if message.status == MessageStatus.QUEUED and message.attempts == 0:
                created += 1
    return created
