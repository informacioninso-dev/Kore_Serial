from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string

from assembly.models import AssemblyStation, Plant, StationEventType
from core.models import AuditModel, ConnectionProtocol, EquipmentIntegration


def generate_gateway_token():
    return get_random_string(48)


class EdgeGatewayStatus(models.TextChoices):
    ONLINE = "ONLINE", "En linea"
    DEGRADED = "DEGRADED", "Degradado"
    OFFLINE = "OFFLINE", "Fuera de linea"
    DISABLED = "DISABLED", "Deshabilitado"


class EdgeDeviceType(models.TextChoices):
    SCANNER = "SCANNER", "Lector de codigo"
    TORQUE_TOOL = "TORQUE_TOOL", "Torquimetro"
    PLC = "PLC", "PLC"
    SENSOR = "SENSOR", "Sensor"
    PRINTER = "PRINTER", "Impresora"
    TERMINAL = "TERMINAL", "Terminal de piso"
    OTHER = "OTHER", "Otro"


class EdgeSignalStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    NORMALIZED = "NORMALIZED", "Normalizada"
    IGNORED = "IGNORED", "Ignorada"
    REJECTED = "REJECTED", "Rechazada"


class EdgeRuleAction(models.TextChoices):
    STATION_EVENT = "STATION_EVENT", "Evento de estacion"
    MEASUREMENT = "MEASUREMENT", "Medicion productiva"
    IGNORE = "IGNORE", "Ignorar"


class EdgeCommandType(models.TextChoices):
    PING = "PING", "Ping"
    FLUSH_BUFFER = "FLUSH_BUFFER", "Vaciar buffer"
    RELOAD_CONFIG = "RELOAD_CONFIG", "Recargar configuracion"
    RESTART_AGENT = "RESTART_AGENT", "Reiniciar agente"
    PRINT_LABEL = "PRINT_LABEL", "Imprimir etiqueta"
    CUSTOM = "CUSTOM", "Personalizado"


class EdgeCommandStatus(models.TextChoices):
    QUEUED = "QUEUED", "En cola"
    SENT = "SENT", "Entregado"
    ACKED = "ACKED", "Confirmado"
    FAILED = "FAILED", "Fallido"
    EXPIRED = "EXPIRED", "Expirado"


class EdgeGateway(AuditModel):
    """Collector independiente que vive en planta y habla con los equipos.

    El MES no conversa con maquinas: conversa con este gateway, que traduce
    senales tecnicas a eventos de negocio y aguanta cortes de red.
    """

    code = models.CharField("Codigo", max_length=40, unique=True)
    name = models.CharField("Nombre", max_length=120)
    plant = models.ForeignKey(
        Plant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="edge_gateways",
        verbose_name="Planta",
    )
    host = models.CharField("Host o IP", max_length=255, blank=True)
    agent_version = models.CharField("Version del agente", max_length=40, blank=True)
    auth_token = models.CharField(
        "Token de autenticacion",
        max_length=64,
        unique=True,
        default=generate_gateway_token,
        help_text="Credencial que el collector envia en cada llamada.",
    )
    heartbeat_interval_seconds = models.PositiveIntegerField(
        "Intervalo de latido (s)",
        default=60,
        help_text="Cada cuanto debe reportarse el gateway.",
    )
    degraded_after_missed = models.PositiveIntegerField(
        "Latidos perdidos para degradado",
        default=2,
        help_text="Latidos consecutivos sin recibir antes de marcar degradado.",
    )
    offline_after_missed = models.PositiveIntegerField(
        "Latidos perdidos para fuera de linea",
        default=5,
        help_text="Latidos consecutivos sin recibir antes de marcar fuera de linea.",
    )
    last_seen_at = models.DateTimeField("Ultimo contacto", null=True, blank=True, db_index=True)
    buffered_signal_count = models.PositiveIntegerField(
        "Senales en buffer",
        default=0,
        help_text="Ultimo tamano de buffer offline informado por el gateway.",
    )
    is_active = models.BooleanField("Activo", default=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Gateway"
        verbose_name_plural = "Gateways"

    def __str__(self):
        return f"{self.code} - {self.name}"

    def clean(self):
        if self.offline_after_missed <= self.degraded_after_missed:
            raise ValidationError(
                {"offline_after_missed": "Debe ser mayor que los latidos para degradado."}
            )

    @property
    def health_status(self):
        """Estado derivado del ultimo latido, no de lo que el gateway diga."""
        if not self.is_active:
            return EdgeGatewayStatus.DISABLED
        if self.last_seen_at is None:
            return EdgeGatewayStatus.OFFLINE
        silence = (timezone.now() - self.last_seen_at).total_seconds()
        if silence > self.heartbeat_interval_seconds * self.offline_after_missed:
            return EdgeGatewayStatus.OFFLINE
        if silence > self.heartbeat_interval_seconds * self.degraded_after_missed:
            return EdgeGatewayStatus.DEGRADED
        return EdgeGatewayStatus.ONLINE

    @property
    def health_status_label(self):
        return EdgeGatewayStatus(self.health_status).label

    @property
    def seconds_since_last_seen(self):
        if self.last_seen_at is None:
            return None
        return int((timezone.now() - self.last_seen_at).total_seconds())

    def rotate_token(self):
        self.auth_token = generate_gateway_token()
        return self.auth_token


class EdgeDevice(AuditModel):
    """Equipo fisico colgado de un gateway: lector, torquimetro, PLC, sensor."""

    gateway = models.ForeignKey(
        EdgeGateway,
        on_delete=models.CASCADE,
        related_name="devices",
        verbose_name="Gateway",
    )
    code = models.CharField("Codigo", max_length=40, unique=True)
    name = models.CharField("Nombre", max_length=120)
    device_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=EdgeDeviceType.choices,
        default=EdgeDeviceType.OTHER,
    )
    protocol = models.CharField(
        "Protocolo",
        max_length=20,
        choices=ConnectionProtocol.choices,
        default=ConnectionProtocol.OTHER,
    )
    address = models.CharField(
        "Direccion",
        max_length=255,
        blank=True,
        help_text="IP:puerto, puerto serial o identificador del canal.",
    )
    equipment = models.ForeignKey(
        EquipmentIntegration,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="edge_devices",
        verbose_name="Equipo configurado",
        help_text="Enlaza con el maestro de equipos de Configuracion.",
    )
    station = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="edge_devices",
        verbose_name="Estacion",
    )
    is_active = models.BooleanField("Activo", default=True)
    last_seen_at = models.DateTimeField("Ultimo dato", null=True, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["gateway__code", "code"]
        verbose_name = "Dispositivo conectado"
        verbose_name_plural = "Dispositivos conectados"

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def equipment_code(self):
        return self.equipment.code if self.equipment_id else ""


class EdgeSignalRule(AuditModel):
    """Traduce una senal tecnica cruda a un hecho de negocio del MES."""

    code = models.CharField("Codigo", max_length=40, unique=True)
    name = models.CharField("Nombre", max_length=120)
    signal_key = models.CharField(
        "Clave de senal",
        max_length=80,
        help_text="Identificador tecnico que envia el equipo (ej: torque.final).",
    )
    device = models.ForeignKey(
        EdgeDevice,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="rules",
        verbose_name="Dispositivo",
        help_text="Vacio aplica a cualquier dispositivo con esa clave de senal.",
    )
    device_type = models.CharField(
        "Tipo de dispositivo",
        max_length=20,
        choices=EdgeDeviceType.choices,
        blank=True,
        help_text="Filtro opcional cuando la regla no apunta a un dispositivo.",
    )
    action = models.CharField(
        "Accion",
        max_length=20,
        choices=EdgeRuleAction.choices,
        default=EdgeRuleAction.STATION_EVENT,
    )
    station_event_type = models.CharField(
        "Evento de estacion",
        max_length=20,
        choices=StationEventType.choices,
        blank=True,
    )
    measurement_code = models.CharField("Codigo de medicion", max_length=40, blank=True)
    measurement_name = models.CharField("Nombre de medicion", max_length=120, blank=True)
    unit_of_measure = models.CharField("Unidad", max_length=20, blank=True)
    min_value = models.DecimalField(
        "Valor minimo",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Si se define, una lectura fuera de rango se rechaza.",
    )
    max_value = models.DecimalField(
        "Valor maximo",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
    )
    priority = models.PositiveIntegerField(
        "Prioridad",
        default=100,
        help_text="Menor numero gana cuando varias reglas calzan.",
    )
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["priority", "code"]
        verbose_name = "Regla de normalizacion"
        verbose_name_plural = "Reglas de normalizacion"
        indexes = [
            models.Index(fields=["signal_key", "is_active"], name="edge_rule_key_active_idx"),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def clean(self):
        if self.action == EdgeRuleAction.STATION_EVENT and not self.station_event_type:
            raise ValidationError(
                {"station_event_type": "Requerido cuando la accion crea un evento de estacion."}
            )
        if self.action == EdgeRuleAction.MEASUREMENT and not self.measurement_code:
            raise ValidationError(
                {"measurement_code": "Requerido cuando la accion registra una medicion."}
            )
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValidationError({"max_value": "El maximo no puede ser menor que el minimo."})

    def matches(self, device, signal_key):
        if not self.is_active or self.signal_key != signal_key:
            return False
        if self.device_id and self.device_id != device.pk:
            return False
        if self.device_type and self.device_type != device.device_type:
            return False
        return True

    def value_issue(self, numeric_value):
        if numeric_value is None:
            if self.min_value is not None or self.max_value is not None:
                return "La senal no trae valor numerico y la regla exige rango."
            return ""
        if self.min_value is not None and numeric_value < self.min_value:
            return f"Lectura {numeric_value} bajo el minimo {self.min_value}."
        if self.max_value is not None and numeric_value > self.max_value:
            return f"Lectura {numeric_value} sobre el maximo {self.max_value}."
        return ""


class EdgeSignal(AuditModel):
    """Senal cruda recibida del piso, guardada antes de interpretarla.

    Se conserva tal como llego para poder reprocesar y auditar: el buffer
    offline del gateway reenvia lo acumulado y aqui se deduplica por
    external_id.
    """

    gateway = models.ForeignKey(
        EdgeGateway,
        on_delete=models.PROTECT,
        related_name="signals",
        verbose_name="Gateway",
    )
    device = models.ForeignKey(
        EdgeDevice,
        on_delete=models.PROTECT,
        related_name="signals",
        verbose_name="Dispositivo",
    )
    external_id = models.CharField(
        "Identificador externo",
        max_length=120,
        unique=True,
        help_text="Clave de idempotencia generada por el gateway.",
    )
    signal_key = models.CharField("Clave de senal", max_length=80, db_index=True)
    raw_value = models.CharField("Valor crudo", max_length=240, blank=True)
    numeric_value = models.DecimalField(
        "Valor numerico",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
    )
    unit_of_measure = models.CharField("Unidad", max_length=20, blank=True)
    unit_serial_number = models.CharField("Serie de unidad", max_length=120, blank=True)
    operator_username = models.CharField("Operario", max_length=150, blank=True)
    captured_at = models.DateTimeField("Capturada en equipo", default=timezone.now, db_index=True)
    received_at = models.DateTimeField("Recibida en servidor", auto_now_add=True)
    from_buffer = models.BooleanField(
        "Desde buffer offline",
        default=False,
        help_text="Llego reenviada tras un corte de red.",
    )
    payload = models.JSONField("Carga original", default=dict, blank=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=EdgeSignalStatus.choices,
        default=EdgeSignalStatus.PENDING,
        db_index=True,
    )
    result_detail = models.TextField("Detalle", blank=True)
    normalized_at = models.DateTimeField("Normalizada", null=True, blank=True)
    rule = models.ForeignKey(
        EdgeSignalRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="signals",
        verbose_name="Regla aplicada",
    )
    inbound_event = models.OneToOneField(
        "assembly.EquipmentInboundEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edge_signal",
        verbose_name="Evento MES generado",
    )
    measurement = models.OneToOneField(
        "assembly.ProductionMeasurement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edge_signal",
        verbose_name="Medicion generada",
    )

    class Meta:
        ordering = ["-captured_at", "-id"]
        verbose_name = "Senal de equipo"
        verbose_name_plural = "Senales de equipo"
        indexes = [
            models.Index(fields=["status", "captured_at"], name="edge_signal_status_time_idx"),
            models.Index(fields=["gateway", "captured_at"], name="edge_signal_gw_time_idx"),
        ]

    def __str__(self):
        return f"{self.signal_key} @ {self.device_id} ({self.external_id})"

    @property
    def latency_seconds(self):
        if not self.received_at:
            return None
        return int((self.received_at - self.captured_at).total_seconds())


class EdgeHealthCheck(AuditModel):
    """Latido del gateway: sirve para saber si el piso sigue reportando."""

    gateway = models.ForeignKey(
        EdgeGateway,
        on_delete=models.CASCADE,
        related_name="health_checks",
        verbose_name="Gateway",
    )
    reported_at = models.DateTimeField("Reportado", default=timezone.now, db_index=True)
    agent_version = models.CharField("Version del agente", max_length=40, blank=True)
    queue_depth = models.PositiveIntegerField("Cola pendiente", default=0)
    buffered_count = models.PositiveIntegerField("Senales en buffer", default=0)
    cpu_percent = models.DecimalField(
        "CPU %", max_digits=5, decimal_places=2, null=True, blank=True
    )
    memory_percent = models.DecimalField(
        "Memoria %", max_digits=5, decimal_places=2, null=True, blank=True
    )
    latency_ms = models.PositiveIntegerField("Latencia (ms)", null=True, blank=True)
    status = models.CharField(
        "Estado informado",
        max_length=20,
        choices=EdgeGatewayStatus.choices,
        default=EdgeGatewayStatus.ONLINE,
    )
    detail = models.TextField("Detalle", blank=True)

    class Meta:
        ordering = ["-reported_at", "-id"]
        verbose_name = "Latido de gateway"
        verbose_name_plural = "Latidos de gateway"
        indexes = [
            models.Index(fields=["gateway", "reported_at"], name="edge_health_gw_time_idx"),
        ]

    def __str__(self):
        return f"{self.gateway_id} @ {self.reported_at:%d/%m/%Y %H:%M}"


class EdgeCommand(AuditModel):
    """Orden que baja del MES al gateway.

    El handshake es selectivo a proposito: el gateway toma los comandos en cola
    cuando puede y confirma el resultado. Nadie empuja nada hacia planta.
    """

    gateway = models.ForeignKey(
        EdgeGateway,
        on_delete=models.CASCADE,
        related_name="commands",
        verbose_name="Gateway",
    )
    device = models.ForeignKey(
        EdgeDevice,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="commands",
        verbose_name="Dispositivo",
    )
    command_type = models.CharField(
        "Comando",
        max_length=20,
        choices=EdgeCommandType.choices,
        default=EdgeCommandType.PING,
    )
    payload = models.JSONField("Parametros", default=dict, blank=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=EdgeCommandStatus.choices,
        default=EdgeCommandStatus.QUEUED,
        db_index=True,
    )
    issued_at = models.DateTimeField("Emitido", default=timezone.now)
    sent_at = models.DateTimeField("Entregado", null=True, blank=True)
    acked_at = models.DateTimeField("Confirmado", null=True, blank=True)
    expires_at = models.DateTimeField("Expira", null=True, blank=True)
    response = models.JSONField("Respuesta", default=dict, blank=True)
    detail = models.TextField("Detalle", blank=True)

    class Meta:
        ordering = ["-issued_at", "-id"]
        verbose_name = "Comando a planta"
        verbose_name_plural = "Comandos a planta"
        indexes = [
            models.Index(fields=["gateway", "status"], name="edge_cmd_gw_status_idx"),
        ]

    def __str__(self):
        return f"{self.command_type} -> {self.gateway_id}"

    @property
    def is_expired(self):
        return bool(self.expires_at and timezone.now() > self.expires_at)

    def default_expiry(self):
        return self.issued_at + timedelta(minutes=30)
