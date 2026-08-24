from decimal import Decimal

from django.db import connection, models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.cache import cache
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from core.storages import private_storage

#-------------------Modelo abstracto para auditoría de creación y modificación
class AuditModel(models.Model):
    """
    Incluye fecha y hora de actualización al igual que el usuario.
    Tambien incluye la creación
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
    related_name="%(class)s_created", on_delete=models.SET_NULL)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
    related_name="%(class)s_updated", on_delete=models.SET_NULL)

    class Meta:
        abstract = True


#-------------------Aprobación formal de documentos maestros (ISO 13485 §4.2.4)
class ApprovalStatus(models.TextChoices):
    DRAFT    = "DRAFT",    "Borrador"
    APPROVED = "APPROVED", "Aprobado"
    OBSOLETE = "OBSOLETE", "Obsoleto"


class ControlledRecordSource(models.TextChoices):
    KORE = "KORE", "Kore"
    EXTERNAL = "EXTERNAL", "Externo"
    MANUAL = "MANUAL", "Manual"


class ControlledRecordAudience(models.TextChoices):
    INTERNAL = "INTERNAL", "Interno"
    CUSTOMER = "CUSTOMER", "Cliente"
    MIXED = "MIXED", "Mixto"


class ControlledRecordStatus(models.TextChoices):
    CREATED = "CREATED", "Creado"
    REVIEWED = "REVIEWED", "Revisado"
    ISSUED = "ISSUED", "Emitido"
    ACCEPTED = "ACCEPTED", "Aceptado"
    CLOSED = "CLOSED", "Cerrado"


class ControlledRecordType(AuditModel):
    code = models.CharField("Codigo", max_length=40, unique=True)
    name = models.CharField("Nombre", max_length=180)
    module = models.CharField("Modulo", max_length=50)
    process = models.CharField("Proceso", max_length=100, blank=True)
    source = models.CharField(
        "Origen",
        max_length=20,
        choices=ControlledRecordSource.choices,
        default=ControlledRecordSource.KORE,
    )
    audience = models.CharField(
        "Audiencia",
        max_length=20,
        choices=ControlledRecordAudience.choices,
        default=ControlledRecordAudience.INTERNAL,
    )
    show_on_customer_docs = models.BooleanField("Mostrar en documentos de cliente", default=False)
    model_label = models.CharField("Modelo relacionado", max_length=100, blank=True)
    description = models.TextField("Descripcion", blank=True)
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        verbose_name = "Tipo de registro controlado"
        verbose_name_plural = "Tipos de registros controlados"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class ControlledRecordLink(AuditModel):
    record_type = models.ForeignKey(
        ControlledRecordType,
        on_delete=models.PROTECT,
        related_name="links",
        verbose_name="Tipo de registro",
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    public_code = models.CharField("Codigo publico", max_length=80, blank=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=ControlledRecordStatus.choices,
        default=ControlledRecordStatus.CREATED,
    )
    event_at = models.DateTimeField("Fecha del evento", default=timezone.now)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        verbose_name = "Vinculo de registro controlado"
        verbose_name_plural = "Vinculos de registros controlados"
        ordering = ["record_type__code", "-event_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["record_type", "content_type", "object_id"],
                name="uniq_controlled_record_link",
            )
        ]
        indexes = [
            models.Index(fields=["content_type", "object_id"], name="ctrl_link_object_idx"),
            models.Index(fields=["status", "event_at"], name="ctrl_link_status_idx"),
        ]

    def __str__(self):
        return f"{self.record_type.code} -> {self.public_code or self.object_id}"


class ApprovableModel(models.Model):
    """
    Aprobación formal por separado de un documento técnico maestro
    (ficha, BOM, ruta, plan de calidad) — ISO 13485 §4.2.4 «Control de documentos».

    Interino hasta que Diseño y Desarrollo (§7.3) consolide todo en una sola
    transferencia con doble firma. Aquí cada maestro se aprueba por su cuenta,
    con responsable y fecha, y queda como documento controlado (no editable
    mientras esté Aprobado; debe revertirse a Borrador para corregir).
    """
    approval_status = models.CharField(
        "Estado de aprobación", max_length=10,
        choices=ApprovalStatus.choices, default=ApprovalStatus.DRAFT, db_index=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_approved", verbose_name="Aprobado por",
    )
    approved_at = models.DateTimeField("Fecha de aprobación", null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def is_approved(self):
        return self.approval_status == ApprovalStatus.APPROVED

    @property
    def is_locked(self):
        """Un documento aprobado es controlado: no se edita hasta revertirlo."""
        return self.approval_status == ApprovalStatus.APPROVED

    def approve(self, user):
        from django.utils import timezone
        if self.approval_status == ApprovalStatus.APPROVED:
            raise ValidationError("El documento ya está aprobado.")
        if self.approval_status == ApprovalStatus.OBSOLETE:
            raise ValidationError("Un documento obsoleto no puede aprobarse; cree una revisión nueva.")
        self.approval_status = ApprovalStatus.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.updated_by = user
        self.save(update_fields=["approval_status", "approved_by", "approved_at", "updated_by", "updated_at"])

    def revert_to_draft(self, user):
        if self.approval_status != ApprovalStatus.APPROVED:
            raise ValidationError("Solo un documento aprobado puede revertirse a borrador.")
        self.approval_status = ApprovalStatus.DRAFT
        self.approved_by = None
        self.approved_at = None
        self.updated_by = user
        self.save(update_fields=["approval_status", "approved_by", "approved_at", "updated_by", "updated_at"])

    def mark_obsolete(self, user):
        if self.approval_status == ApprovalStatus.OBSOLETE:
            raise ValidationError("El documento ya está obsoleto.")
        self.approval_status = ApprovalStatus.OBSOLETE
        self.updated_by = user
        self.save(update_fields=["approval_status", "updated_by", "updated_at"])


#-------------------Modelo para esquemas tributarios para inventarios y transacciones
class TaxScheme(AuditModel):
    """
    Aqui se establece el modelo para gestionar los posible impuesto de manera dinamica
    Es decir genera un tabla de registro de estos valores 
    Incluye el nombre de impuesto, codigo y valor del impuesto tipo decimal
    """
    code = models.CharField(max_length=20,unique=True,
    help_text="Código interno del esquema tributario (ej: IVA12, IVA0, EXENTO)"
    )
    name = models.CharField(
    max_length=100,
    help_text="Nombre descriptivo (IVA 12%, IVA 0%, Exento, etc.)"
    )
    rate = models.DecimalField(max_digits=5,decimal_places=2,
    help_text="Porcentaje (ej. 12.00 para IVA 12%)"
    )
    is_active = models.BooleanField(default=True)

    applies_sales = models.BooleanField(default=True)
    applies_purchases = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Esquema Tributario"
        verbose_name_plural = "Esquemas Tributarios"

    def __str__(self):
        return f"{self.code} ({self.rate}%)"
    
#-------------------Categorias de unidades donde se consdiera las mas usadas en producto
class UnitCategory(models.TextChoices):
    """
    Aqui se establecen las categorias de unidades para la aprte de compra, venta y producción 
    Incluye Masa, longuitud, unidad (conteo), volumne, area y otros 
    """
    MASS = "MASS", "Masa"
    LENGTH = "LENGTH", "Longitud"
    COUNT = "COUNT", "Unidad (pieza, rollo, etc.)"
    VOLUME = "VOLUME", "Volumen"
    AREA = "AREA", "Área"
    OTHER = "OTHER", "Otro"
    
#-------------------Modelo de unidades de medida considerando como cegorias de UnitCategory
class Unit(AuditModel):
    """
    Aqui se establecen la entidad unidad de medida de producto ( materias primas, producto etc)
    Incluye codigo de unidad, nombre, categoria(UnitCategory), factor base para conversion 
    """
    code = models.CharField(max_length=10,unique=True,
    help_text="Código corto: kg, g, m, cm, un, caja, etc."
    )
    name = models.CharField(max_length=50,
    help_text="Nombre descriptivo: Kilogramo, Metro, Unidad, Caja..."
    )
    category = models.CharField(max_length=10,choices=UnitCategory.choices,default=UnitCategory.COUNT,
    )
    # factor relativo a la unidad base de su categoría
    factor_to_base = models.DecimalField(max_digits=10,decimal_places=4,
    help_text="Factor para convertir a la unidad base de la categoría"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Unidad de medida"
        verbose_name_plural = "Unidades de medida"

    def __str__(self):
        return f"{self.code} ({self.name})"
    
    def clean(self):
        super().clean()
        if self.factor_to_base <= 0:
            raise ValidationError({
                'factor_to_base': 'El factor de conversión debe ser mayor a 0'
            })


#-------------------Clasificación de tipos como minimo de bodega acorde a BPDT e ISO 13485
class WarehouseType(models.TextChoices):
    """
    Aqui se establecen los tipos de bodegas
    """
    QUARANTINE = "QUARANTINE", "Cuarentena"
    RAW = "RAW", "Materia prima"
    WIP = "WIP", "Semielaborado"
    FINISHED = "FINISHED", "Producto terminado"
    SCRAP = "SCRAP", "Producto de baja"
    RECALL = "RECALL", "Retiro de mercado"
    RETURNS    = "RETURNS",    "Devoluciones de clientes"
    STAGING    = "STAGING",    "Zona de predespacho"
    SAMPLES    = "SAMPLES",    "Muestras / retención"
    LABELS     = "LABELS",     "Etiquetas"
    PACK       = "PACK",       "Material de empaque"
    RETAIL     = "RETAIL",     "Punto de venta (POS)"
    OTHER      = "OTHER",      "Otro"


#-------------------Clasificación de tipos diferentes bodegas en el sistema 
class Warehouse(AuditModel):
    code = models.CharField(max_length=20,unique=True,
    help_text="Código interno de bodega (ej: BOD-CUA, BOD-MP, BOD-PT)"
    )
    name = models.CharField(max_length=100,
    help_text="Nombre descriptivo (ej: Bodega de cuarentena)"
    )
    type = models.CharField(max_length=20,choices=WarehouseType.choices,default=WarehouseType.OTHER,
    help_text="Tipo de bodega según clasificación regulatoria/operativa"
    )

    is_active = models.BooleanField(default=True)
    # Flags para flujos por defecto
    is_default_quarantine = models.BooleanField(default=False,
    help_text="Usar como bodega de cuarentena por defecto en recepción"
    )
    is_default_for_raw = models.BooleanField(default=False,
    help_text="Bodega por defecto para materia prima liberada"
    )

    is_default_fg_released = models.BooleanField(
        default=False,
        help_text="Bodega por defecto para producto terminado liberado."
    )

    class Meta:
        verbose_name = "Bodega"
        verbose_name_plural = "Bodegas"

    def __str__(self):
        return f"{self.code} - {self.name}"

# -------------------Modelo de tipo de ubicaciones
class Location(AuditModel):
    warehouse = models.ForeignKey(
    Warehouse, on_delete=models.CASCADE,related_name="locations",verbose_name="Bodega")
    code = models.CharField( max_length=30,
    help_text="Código de ubicación (ej: EST-01-N1-A)")
    name = models.CharField(max_length=100, blank=True,null=True, 
    help_text="Nombre o alias de la ubicació")
    description = models.CharField(max_length=255,blank=True,null=True,
    help_text="Descripción adicional (pasillo, estante, etc.)"
    )

    # Campos a usar  futuro un sistema de gestion en un centro de almacenamiento (WMS)
    row = models.CharField(max_length=10, blank=True, null=True)
    rack = models.CharField(max_length=10, blank=True, null=True)
    level = models.CharField(max_length=10, blank=True, null=True)

    # Capacidad WMS: límite de unidades base que admite la ubicación.
    max_units = models.DecimalField(
        "Capacidad (unidades)", max_digits=12, decimal_places=4,
        null=True, blank=True,
        help_text="Capacidad máxima en unidades base. Vacío = sin límite.",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Ubicación"
        verbose_name_plural = "Ubicaciones"
        unique_together = ("warehouse", "code")

    def __str__(self):
        return f"{self.warehouse.code} / {self.code}"


# ─── Configuración del Emisor (Singleton) ──────────────────
class SRIEnvironment(models.TextChoices):
    PRUEBAS = "1", "Pruebas"
    PRODUCCION = "2", "Producción"


class CompanyConfig(AuditModel):
    _CACHE_MISS = object()

    ruc = models.CharField("RUC", max_length=13)
    legal_name = models.CharField("Razón social", max_length=300)
    trade_name = models.CharField("Nombre comercial", max_length=300, blank=True)
    address = models.CharField("Dirección matriz", max_length=300)
    establishment_code = models.CharField(
        "Código establecimiento", max_length=3, default="001",
        help_text="Ej: 001",
    )
    emission_point = models.CharField(
        "Punto de emisión", max_length=3, default="001",
        help_text="Ej: 001",
    )
    special_taxpayer = models.CharField(
        "Contribuyente especial Nº", max_length=13, blank=True,
    )
    obligated_accounting = models.BooleanField(
        "Obligado a llevar contabilidad", default=True,
    )
    environment = models.CharField(
        "Ambiente SRI", max_length=1,
        choices=SRIEnvironment.choices, default=SRIEnvironment.PRUEBAS,
    )
    emission_type = models.CharField(
        "Tipo de emisión", max_length=1, default="1",
        help_text="1 = Emisión normal",
    )
    # El .p12 y su clave son material de firma: quien los tenga puede emitir
    # comprobantes en nombre de la empresa. Con el gateway configurado no se
    # guardan aqui — se mandan a la boveda de B22 y se descartan (b22_service).
    # Solo sobreviven en instalaciones sin gateway, que firman en local
    # (sales/sri_service._sign_xml_soap), y aun ahi van a PRIVATE_ROOT, que
    # nginx no sirve.
    certificate_file = models.FileField(
        "Certificado .p12", upload_to="sri_certs/", blank=True,
        storage=private_storage,
        help_text="Se guarda fuera de /media/: no tiene URL publica.",
    )
    certificate_password_encrypted = models.TextField(
        "Contraseña del certificado (cifrada)",
        blank=True,
        default="",
        help_text="Se almacena cifrada; nunca se muestra en claro.",
    )
    logo = models.ImageField("Logo", upload_to="company/", blank=True)

    # ── Gateway fiscal (B22) ─────────────────────────────────────────
    # Cada tenant tiene SU PROPIA credencial, restringida a su RUC en el
    # gateway. Asi un tenant no puede emitir con el RUC de otro, ni siquiera
    # por error: si una credencial se filtra, no compromete a los demas.
    # Se guarda cifrada (core.crypto) y nunca se muestra completa en pantalla.
    b22_api_key_encrypted = models.TextField(
        "Credencial del gateway fiscal (cifrada)",
        blank=True,
        default="",
        help_text="Se genera automaticamente al configurar el certificado. No se edita a mano.",
    )
    b22_integrator_id = models.IntegerField(
        "ID de integrador en el gateway",
        null=True,
        blank=True,
        help_text="Referencia para rotar la credencial sin crear un integrador duplicado.",
    )

    # ── Producción ───────────────────────────────────────────────────
    @property
    def certificate_password(self) -> str:
        """Clave del certificado en claro. Vacia si no hay o no se pudo descifrar."""
        from core.crypto import decrypt

        return decrypt(self.certificate_password_encrypted)

    @certificate_password.setter
    def certificate_password(self, value: str) -> None:
        from core.crypto import encrypt

        self.certificate_password_encrypted = encrypt(value or "")

    mp_shortage_tolerance_pct = models.DecimalField(
        "Tolerancia de faltante de MP (%)",
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text=(
            "Margen permitido cuando el stock de materia prima queda ligeramente por "
            "debajo de lo requerido (varianza de consumo o redondeo). Si el faltante "
            "está dentro de este %, la orden se libera/consume con una advertencia en "
            "vez de bloquearse. 0 = sin tolerancia (bloqueo estricto)."
        ),
    )

    # Compras / proveedores
    require_supplier_evaluation_for_purchase = models.BooleanField(
        "Bloquear compras sin evaluacion vigente de proveedor",
        default=True,
        help_text=(
            "Si esta activo, Compras solo permite proveedores con evaluacion "
            "formal calificada y no vencida."
        ),
    )
    supplier_evaluation_approval_threshold = models.DecimalField(
        "Umbral de aprobacion de proveedores (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("80.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
        help_text="Puntaje minimo para calificar una evaluacion de proveedor.",
    )
    supplier_evaluation_frequency_months = models.PositiveSmallIntegerField(
        "Frecuencia de reevaluacion de proveedores (meses)",
        default=12,
        help_text="Periodicidad por defecto para proveedores no criticos.",
    )
    critical_supplier_evaluation_frequency_months = models.PositiveSmallIntegerField(
        "Frecuencia de reevaluacion de proveedores criticos (meses)",
        default=6,
        help_text="Periodicidad por defecto para proveedores criticos.",
    )

    @property
    def b22_api_key(self) -> str:
        """Credencial en claro. Vacia si no hay o si no se pudo descifrar."""
        from core.crypto import decrypt

        return decrypt(self.b22_api_key_encrypted)

    @b22_api_key.setter
    def b22_api_key(self, value: str) -> None:
        from core.crypto import encrypt

        self.b22_api_key_encrypted = encrypt(value or "")

    @property
    def has_b22_credentials(self) -> bool:
        return bool(self.b22_api_key_encrypted)

    # ── Ente regulador sanitario ─────────────────────────────────────
    # El nombre del organismo se guarda aquí y NO se escribe en las plantillas:
    # las instituciones cambian de nombre (en Ecuador ha pasado) y ademas Kore
    # puede operar en otros paises (INVIMA en Colombia, DIGEMID en Peru).
    # Se cambia aquí una vez y se actualiza en todo el sistema.
    regulatory_agency = models.CharField(
        "Ente regulador sanitario",
        max_length=40,
        default="ARCSA",
        blank=True,
        help_text=(
            "Siglas del organismo que otorga el registro sanitario. "
            "Ej: ARCSA (Ecuador), INVIMA (Colombia), DIGEMID (Peru). "
            "Aparece en pantallas y documentos; si la institución cambia de "
            "nombre, se actualiza aquí y se refleja en todo el sistema."
        ),
    )
    regulatory_agency_full = models.CharField(
        "Nombre completo del ente regulador",
        max_length=200,
        blank=True,
        default="Agencia Nacional de Regulación, Control y Vigilancia Sanitaria",
        help_text="Nombre desarrollado, para documentos formales.",
    )

    # ── Generación automática de lotes de recepción ──────────────────
    lot_formula = models.CharField(
        "Fórmula de lote automático",
        max_length=100,
        default="{PREFIX}-{YYYYMM}-{SEQ:04d}",
        blank=True,
        help_text=(
            "Variables: {PREFIX} = prefijo del producto, {CODE} = código del producto, "
            "{YYYY} = año 4 dígitos, {YY} = año 2 dígitos, {MM} = mes, {DD} = día, "
            "{SEQ:04d} = secuencial con ceros. "
            "Ejemplo: {PREFIX}-{YYYYMM}-{SEQ:04d} → MP001-202605-0001"
        ),
    )
    lot_default_prefix = models.CharField(
        "Prefijo por defecto para lotes",
        max_length=20,
        default="REC",
        blank=True,
        help_text="Se usa cuando el producto no tiene prefijo de lote configurado.",
    )

    # ── Modo de envío de correos transaccionales ─────────────────────
    class EmailMode(models.TextChoices):
        LIVE     = "LIVE",     "En vivo — envía a destinatarios reales"
        TEST     = "TEST",     "Pruebas — redirige todos los correos a una dirección de prueba"
        DISABLED = "DISABLED", "Desactivado — no envía ningún correo transaccional"

    email_mode = models.CharField(
        "Modo de correo transaccional",
        max_length=10,
        choices=EmailMode.choices,
        default=EmailMode.DISABLED,
        help_text=(
            "En vivo: los correos van a proveedores/clientes reales. "
            "Pruebas: todos los correos se redirigen a la dirección de prueba. "
            "Desactivado: no se envía ningún correo (ideal durante implementación)."
        ),
    )
    email_test_address = models.EmailField(
        "Dirección de prueba",
        blank=True,
        help_text="Solo en modo Pruebas. Todos los correos irán a esta dirección en lugar del destinatario real.",
    )

    class Meta:
        verbose_name = "Configuración de empresa"
        verbose_name_plural = "Configuración de empresa"

    def __str__(self):
        return f"{self.ruc} – {self.legal_name}"

    def save(self, *args, **kwargs):
        # Singleton: solo permite 1 registro
        if not self.pk and CompanyConfig.objects.exists():
            raise ValidationError("Solo puede existir un registro de configuración de empresa.")
        super().save(*args, **kwargs)
        self.clear_cache()

    def delete(self, *args, **kwargs):
        self.clear_cache()
        return super().delete(*args, **kwargs)

    @classmethod
    def get(cls):
        cache_key = cls.cache_key()
        cached = cache.get(cache_key, cls._CACHE_MISS)
        if cached is not cls._CACHE_MISS:
            return cached

        config = cls.objects.first()
        cache.set(cache_key, config, timeout=300)
        return config

    @classmethod
    def cache_key(cls):
        schema = getattr(connection, "schema_name", "default") or "default"
        return f"core:company-config:{schema}"

    @classmethod
    def clear_cache(cls):
        cache.delete(cls.cache_key())


# ─── Registro de reportes/documentos emitidos (ISO 13485 trazabilidad documental) ──

class ReportRegistry(models.Model):
    """
    Registro auditable de cada documento/PDF emitido desde el ERP.
    Guarda un snapshot de los datos clave y un hash SHA-256 para
    demostrar en auditoría que el documento no fue alterado post-emisión.
    """
    document_code    = models.CharField("Código documento", max_length=20, unique=True)
    template_name    = models.CharField("Plantilla", max_length=150)
    template_version = models.CharField("Versión plantilla", max_length=10, default="v1")
    source_model     = models.CharField("Modelo origen", max_length=100, help_text="Ej: quality.QualityInspection")
    source_id        = models.PositiveIntegerField("ID origen")
    source_code      = models.CharField("Código origen", max_length=60, blank=True, help_text="Código legible: INS-2026-0001")
    emitted_at       = models.DateTimeField("Emitido el", auto_now_add=True, db_index=True)
    emitted_by       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="emitted_reports", verbose_name="Emitido por")
    data_snapshot    = models.JSONField("Snapshot de datos", default=dict)
    data_hash        = models.CharField("Hash SHA-256", max_length=64)

    class Meta:
        verbose_name = "Registro de reporte"
        verbose_name_plural = "Registro de reportes"
        ordering = ["-emitted_at"]
        indexes = [
            models.Index(fields=["source_model", "source_id"]),
        ]

    def __str__(self):
        return f"{self.document_code} — {self.source_code or self.source_model}/{self.source_id}"

    def verify_integrity(self) -> bool:
        """Re-calcula el hash y lo compara con el almacenado."""
        import json, hashlib
        snapshot_json = json.dumps(self.data_snapshot, sort_keys=True, default=str)
        expected = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        return expected == self.data_hash


class OperationalAuditModule(models.TextChoices):
    PROCUREMENT = "PROCUREMENT", "Compras"
    QUALITY = "QUALITY", "Calidad"
    INVENTORY = "INVENTORY", "Inventario"
    PRODUCTION = "PRODUCTION", "Produccion"
    SALES = "SALES", "Ventas"
    BILLING = "BILLING", "Facturacion"
    POS = "POS", "Punto de venta"
    SYSTEM = "SYSTEM", "Sistema"


class OperationalAuditAction(models.TextChoices):
    CREATE = "CREATE", "Creacion"
    UPDATE = "UPDATE", "Actualizacion"
    STATUS_CHANGE = "STATUS_CHANGE", "Cambio de estado"
    RELEASE = "RELEASE", "Liberacion"
    APPROVAL = "APPROVAL", "Aprobacion"
    MOVEMENT = "MOVEMENT", "Movimiento de inventario"
    DISPATCH = "DISPATCH", "Despacho"
    INVOICE = "INVOICE", "Facturacion"
    EXCEPTION = "EXCEPTION", "Excepcion"


class OperationalAuditEvent(models.Model):
    """
    Bitacora operativa transversal.

    Registra cambios importantes con actor, fecha/hora, estado anterior/nuevo,
    motivo y documento relacionado sin depender de una sola app de negocio.
    """
    event_at = models.DateTimeField("Fecha/hora", default=timezone.now, db_index=True)
    module = models.CharField("Modulo", max_length=30, choices=OperationalAuditModule.choices, db_index=True)
    action = models.CharField("Accion", max_length=30, choices=OperationalAuditAction.choices, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operational_audit_events",
        verbose_name="Usuario",
    )

    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operational_audit_sources",
    )
    source_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_object = GenericForeignKey("source_content_type", "source_object_id")
    source_model = models.CharField("Modelo origen", max_length=120, blank=True)
    source_code = models.CharField("Codigo origen", max_length=100, blank=True, db_index=True)

    document_type = models.CharField("Tipo de documento", max_length=100, blank=True)
    document_code = models.CharField("Codigo de documento", max_length=120, blank=True, db_index=True)

    related_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operational_audit_related",
    )
    related_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    related_object = GenericForeignKey("related_content_type", "related_object_id")
    related_code = models.CharField("Documento relacionado", max_length=120, blank=True, db_index=True)

    from_status = models.CharField("Estado anterior", max_length=60, blank=True)
    to_status = models.CharField("Estado nuevo", max_length=60, blank=True)
    reason = models.TextField("Motivo", blank=True)
    metadata = models.JSONField("Datos de soporte", default=dict, blank=True)

    class Meta:
        verbose_name = "Evento de bitacora operativa"
        verbose_name_plural = "Eventos de bitacora operativa"
        ordering = ["-event_at", "-id"]
        indexes = [
            models.Index(fields=["module", "event_at"], name="op_audit_module_time_idx"),
            models.Index(fields=["source_content_type", "source_object_id"], name="op_audit_source_idx"),
            models.Index(fields=["related_content_type", "related_object_id"], name="op_audit_related_idx"),
            models.Index(fields=["document_code", "event_at"], name="op_audit_doc_time_idx"),
        ]

    def __str__(self):
        code = self.document_code or self.source_code or self.related_code or self.pk
        return f"{self.get_module_display()} {self.get_action_display()} - {code}"


class EquipmentType(models.TextChoices):
    PRODUCTION_MACHINE = "PRODUCTION_MACHINE", "Maquinaria de produccion"
    MEASUREMENT = "MEASUREMENT", "Equipo de medicion / metrologia"
    AUXILIARY = "AUXILIARY", "Equipo auxiliar"
    TOOLING = "TOOLING", "Herramienta / utillaje"
    ZEBRA_PRINTER = "ZEBRA_PRINTER", "Impresora Zebra"
    LABEL_PRINTER = "LABEL_PRINTER", "Impresora de etiquetas"
    BARCODE_SCANNER = "BARCODE_SCANNER", "Lector de codigo"
    SCALE = "SCALE", "Balanza"
    WORKSTATION = "WORKSTATION", "Terminal de piso"
    OTHER = "OTHER", "Otro"


class ConnectionProtocol(models.TextChoices):
    TCP_RAW = "TCP_RAW", "TCP/IP (RAW 9100)"
    USB = "USB", "USB"
    SERIAL = "SERIAL", "Serial (COM/RS232)"
    API = "API", "API/HTTP"
    OTHER = "OTHER", "Otro"


class ResourceControlStatus(models.TextChoices):
    NOT_APPLICABLE = "NOT_APPLICABLE", "No aplica"
    PENDING = "PENDING", "Pendiente"
    CURRENT = "CURRENT", "Vigente"
    DUE_SOON = "DUE_SOON", "Por vencer"
    OVERDUE = "OVERDUE", "Vencido"


def dated_control_status(required, next_date):
    """
    Vigencia de un control con fecha de vencimiento.

    Lo comparten la calibracion y el mantenimiento del equipo y la habilitacion
    de un operario: los tres responden la misma pregunta y deben responderla
    igual, para que el usuario aprenda "vigente / por vencer / vencido" una sola
    vez en toda la aplicacion.

    Sin fecha de vencimiento el control queda PENDIENTE, no vigente: un control
    exigido del que no se sabe cuando caduca no habilita nada.
    """
    if not required:
        return ResourceControlStatus.NOT_APPLICABLE
    if not next_date:
        return ResourceControlStatus.PENDING
    today = timezone.localdate()
    if next_date < today:
        return ResourceControlStatus.OVERDUE
    if (next_date - today).days <= 30:
        return ResourceControlStatus.DUE_SOON
    return ResourceControlStatus.CURRENT


class LabelTemplateKey(models.TextChoices):
    PROCUREMENT_RECEPTION = "PROCUREMENT_RECEPTION", "Recepcion de compras"
    PRODUCTION_FINISHED_LOT = "PRODUCTION_FINISHED_LOT", "Producto terminado"


class LabelPrinterMode(models.TextChoices):
    A4 = "A4", "Hoja A4"
    ZEBRA = "ZEBRA", "Impresora Zebra"


class LabelPrintReason(models.TextChoices):
    INITIAL = "INITIAL", "Impresion inicial"
    REPRINT = "REPRINT", "Reimpresion"
    TEST = "TEST", "Prueba"
    OTHER = "OTHER", "Otro"


class LabelPrintStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    GENERATED = "GENERATED", "Documento generado"
    SENT = "SENT", "Enviado a impresora"
    FAILED = "FAILED", "Fallido"


class LabelFieldSource(models.TextChoices):
    NONE = "NONE", "No mostrar"
    PRODUCT_CODE = "product_code", "Codigo de producto"
    DESCRIPTION = "description", "Descripcion"
    LOT = "lot", "Lote"
    QUANTITY = "quantity", "Cantidad"
    PRODUCTION_DATE = "production_date", "Fecha de produccion"
    EXPIRY_DATE = "expiry_date", "Fecha de caducidad"
    SUPPLIER = "supplier", "Proveedor"
    RECEPTION = "reception", "Recepcion"
    PURCHASE_ORDER = "purchase_order", "Orden de compra"
    BARCODE = "barcode", "Codigo de barras"


def default_label_field_map():
    return [
        {"label": "Producto", "source": LabelFieldSource.PRODUCT_CODE},
        {"label": "Descripcion", "source": LabelFieldSource.DESCRIPTION},
        {"label": "Lote", "source": LabelFieldSource.LOT},
        {"label": "Cantidad", "source": LabelFieldSource.QUANTITY},
        {"label": "Fec. Prod.", "source": LabelFieldSource.PRODUCTION_DATE},
        {"label": "Barcode", "source": LabelFieldSource.BARCODE},
    ]


class LabelTemplateConfig(AuditModel):
    key = models.CharField(
        "Uso de etiqueta",
        max_length=60,
        choices=LabelTemplateKey.choices,
        unique=True,
    )
    name = models.CharField("Nombre", max_length=120)
    title = models.CharField("Titulo impreso", max_length=120, default="ETIQUETA DE LOTE")
    printer_mode = models.CharField(
        "Tipo de impresion",
        max_length=10,
        choices=LabelPrinterMode.choices,
        default=LabelPrinterMode.A4,
    )
    printer = models.ForeignKey(
        "core.EquipmentIntegration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="label_templates",
        verbose_name="Impresora configurada",
    )
    a4_columns = models.PositiveSmallIntegerField("Columnas en A4", default=2)
    a4_rows = models.PositiveSmallIntegerField("Filas en A4", default=5)
    label_width_mm = models.DecimalField("Ancho etiqueta A4 (mm)", max_digits=6, decimal_places=2, default=95)
    label_height_mm = models.DecimalField("Alto etiqueta A4 (mm)", max_digits=6, decimal_places=2, default=52)
    zebra_width_mm = models.DecimalField("Ancho Zebra (mm)", max_digits=6, decimal_places=2, default=100)
    zebra_height_mm = models.DecimalField("Alto Zebra (mm)", max_digits=6, decimal_places=2, default=70)
    field_map = models.JSONField("Campos de etiqueta", default=default_label_field_map)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        verbose_name = "Plantilla de etiqueta"
        verbose_name_plural = "Plantillas de etiquetas"
        ordering = ["key"]

    def __str__(self):
        return self.name or self.get_key_display()

    @property
    def active_width_mm(self):
        return self.zebra_width_mm if self.printer_mode == LabelPrinterMode.ZEBRA else self.label_width_mm

    @property
    def active_height_mm(self):
        return self.zebra_height_mm if self.printer_mode == LabelPrinterMode.ZEBRA else self.label_height_mm

    def normalized_field_map(self, min_rows=6):
        valid_sources = {choice[0] for choice in LabelFieldSource.choices}
        rows = []
        for row in self.field_map or []:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()
            source = str(row.get("source") or LabelFieldSource.NONE).strip()
            if source not in valid_sources:
                source = LabelFieldSource.NONE
            rows.append({"label": label, "source": source})
        while len(rows) < min_rows:
            rows.append({"label": "", "source": LabelFieldSource.NONE})
        return rows

    def clean(self):
        super().clean()
        if self.a4_columns < 1 or self.a4_columns > 4:
            raise ValidationError({"a4_columns": "Use entre 1 y 4 columnas."})
        if self.a4_rows < 1 or self.a4_rows > 12:
            raise ValidationError({"a4_rows": "Use entre 1 y 12 filas."})
        if self.printer and self.printer.equipment_type not in {
            EquipmentType.ZEBRA_PRINTER,
            EquipmentType.LABEL_PRINTER,
        }:
            raise ValidationError({"printer": "Seleccione una impresora de etiquetas."})


class LabelPrintAuditLog(AuditModel):
    template = models.ForeignKey(
        LabelTemplateConfig,
        on_delete=models.PROTECT,
        related_name="print_logs",
        verbose_name="Plantilla",
    )
    reason = models.CharField(
        "Motivo",
        max_length=20,
        choices=LabelPrintReason.choices,
        default=LabelPrintReason.INITIAL,
    )
    copy_count = models.PositiveIntegerField("Copias por item", default=1)
    item_count = models.PositiveIntegerField("Items impresos", default=1)
    printer_mode = models.CharField(
        "Tipo de impresion",
        max_length=10,
        choices=LabelPrinterMode.choices,
        default=LabelPrinterMode.A4,
    )
    status = models.CharField(
        "Resultado",
        max_length=20,
        choices=LabelPrintStatus.choices,
        default=LabelPrintStatus.PENDING,
        db_index=True,
    )
    result_detail = models.TextField("Detalle del resultado", blank=True)
    output_sha256 = models.CharField(
        "Huella SHA-256 de la salida",
        max_length=64,
        blank=True,
    )
    printer = models.ForeignKey(
        "core.EquipmentIntegration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="label_print_logs",
        verbose_name="Impresora",
    )
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    source_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_object = GenericForeignKey("source_content_type", "source_object_id")
    source_code = models.CharField("Origen", max_length=80, blank=True)
    data_snapshot = models.JSONField("Snapshot impreso", default=dict)
    printed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="core_label_print_logs",
        verbose_name="Impreso por",
    )
    printed_at = models.DateTimeField("Fecha de impresion", auto_now_add=True, db_index=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        verbose_name = "Registro de impresion de etiqueta"
        verbose_name_plural = "Registros de impresion de etiquetas"
        ordering = ["-printed_at", "-id"]
        indexes = [
            models.Index(fields=["source_content_type", "source_object_id"], name="label_log_source_idx"),
            models.Index(fields=["printed_at"], name="label_log_printed_idx"),
        ]

    def __str__(self):
        return f"{self.template} x{self.copy_count} ({self.get_reason_display()})"

    @property
    def total_labels(self):
        return self.copy_count * self.item_count

    def mark_result(self, status, detail="", user=None):
        valid_statuses = {choice[0] for choice in LabelPrintStatus.choices}
        if status not in valid_statuses:
            raise ValidationError({"status": "Resultado de impresion invalido."})
        self.status = status
        self.result_detail = str(detail or "").strip()
        if user is not None:
            self.updated_by = user
        self.save(
            update_fields=[
                "status",
                "result_detail",
                "updated_by",
                "updated_at",
            ]
        )


class EquipmentIntegration(AuditModel):
    code = models.CharField(
        max_length=30,
        unique=True,
        help_text="Codigo interno del equipo (ej: ZEBRA-PT-01).",
    )
    name = models.CharField(
        max_length=120,
        help_text="Nombre descriptivo (ej: Zebra despacho bodega PT).",
    )
    equipment_type = models.CharField(
        max_length=30,
        choices=EquipmentType.choices,
        default=EquipmentType.OTHER,
    )
    asset_code = models.CharField(
        max_length=50,
        blank=True,
        help_text="Codigo de activo fijo o identificacion patrimonial.",
    )
    manufacturer = models.CharField(max_length=120, blank=True)
    model = models.CharField(max_length=120, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    operating_parameters = models.CharField(
        "Variable operativa",
        max_length=200,
        blank=True,
        help_text="Rango o parametro de trabajo. Ej: puntada 1,4-3,6 mm; 4500-5000 ppm.",
    )
    is_quality_critical = models.BooleanField(
        default=False,
        help_text="Marca equipos que pueden afectar calidad, trazabilidad o liberacion.",
    )
    connection_protocol = models.CharField(
        max_length=20,
        choices=ConnectionProtocol.choices,
        default=ConnectionProtocol.OTHER,
    )
    host = models.CharField(
        max_length=255,
        blank=True,
        help_text="IP o hostname del equipo (para TCP).",
    )
    port = models.PositiveIntegerField(
        default=9100,
        blank=True,
        null=True,
        help_text="Puerto de red (ej: 9100 para Zebra).",
    )
    serial_port = models.CharField(
        max_length=50,
        blank=True,
        help_text="Puerto serial (ej: COM3, /dev/ttyS0).",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment_integrations",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment_integrations",
    )
    is_active = models.BooleanField(default=True)
    requires_calibration = models.BooleanField(default=False)
    last_calibration_date = models.DateField(null=True, blank=True)
    next_calibration_date = models.DateField(null=True, blank=True)
    calibration_certificate_ref = models.CharField(
        max_length=120,
        blank=True,
        help_text="Codigo o referencia del certificado vigente.",
    )
    calibration_notes = models.TextField(blank=True)
    # Enciende el control de habilitacion de operarios para esta maquina.
    # Nace en falso a proposito: activarlo de golpe en toda la planta, con cero
    # habilitaciones cargadas, dejaria a todo el mundo sin poder producir. Se
    # enciende maquina por maquina, cuando esa maquina ya tiene a su gente
    # habilitada.
    requires_qualification = models.BooleanField(
        "Exige operario habilitado",
        default=False,
        help_text="Si esta activo, solo pueden operarlo quienes tengan habilitacion vigente.",
    )
    requires_maintenance = models.BooleanField(default=False)
    last_maintenance_date = models.DateField(null=True, blank=True)
    next_maintenance_date = models.DateField(null=True, blank=True)
    maintenance_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Equipo / Integracion"
        verbose_name_plural = "Equipos / Integraciones"

    def __str__(self):
        return f"{self.code} - {self.name}"

    def _dated_control_status(self, required, next_date):
        return dated_control_status(required, next_date)

    @property
    def calibration_status(self):
        return self._dated_control_status(
            self.requires_calibration,
            self.next_calibration_date,
        )

    @property
    def calibration_status_label(self):
        return ResourceControlStatus(self.calibration_status).label

    @property
    def maintenance_status(self):
        return self._dated_control_status(
            self.requires_maintenance,
            self.next_maintenance_date,
        )

    @property
    def maintenance_status_label(self):
        return ResourceControlStatus(self.maintenance_status).label

    @property
    def is_calibration_valid(self):
        return self.calibration_status not in {
            ResourceControlStatus.PENDING,
            ResourceControlStatus.OVERDUE,
        }

    @property
    def is_maintenance_valid(self):
        return self.maintenance_status not in {
            ResourceControlStatus.PENDING,
            ResourceControlStatus.OVERDUE,
        }

    @property
    def can_be_used(self):
        return self.is_active and self.is_calibration_valid and self.is_maintenance_valid

    def qualification_issue_for(self, user):
        """
        Motivo por el que este usuario no puede operar el equipo, o "" si puede.

        Devuelve texto y no un booleano porque el mensaje va directo a la
        pantalla: quien intenta ejecutar necesita saber si le falta la
        habilitacion o si la tiene vencida, no solo que no puede.
        """
        if not self.requires_qualification:
            return ""
        if not user or not getattr(user, "is_authenticated", False):
            return f"{self.code}: se requiere operario identificado"
        habilitacion = self.qualifications.filter(operator=user, is_active=True).first()
        if habilitacion is None:
            return f"{self.code}: el operario no esta habilitado"
        if not habilitacion.is_valid:
            return f"{self.code}: habilitacion {habilitacion.status_label.lower()}"
        return ""

    def clean(self):
        super().clean()
        if self.location and not self.warehouse:
            raise ValidationError(
                {"warehouse": "Debes seleccionar una bodega cuando indiques ubicacion."}
            )
        if self.location and self.warehouse and self.location.warehouse_id != self.warehouse_id:
            raise ValidationError(
                {"location": "La ubicacion debe pertenecer a la bodega seleccionada."}
            )
        if self.connection_protocol == ConnectionProtocol.TCP_RAW:
            if not self.host:
                raise ValidationError({"host": "Debes indicar host/IP para conexion TCP."})
            if not self.port:
                raise ValidationError({"port": "Debes indicar puerto para conexion TCP."})
        if self.requires_calibration and self.next_calibration_date and self.last_calibration_date:
            if self.next_calibration_date < self.last_calibration_date:
                raise ValidationError(
                    {"next_calibration_date": "La proxima calibracion no puede ser anterior a la ultima."}
                )
        if self.requires_maintenance and self.next_maintenance_date and self.last_maintenance_date:
            if self.next_maintenance_date < self.last_maintenance_date:
                raise ValidationError(
                    {"next_maintenance_date": "El proximo mantenimiento no puede ser anterior al ultimo."}
                )



class OperatorQualification(AuditModel):
    """
    Habilitacion de una persona para operar un equipo (ISO 13485 §6.2).

    Responde una pregunta que el permiso de Django no responde: esta persona
    tiene permiso de entrar a la pantalla, pero ¿esta capacitada para usar esta
    maquina? Son controles distintos y conviven.

    Sigue el mismo patron que la calibracion del equipo — una fila por par, con
    fecha de otorgamiento y de revalidacion — para que el usuario lea la
    vigencia con el mismo vocabulario en toda la aplicacion.

    La habilitacion caduca. Una sin fecha de revalidacion queda PENDIENTE y no
    habilita: un control del que no se sabe cuando vence no es un control.
    """
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="equipment_qualifications",
        verbose_name="Operario",
    )
    equipment = models.ForeignKey(
        EquipmentIntegration,
        on_delete=models.CASCADE,
        related_name="qualifications",
        verbose_name="Equipo",
    )
    qualified_on = models.DateField("Habilitado desde")
    revalidate_on = models.DateField(
        "Revalidar el",
        null=True, blank=True,
        help_text="Sin esta fecha la habilitacion queda pendiente y no habilita.",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="qualifications_granted",
        verbose_name="Otorgada por",
    )
    evidence_reference = models.CharField(
        "Evidencia de capacitacion",
        max_length=120,
        blank=True,
        help_text="Referencia del registro de capacitacion firmado (ej: CAP-2026-014).",
    )
    notes = models.TextField("Notas", blank=True)
    is_active = models.BooleanField("Activa", default=True, db_index=True)

    class Meta:
        verbose_name = "Habilitacion de operario"
        verbose_name_plural = "Habilitaciones de operarios"
        ordering = ["equipment__code", "operator__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["operator", "equipment"],
                name="uniq_qualification_operator_equipment",
            ),
        ]

    def __str__(self):
        return f"{self.operator} · {self.equipment.code}"

    def clean(self):
        super().clean()
        if self.revalidate_on and self.qualified_on and self.revalidate_on < self.qualified_on:
            raise ValidationError(
                {"revalidate_on": "La revalidacion no puede ser anterior a la habilitacion."}
            )

    @property
    def status(self):
        # `is_active` hace de "requerido": una habilitacion dada de baja no
        # vence, simplemente no aplica.
        return dated_control_status(self.is_active, self.revalidate_on)

    @property
    def status_label(self):
        return ResourceControlStatus(self.status).label

    @property
    def is_valid(self):
        return self.status not in {
            ResourceControlStatus.PENDING,
            ResourceControlStatus.OVERDUE,
            ResourceControlStatus.NOT_APPLICABLE,
        }
