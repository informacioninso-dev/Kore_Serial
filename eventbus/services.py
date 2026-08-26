"""Bus de eventos e indicadores derivados.

Un hecho se publica una sola vez y se entrega a quien este suscrito. Los
indicadores no se calculan al vuelo sobre las tablas operativas: se
reconstruyen desde los eventos, que ya traen en su carga lo que hace falta
para contarlos.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from assembly.models import AssemblyLine, LineBalanceStatus, LineBalanceStudy, ProductionPlan

from .models import (
    DeliveryStatus,
    DomainEvent,
    EventDelivery,
    EventStatus,
    EventSubscription,
    EventType,
    IndicatorSnapshot,
    SubscriptionHandler,
)


# Turno por defecto cuando la linea no tiene un estudio de balanceo cargado.
DEFAULT_SHIFT_MINUTES = Decimal("480")

# Catalogo base. Se siembra con `seed_event_catalog` y puede crecer desde la GUI.
CORE_EVENT_TYPES = [
    ("produccion.unidad.completada", "Unidad completada en estacion", "PRODUCTION",
     ["unit", "station", "line"]),
    ("produccion.estacion.falla", "Falla registrada en estacion", "PRODUCTION",
     ["unit", "station", "line"]),
    ("produccion.paro.cerrado", "Paro de linea cerrado", "PRODUCTION",
     ["line", "minutes", "cause"]),
    ("calidad.retrabajo.abierto", "Retrabajo abierto", "QUALITY", ["unit", "line"]),
    ("calidad.control.resultado", "Control de calidad resuelto", "QUALITY",
     ["unit", "gate", "status"]),
    ("almacen.movimiento.registrado", "Movimiento de inventario", "WAREHOUSE",
     ["material", "quantity", "movement_type"]),
    ("conectividad.senal.normalizada", "Senal de equipo normalizada", "CONNECTIVITY",
     ["gateway", "device", "signal_key"]),
]


def _percent(numerator, denominator):
    if not denominator:
        return None
    value = (Decimal(numerator) / Decimal(denominator)) * Decimal("100")
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _minutes(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def seed_event_catalog(actor=None):
    """Deja el catalogo base disponible. Idempotente."""
    created = 0
    for code, name, domain, keys in CORE_EVENT_TYPES:
        _, was_created = EventType.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "domain": domain,
                "payload_keys": keys,
                "created_by": actor,
                "updated_by": actor,
            },
        )
        created += int(was_created)
    return created


def publish(
    *,
    event_code,
    idempotency_key,
    payload=None,
    actor=None,
    occurred_at=None,
    source_module="",
    aggregate_type="",
    aggregate_id="",
    line=None,
):
    """Publica un hecho y arma sus entregas pendientes.

    Devuelve (evento, creado). Si el tipo no esta en el catalogo o esta
    inactivo devuelve (None, False): el bus nunca debe tumbar la operacion
    que lo invoca.
    """
    event_type = EventType.objects.filter(code=event_code, is_active=True).first()
    if event_type is None:
        return None, False

    payload = payload or {}
    with transaction.atomic():
        existing = DomainEvent.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing, False

        missing = event_type.missing_keys(payload)
        event = DomainEvent.objects.create(
            event_type=event_type,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at or timezone.now(),
            source_module=source_module,
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id or ""),
            line=line,
            payload=payload,
            actor=actor,
            status=EventStatus.PUBLISHED,
            detail=f"Faltan claves del contrato: {', '.join(missing)}." if missing else "",
            created_by=actor,
            updated_by=actor,
        )
        _fan_out(event, actor)
    return event, True


def _fan_out(event, actor=None):
    """Crea una entrega por cada suscripcion que calce."""
    subscriptions = EventSubscription.objects.filter(is_active=True).select_related("event_type")
    deliveries = [
        EventDelivery(event=event, subscription=subscription, created_by=actor, updated_by=actor)
        for subscription in subscriptions
        if subscription.matches(event)
    ]
    if deliveries:
        EventDelivery.objects.bulk_create(deliveries, ignore_conflicts=True)
    return deliveries


def dispatch_pending(limit=200, actor=None):
    """Procesa entregas pendientes. Devuelve (entregadas, fallidas)."""
    delivered = failed = 0
    pending = (
        EventDelivery.objects.filter(status=DeliveryStatus.PENDING)
        .select_related("event__event_type", "subscription")
        .order_by("id")[:limit]
    )
    for delivery in pending:
        ok, error = _run_handler(delivery, actor)
        delivery.attempts += 1
        if ok:
            delivery.status = DeliveryStatus.DELIVERED
            delivery.delivered_at = timezone.now()
            delivery.last_error = ""
            delivered += 1
        else:
            delivery.status = DeliveryStatus.FAILED
            delivery.last_error = error
            failed += 1
        delivery.updated_by = actor
        delivery.save(
            update_fields=["status", "attempts", "delivered_at", "last_error", "updated_by", "updated_at"]
        )
    return delivered, failed


def retry_delivery(delivery, actor=None):
    """Reintenta una entrega fallida sin superar su tope de intentos."""
    if delivery.status == DeliveryStatus.DELIVERED:
        raise ValueError("La entrega ya fue procesada.")
    if delivery.attempts >= delivery.subscription.max_attempts:
        raise ValueError("La entrega agoto sus intentos; ajusta la suscripcion antes de insistir.")
    delivery.status = DeliveryStatus.PENDING
    delivery.updated_by = actor
    delivery.save(update_fields=["status", "updated_by", "updated_at"])
    return dispatch_pending(limit=1, actor=actor)


def _run_handler(delivery, actor=None):
    handler = delivery.subscription.handler
    try:
        if handler == SubscriptionHandler.INDICATORS:
            event = delivery.event
            rebuild_indicators(
                line=event.line,
                date=timezone.localtime(event.occurred_at).date(),
                actor=actor,
            )
        elif handler == SubscriptionHandler.LEDGER:
            pass  # El evento ya quedo persistido: la bitacora es el propio bus.
        elif handler == SubscriptionHandler.OUTBOUND:
            # Connect resuelve el destino. Import local para que el bus no
            # dependa del modulo de integraciones salvo en este punto.
            from connect.services import queue_from_event

            messages = queue_from_event(delivery.event, actor=actor)
            if not messages:
                return False, "Ningun contrato de salida escucha este evento."
    except Exception as error:  # noqa: BLE001 - el bus no debe propagar fallos de un consumidor
        return False, str(error)
    return True, ""


def planned_minutes_for(line, date):
    """Minutos disponibles del turno para esa linea.

    Sale del estudio de balanceo cuando existe; si no, del turno por defecto.
    No viene de un evento porque es configuracion, no un hecho ocurrido.
    """
    if line is None:
        return DEFAULT_SHIFT_MINUTES
    study = (
        LineBalanceStudy.objects.filter(
            line=line, status=LineBalanceStatus.APPROVED
        )
        .order_by("-generated_at", "-created_at")
        .first()
    )
    if study and study.shift_duration_seconds:
        return _minutes(Decimal(study.shift_duration_seconds) / Decimal("60"))
    return DEFAULT_SHIFT_MINUTES


def rebuild_indicators(*, line, date, actor=None):
    """Recalcula la foto diaria de una linea a partir de sus eventos.

    Formulas usadas, escritas aqui para que nadie las adivine:
      disponibilidad = (turno - paros) / turno
      rendimiento    = completadas / objetivo del plan
      calidad        = completadas / (completadas + fallas)
      OEE            = disponibilidad x rendimiento x calidad
      FPY            = completadas sin falla ni retrabajo / completadas
      MTBF           = minutos operando / cantidad de paros
      MTTR           = minutos de paro / cantidad de paros
    """
    events = DomainEvent.objects.filter(occurred_at__date=date)
    events = events.filter(line=line) if line is not None else events.filter(line__isnull=True)
    events = list(events.select_related("event_type"))

    completed = [e for e in events if e.event_type.code == "produccion.unidad.completada"]
    failures = [e for e in events if e.event_type.code == "produccion.estacion.falla"]
    downtimes = [e for e in events if e.event_type.code == "produccion.paro.cerrado"]
    reworks = [e for e in events if e.event_type.code == "calidad.retrabajo.abierto"]

    completed_units = {e.aggregate_id for e in completed if e.aggregate_id}
    failed_units = {e.aggregate_id for e in failures if e.aggregate_id}
    reworked_units = {e.aggregate_id for e in reworks if e.aggregate_id}
    first_pass = completed_units - failed_units - reworked_units

    downtime_minutes = sum(
        (Decimal(str(e.payload.get("minutes") or 0)) for e in downtimes), Decimal("0")
    )
    planned = planned_minutes_for(line, date)
    operating = max(planned - downtime_minutes, Decimal("0"))

    target = (
        ProductionPlan.objects.filter(planned_date=date, line=line).aggregate(
            total=Sum("target_quantity")
        )["total"]
        if line is not None
        else None
    )

    availability = _percent(operating, planned)
    # Unidades distintas, no eventos: una unidad que pasa por tres estaciones
    # emite tres completados y no por eso produjo tres vehiculos.
    performance = _percent(len(completed_units), target) if target else None
    quality = _percent(len(completed), len(completed) + len(failures)) if completed or failures else None

    oee = None
    if availability is not None and performance is not None and quality is not None:
        oee = ((availability / 100) * (performance / 100) * (quality / 100) * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    values = {
        "planned_minutes": planned,
        "downtime_minutes": _minutes(downtime_minutes),
        "completed_units": len(completed_units),
        "first_pass_units": len(first_pass),
        "failure_count": len(failures),
        "rework_count": len(reworks),
        "availability_percent": availability,
        "performance_percent": performance,
        "quality_percent": quality,
        "oee_percent": oee,
        "fpy_percent": _percent(len(first_pass), len(completed_units)) if completed_units else None,
        "mtbf_minutes": _minutes(operating / len(downtimes)) if downtimes else None,
        "mttr_minutes": _minutes(downtime_minutes / len(downtimes)) if downtimes else None,
        "event_count": len(events),
        "updated_by": actor,
    }

    snapshot, created = IndicatorSnapshot.objects.update_or_create(
        line=line, date=date, defaults=values
    )
    if created:
        snapshot.created_by = actor
        snapshot.save(update_fields=["created_by"])
    return snapshot


def rebuild_all_indicators(date, actor=None):
    """Recalcula todas las lineas activas de un dia."""
    snapshots = [
        rebuild_indicators(line=line, date=date, actor=actor)
        for line in AssemblyLine.objects.filter(is_active=True)
    ]
    snapshots.append(rebuild_indicators(line=None, date=date, actor=actor))
    return snapshots
