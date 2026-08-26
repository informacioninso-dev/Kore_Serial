from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import AuditModel
from eventbus.models import DomainEvent, EventType


class ConnectorDirection(models.TextChoices):
    OUTBOUND = "OUTBOUND", "Salida"
    INBOUND = "INBOUND", "Entrada"
    BIDIRECTIONAL = "BIDIRECTIONAL", "Entrada y salida"


class ConnectorSystem(models.TextChoices):
    ERP = "ERP", "ERP"
    BI = "BI", "BI / analitica"
    API = "API", "API externa"
    B22 = "B22", "B22"
    OTHER = "OTHER", "Otro"


class ConnectorTransport(models.TextChoices):
    LOG = "LOG", "Solo registrar"
    HTTP = "HTTP", "HTTP POST"


class MessageStatus(models.TextChoices):
    QUEUED = "QUEUED", "En cola"
    SENT = "SENT", "Enviado"
    FAILED = "FAILED", "Fallido"
    DISCARDED = "DISCARDED", "Descartado"


class InboundStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Recibido"
    PROCESSED = "PROCESSED", "Procesado"
    REJECTED = "REJECTED", "Rechazado"


class Connector(AuditModel):
    """Sistema externo con el que Kore Line conversa.

    El transporte nace en `LOG` a proposito: un conector recien creado no debe
    empezar a golpear un sistema ajeno solo porque alguien lo guardo.
    """

    code = models.CharField("Codigo", max_length=40, unique=True)
    name = models.CharField("Nombre", max_length=120)
    system = models.CharField(
        "Sistema", max_length=20, choices=ConnectorSystem.choices, default=ConnectorSystem.ERP
    )
    direction = models.CharField(
        "Direccion",
        max_length=20,
        choices=ConnectorDirection.choices,
        default=ConnectorDirection.OUTBOUND,
    )
    transport = models.CharField(
        "Transporte",
        max_length=10,
        choices=ConnectorTransport.choices,
        default=ConnectorTransport.LOG,
        help_text="LOG deja el mensaje registrado sin salir; HTTP lo envia de verdad.",
    )
    endpoint = models.URLField("Endpoint", blank=True)
    auth_header = models.CharField(
        "Cabecera de autenticacion",
        max_length=60,
        blank=True,
        help_text="Nombre de la cabecera (ej: Authorization).",
    )
    auth_token = models.CharField("Token", max_length=200, blank=True)
    inbound_token = models.CharField(
        "Token de entrada",
        max_length=64,
        blank=True,
        help_text="Credencial que el sistema externo usa para empujar datos.",
    )
    timeout_seconds = models.PositiveSmallIntegerField("Timeout (s)", default=15)
    max_attempts = models.PositiveSmallIntegerField("Intentos maximos", default=5)
    retry_backoff_seconds = models.PositiveIntegerField(
        "Espera entre intentos (s)",
        default=60,
        help_text="Se multiplica por el numero de intento.",
    )
    is_active = models.BooleanField("Activo", default=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Conector"
        verbose_name_plural = "Conectores"

    def __str__(self):
        return f"{self.code} - {self.name}"

    def clean(self):
        if self.transport == ConnectorTransport.HTTP and not self.endpoint:
            raise ValidationError({"endpoint": "El transporte HTTP necesita un endpoint."})

    @property
    def sends(self):
        return self.direction in (ConnectorDirection.OUTBOUND, ConnectorDirection.BIDIRECTIONAL)

    @property
    def receives(self):
        return self.direction in (ConnectorDirection.INBOUND, ConnectorDirection.BIDIRECTIONAL)

    def backoff_for(self, attempt):
        return timedelta(seconds=self.retry_backoff_seconds * max(attempt, 1))


class ConnectorContract(AuditModel):
    """Que se manda y con que nombres. El mapeo vive en datos, no en codigo."""

    connector = models.ForeignKey(
        Connector, on_delete=models.CASCADE, related_name="contracts", verbose_name="Conector"
    )
    code = models.CharField("Codigo", max_length=40, unique=True)
    name = models.CharField("Nombre", max_length=120)
    direction = models.CharField(
        "Direccion",
        max_length=20,
        choices=[
            (ConnectorDirection.OUTBOUND, "Salida"),
            (ConnectorDirection.INBOUND, "Entrada"),
        ],
        default=ConnectorDirection.OUTBOUND,
    )
    event_type = models.ForeignKey(
        EventType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="connector_contracts",
        verbose_name="Tipo de evento",
        help_text="Que evento del bus dispara este envio.",
    )
    field_map = models.JSONField(
        "Mapeo de campos",
        default=dict,
        blank=True,
        help_text='Destino: origen. Ej: {"orderNo": "unit", "workCenter": "station"}',
    )
    static_fields = models.JSONField(
        "Campos fijos",
        default=dict,
        blank=True,
        help_text="Valores constantes que el receptor exige.",
    )
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        ordering = ["connector__code", "code"]
        verbose_name = "Contrato"
        verbose_name_plural = "Contratos"

    def __str__(self):
        return f"{self.code} - {self.name}"

    def clean(self):
        if self.direction == ConnectorDirection.OUTBOUND and not self.event_type_id:
            raise ValidationError(
                {"event_type": "Un contrato de salida necesita saber que evento lo dispara."}
            )

    def render(self, payload):
        """Traduce la carga interna al vocabulario del sistema externo."""
        body = dict(self.static_fields or {})
        mapping = self.field_map or {}
        if not mapping:
            body.update(payload or {})
            return body
        for target, source in mapping.items():
            body[target] = (payload or {}).get(source)
        return body


class OutboundMessage(AuditModel):
    """Mensaje hacia afuera, con su historia de intentos."""

    connector = models.ForeignKey(
        Connector, on_delete=models.PROTECT, related_name="outbound", verbose_name="Conector"
    )
    contract = models.ForeignKey(
        ConnectorContract,
        on_delete=models.PROTECT,
        related_name="outbound",
        verbose_name="Contrato",
    )
    event = models.ForeignKey(
        DomainEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="outbound_messages",
        verbose_name="Evento origen",
    )
    idempotency_key = models.CharField("Clave de idempotencia", max_length=180, unique=True)
    payload = models.JSONField("Cuerpo enviado", default=dict, blank=True)
    status = models.CharField(
        "Estado", max_length=20, choices=MessageStatus.choices, default=MessageStatus.QUEUED, db_index=True
    )
    attempts = models.PositiveSmallIntegerField("Intentos", default=0)
    next_attempt_at = models.DateTimeField("Proximo intento", null=True, blank=True, db_index=True)
    sent_at = models.DateTimeField("Enviado", null=True, blank=True)
    response_status = models.PositiveSmallIntegerField("Codigo de respuesta", null=True, blank=True)
    response_body = models.TextField("Respuesta", blank=True)
    last_error = models.TextField("Ultimo error", blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Mensaje de salida"
        verbose_name_plural = "Mensajes de salida"
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="connect_out_status_idx"),
        ]

    def __str__(self):
        return f"{self.connector_id}:{self.idempotency_key}"

    @property
    def exhausted(self):
        return self.attempts >= self.connector.max_attempts

    @property
    def is_due(self):
        return self.next_attempt_at is None or self.next_attempt_at <= timezone.now()


class InboundMessage(AuditModel):
    """Mensaje que llega de afuera. Se guarda antes de interpretarlo."""

    connector = models.ForeignKey(
        Connector, on_delete=models.PROTECT, related_name="inbound", verbose_name="Conector"
    )
    contract = models.ForeignKey(
        ConnectorContract,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inbound",
        verbose_name="Contrato",
    )
    external_id = models.CharField("Identificador externo", max_length=180, unique=True)
    payload = models.JSONField("Carga recibida", default=dict, blank=True)
    received_at = models.DateTimeField("Recibido", auto_now_add=True)
    status = models.CharField(
        "Estado", max_length=20, choices=InboundStatus.choices, default=InboundStatus.RECEIVED, db_index=True
    )
    result_detail = models.TextField("Detalle", blank=True)
    processed_at = models.DateTimeField("Procesado", null=True, blank=True)

    class Meta:
        ordering = ["-received_at", "-id"]
        verbose_name = "Mensaje de entrada"
        verbose_name_plural = "Mensajes de entrada"

    def __str__(self):
        return f"{self.connector_id}:{self.external_id}"


class ReconciliationRun(AuditModel):
    """Comparacion entre lo que ocurrio adentro y lo que salio.

    Sin esto un conector puede estar fallando en silencio: los eventos ocurren,
    los mensajes se encolan y nadie nota que ninguno llego.
    """

    connector = models.ForeignKey(
        Connector, on_delete=models.CASCADE, related_name="reconciliations", verbose_name="Conector"
    )
    date_from = models.DateField("Desde")
    date_to = models.DateField("Hasta")
    expected_count = models.PositiveIntegerField("Eventos esperados", default=0)
    queued_count = models.PositiveIntegerField("Mensajes encolados", default=0)
    sent_count = models.PositiveIntegerField("Mensajes enviados", default=0)
    failed_count = models.PositiveIntegerField("Mensajes fallidos", default=0)
    missing_keys = models.JSONField("Eventos sin mensaje", default=list, blank=True)
    ran_at = models.DateTimeField("Ejecutado", auto_now_add=True)

    class Meta:
        ordering = ["-ran_at", "-id"]
        verbose_name = "Reconciliacion"
        verbose_name_plural = "Reconciliaciones"

    def __str__(self):
        return f"{self.connector_id} {self.date_from}..{self.date_to}"

    @property
    def is_clean(self):
        return not self.missing_keys and self.failed_count == 0

    @property
    def gap(self):
        return max(self.expected_count - self.sent_count, 0)
