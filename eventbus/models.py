from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from assembly.models import AssemblyLine
from core.models import AuditModel


class EventDomain(models.TextChoices):
    PRODUCTION = "PRODUCTION", "Produccion"
    WAREHOUSE = "WAREHOUSE", "Almacen"
    CONNECTIVITY = "CONNECTIVITY", "Conectividad"
    QUALITY = "QUALITY", "Calidad"
    SYSTEM = "SYSTEM", "Sistema"


class EventStatus(models.TextChoices):
    PUBLISHED = "PUBLISHED", "Publicado"
    DISCARDED = "DISCARDED", "Descartado"


class DeliveryStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    DELIVERED = "DELIVERED", "Entregado"
    FAILED = "FAILED", "Fallido"
    SKIPPED = "SKIPPED", "Omitido"


class SubscriptionHandler(models.TextChoices):
    INDICATORS = "INDICATORS", "Recalcular indicadores"
    LEDGER = "LEDGER", "Registrar en bitacora"
    OUTBOUND = "OUTBOUND", "Publicar hacia afuera"


class EventType(AuditModel):
    """Catalogo formal: si un evento no esta aqui, no se publica.

    Tener el contrato en tabla y no en codigo permite que planta agregue
    eventos sin desplegar, y que se sepa exactamente que emite el sistema.
    """

    code = models.CharField(
        "Codigo",
        max_length=80,
        unique=True,
        help_text="Identificador estable del evento (ej: produccion.unidad.completada).",
    )
    name = models.CharField("Nombre", max_length=120)
    domain = models.CharField(
        "Dominio", max_length=20, choices=EventDomain.choices, default=EventDomain.PRODUCTION
    )
    description = models.TextField("Descripcion", blank=True)
    payload_keys = models.JSONField(
        "Claves esperadas",
        default=list,
        blank=True,
        help_text="Lista de claves que el consumidor puede dar por seguras.",
    )
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        ordering = ["domain", "code"]
        verbose_name = "Tipo de evento"
        verbose_name_plural = "Tipos de evento"

    def __str__(self):
        return f"{self.code} - {self.name}"

    def missing_keys(self, payload):
        """Claves del contrato que el emisor no envio."""
        return [key for key in self.payload_keys or [] if key not in (payload or {})]


class DomainEvent(AuditModel):
    """Hecho ocurrido en el sistema, publicado una sola vez.

    La clave de idempotencia es lo que permite reintentar emisores sin
    duplicar historia: dos publicaciones del mismo hecho son el mismo evento.
    """

    event_type = models.ForeignKey(
        EventType, on_delete=models.PROTECT, related_name="events", verbose_name="Tipo"
    )
    idempotency_key = models.CharField(
        "Clave de idempotencia",
        max_length=160,
        unique=True,
        help_text="Derivada del hecho origen (ej: unitstationevent:1234).",
    )
    occurred_at = models.DateTimeField("Ocurrido", default=timezone.now, db_index=True)
    published_at = models.DateTimeField("Publicado", auto_now_add=True)
    source_module = models.CharField("Modulo origen", max_length=40, blank=True)
    aggregate_type = models.CharField(
        "Tipo de agregado",
        max_length=40,
        blank=True,
        help_text="Sobre que entidad ocurre el hecho (unidad, material, gateway).",
    )
    aggregate_id = models.CharField("Identificador del agregado", max_length=120, blank=True)
    line = models.ForeignKey(
        AssemblyLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="domain_events",
        verbose_name="Linea",
    )
    payload = models.JSONField("Carga", default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_events",
        verbose_name="Actor",
    )
    status = models.CharField(
        "Estado", max_length=20, choices=EventStatus.choices, default=EventStatus.PUBLISHED
    )
    detail = models.TextField("Detalle", blank=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        verbose_name = "Evento"
        verbose_name_plural = "Eventos"
        indexes = [
            models.Index(fields=["event_type", "occurred_at"], name="event_type_time_idx"),
            models.Index(fields=["aggregate_type", "aggregate_id"], name="event_aggregate_idx"),
        ]

    def __str__(self):
        return f"{self.event_type_id}:{self.idempotency_key}"

    @property
    def pending_deliveries(self):
        return self.deliveries.filter(status=DeliveryStatus.PENDING).count()


class EventSubscription(AuditModel):
    """Quien quiere enterarse de que. Sin suscripcion no hay entrega."""

    code = models.CharField("Codigo", max_length=60, unique=True)
    name = models.CharField("Nombre", max_length=120)
    event_type = models.ForeignKey(
        EventType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subscriptions",
        verbose_name="Tipo de evento",
        help_text="Vacio escucha todos los eventos del dominio elegido.",
    )
    domain = models.CharField(
        "Dominio",
        max_length=20,
        choices=EventDomain.choices,
        blank=True,
        help_text="Filtro usado cuando la suscripcion no apunta a un tipo puntual.",
    )
    handler = models.CharField(
        "Manejador",
        max_length=20,
        choices=SubscriptionHandler.choices,
        default=SubscriptionHandler.LEDGER,
    )
    max_attempts = models.PositiveSmallIntegerField("Intentos maximos", default=3)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Suscripcion"
        verbose_name_plural = "Suscripciones"

    def __str__(self):
        return f"{self.code} - {self.name}"

    def clean(self):
        if not self.event_type_id and not self.domain:
            raise ValidationError(
                {"domain": "Indica un tipo de evento o un dominio; si no, la suscripcion no filtra nada."}
            )

    def matches(self, event):
        if not self.is_active:
            return False
        if self.event_type_id:
            return self.event_type_id == event.event_type_id
        return self.domain == event.event_type.domain


class EventDelivery(AuditModel):
    """Intento de entrega a un suscriptor. Uno por evento y suscripcion."""

    event = models.ForeignKey(
        DomainEvent, on_delete=models.CASCADE, related_name="deliveries", verbose_name="Evento"
    )
    subscription = models.ForeignKey(
        EventSubscription,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name="Suscripcion",
    )
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField("Intentos", default=0)
    last_error = models.TextField("Ultimo error", blank=True)
    delivered_at = models.DateTimeField("Entregado", null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Entrega"
        verbose_name_plural = "Entregas"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "subscription"], name="eventbus_delivery_once"
            )
        ]
        indexes = [
            models.Index(fields=["status", "id"], name="eventbus_delivery_status_idx"),
        ]

    def __str__(self):
        return f"{self.event_id} -> {self.subscription_id}"

    @property
    def can_retry(self):
        return self.status == DeliveryStatus.FAILED and self.attempts < self.subscription.max_attempts


class IndicatorSnapshot(AuditModel):
    """Foto diaria por linea, reconstruible desde los eventos.

    Se guarda calculada y no al vuelo porque OEE mira hacia atras: sirve para
    comparar dias, y recalcularlo entero en cada pantalla no escala.
    """

    line = models.ForeignKey(
        AssemblyLine,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="indicator_snapshots",
        verbose_name="Linea",
    )
    date = models.DateField("Fecha", db_index=True)
    planned_minutes = models.DecimalField(
        "Minutos planificados", max_digits=10, decimal_places=2, default=0
    )
    downtime_minutes = models.DecimalField(
        "Minutos de paro", max_digits=10, decimal_places=2, default=0
    )
    completed_units = models.PositiveIntegerField("Unidades completadas", default=0)
    first_pass_units = models.PositiveIntegerField("Unidades sin falla", default=0)
    failure_count = models.PositiveIntegerField("Fallas", default=0)
    rework_count = models.PositiveIntegerField("Retrabajos", default=0)
    availability_percent = models.DecimalField(
        "Disponibilidad %", max_digits=6, decimal_places=2, null=True, blank=True
    )
    performance_percent = models.DecimalField(
        "Rendimiento %", max_digits=6, decimal_places=2, null=True, blank=True
    )
    quality_percent = models.DecimalField(
        "Calidad %", max_digits=6, decimal_places=2, null=True, blank=True
    )
    oee_percent = models.DecimalField(
        "OEE %", max_digits=6, decimal_places=2, null=True, blank=True
    )
    fpy_percent = models.DecimalField(
        "FPY %", max_digits=6, decimal_places=2, null=True, blank=True
    )
    mtbf_minutes = models.DecimalField(
        "MTBF (min)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    mttr_minutes = models.DecimalField(
        "MTTR (min)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    event_count = models.PositiveIntegerField("Eventos considerados", default=0)
    computed_at = models.DateTimeField("Calculado", auto_now=True)

    class Meta:
        ordering = ["-date", "line__code"]
        verbose_name = "Indicador diario"
        verbose_name_plural = "Indicadores diarios"
        constraints = [
            models.UniqueConstraint(fields=["line", "date"], name="eventbus_snapshot_unique")
        ]

    def __str__(self):
        return f"{self.line_id or 'planta'} {self.date}"

    @property
    def line_label(self):
        return self.line.code if self.line_id else "Toda la planta"
