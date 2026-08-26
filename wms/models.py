from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import AuditModel, Location, Unit


class MaterialTraceability(models.TextChoices):
    NONE = "NONE", "Sin trazabilidad"
    LOT = "LOT", "Por lote"
    SERIAL = "SERIAL", "Por serie"


class LocationOperationalType(models.TextChoices):
    STORAGE = "STORAGE", "Almacenamiento"
    RECEIVING = "RECEIVING", "Recepcion"
    SUPERMARKET = "SUPERMARKET", "Supermercado"
    LINE_SIDE = "LINE_SIDE", "Line side"
    QUARANTINE = "QUARANTINE", "Cuarentena"
    DISPATCH = "DISPATCH", "Despacho"


class InventoryState(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Disponible"
    QUARANTINE = "QUARANTINE", "Cuarentena"
    BLOCKED = "BLOCKED", "Bloqueado"
    IN_TRANSIT = "IN_TRANSIT", "En transito"
    SCRAP = "SCRAP", "Baja"


class InboundReceiptStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    RECEIVED = "RECEIVED", "Recibida"
    CANCELLED = "CANCELLED", "Cancelada"


class InventoryMovementType(models.TextChoices):
    RECEIPT = "RECEIPT", "Recepcion"
    TRANSFER = "TRANSFER", "Traslado"
    STATUS_CHANGE = "STATUS_CHANGE", "Cambio de estado"
    ADJUSTMENT_IN = "ADJUSTMENT_IN", "Ajuste positivo"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Ajuste negativo"


class MaterialCategory(AuditModel):
    code = models.CharField("Codigo", max_length=40, unique=True)
    name = models.CharField("Nombre", max_length=120)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Categoria de material"
        verbose_name_plural = "Categorias de material"

    def __str__(self):
        return f"{self.code} - {self.name}"


class Material(AuditModel):
    code = models.CharField("Codigo", max_length=80, unique=True)
    name = models.CharField("Nombre", max_length=180)
    description = models.TextField("Descripcion", blank=True)
    category = models.ForeignKey(
        MaterialCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="materials",
        verbose_name="Categoria",
    )
    base_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="wms_materials", verbose_name="Unidad base")
    traceability = models.CharField(
        "Trazabilidad", max_length=20, choices=MaterialTraceability.choices, default=MaterialTraceability.NONE
    )
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Material"
        verbose_name_plural = "Materiales"

    def __str__(self):
        return f"{self.code} - {self.name}"


class WmsLocationProfile(AuditModel):
    location = models.OneToOneField(Location, on_delete=models.CASCADE, related_name="wms_profile", verbose_name="Ubicacion")
    operational_type = models.CharField(
        "Tipo operativo", max_length=20, choices=LocationOperationalType.choices, default=LocationOperationalType.STORAGE
    )
    allows_mixed_materials = models.BooleanField("Permite materiales mixtos", default=True)
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        ordering = ["location__warehouse__code", "location__code"]
        verbose_name = "Perfil WMS de ubicacion"
        verbose_name_plural = "Perfiles WMS de ubicacion"

    def __str__(self):
        return f"{self.location} / {self.get_operational_type_display()}"


class InboundReceipt(AuditModel):
    code = models.CharField("Recepcion", max_length=80, unique=True)
    supplier_name = models.CharField("Proveedor", max_length=180, blank=True)
    container_number = models.CharField("Contenedor", max_length=80, blank=True)
    asn_reference = models.CharField("ASN / referencia externa", max_length=120, blank=True)
    destination_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="inbound_receipts", verbose_name="Ubicacion destino"
    )
    received_at = models.DateTimeField("Fecha de recepcion", default=timezone.now)
    status = models.CharField(
        "Estado", max_length=20, choices=InboundReceiptStatus.choices, default=InboundReceiptStatus.DRAFT, db_index=True
    )
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-received_at", "-id"]
        verbose_name = "Recepcion CKD"
        verbose_name_plural = "Recepciones CKD"

    def __str__(self):
        return self.code


class InboundReceiptLine(AuditModel):
    receipt = models.ForeignKey(InboundReceipt, on_delete=models.CASCADE, related_name="lines", verbose_name="Recepcion")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="receipt_lines", verbose_name="Material")
    expected_quantity = models.DecimalField("Cantidad esperada", max_digits=14, decimal_places=4, default=Decimal("0"))
    received_quantity = models.DecimalField("Cantidad recibida", max_digits=14, decimal_places=4, default=Decimal("0"))
    lot_number = models.CharField("Lote", max_length=120, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["receipt", "id"]
        verbose_name = "Linea de recepcion"
        verbose_name_plural = "Lineas de recepcion"

    def clean(self):
        super().clean()
        if self.expected_quantity < 0 or self.received_quantity < 0:
            raise ValidationError("Las cantidades de recepcion no pueden ser negativas.")

    def __str__(self):
        return f"{self.receipt.code} / {self.material.code}"


class MaterialLot(AuditModel):
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="lots", verbose_name="Material")
    number = models.CharField("Numero de lote", max_length=120)

    class Meta:
        ordering = ["material__code", "number"]
        constraints = [models.UniqueConstraint(fields=["material", "number"], name="wms_lot_material_number_uq")]
        verbose_name = "Lote de material"
        verbose_name_plural = "Lotes de material"

    def __str__(self):
        return f"{self.material.code} / {self.number}"


class MaterialSerial(AuditModel):
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="serials", verbose_name="Material")
    number = models.CharField("Numero de serie", max_length=120)
    lot = models.ForeignKey(MaterialLot, null=True, blank=True, on_delete=models.PROTECT, related_name="serials", verbose_name="Lote")

    class Meta:
        ordering = ["material__code", "number"]
        constraints = [models.UniqueConstraint(fields=["material", "number"], name="wms_serial_material_number_uq")]
        verbose_name = "Serie de material"
        verbose_name_plural = "Series de material"

    def clean(self):
        super().clean()
        if self.lot_id and self.lot.material_id != self.material_id:
            raise ValidationError({"lot": "El lote no pertenece al material seleccionado."})

    def __str__(self):
        return f"{self.material.code} / {self.number}"


class InventoryBalance(AuditModel):
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="balances", verbose_name="Material")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="inventory_balances", verbose_name="Ubicacion")
    state = models.CharField("Estado", max_length=20, choices=InventoryState.choices, default=InventoryState.AVAILABLE)
    lot = models.ForeignKey(MaterialLot, null=True, blank=True, on_delete=models.PROTECT, related_name="balances", verbose_name="Lote")
    serial = models.ForeignKey(MaterialSerial, null=True, blank=True, on_delete=models.PROTECT, related_name="balances", verbose_name="Serie")
    quantity = models.DecimalField("Cantidad", max_digits=14, decimal_places=4, default=Decimal("0"))

    class Meta:
        ordering = ["material__code", "location__warehouse__code", "location__code", "state", "id"]
        indexes = [
            models.Index(fields=["material", "location", "state"], name="wms_balance_material_loc_idx"),
            models.Index(fields=["serial"], name="wms_balance_serial_idx"),
        ]
        verbose_name = "Saldo de inventario"
        verbose_name_plural = "Saldos de inventario"

    def clean(self):
        super().clean()
        if self.quantity < 0:
            raise ValidationError({"quantity": "El saldo no puede ser negativo."})
        if self.lot_id and self.lot.material_id != self.material_id:
            raise ValidationError({"lot": "El lote no pertenece al material."})
        if self.serial_id:
            if self.serial.material_id != self.material_id:
                raise ValidationError({"serial": "La serie no pertenece al material."})
            if self.quantity != Decimal("1"):
                raise ValidationError({"quantity": "Una serie individual debe tener saldo exactamente igual a 1."})

    def __str__(self):
        return f"{self.material.code} / {self.location.code} / {self.quantity}"


class InventoryMovement(AuditModel):
    movement_type = models.CharField("Tipo", max_length=20, choices=InventoryMovementType.choices, db_index=True)
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="movements", verbose_name="Material")
    quantity = models.DecimalField("Cantidad", max_digits=14, decimal_places=4)
    source_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="outbound_inventory_movements", verbose_name="Ubicacion origen"
    )
    destination_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="inbound_inventory_movements", verbose_name="Ubicacion destino"
    )
    source_state = models.CharField("Estado origen", max_length=20, choices=InventoryState.choices, blank=True)
    destination_state = models.CharField("Estado destino", max_length=20, choices=InventoryState.choices, blank=True)
    lot = models.ForeignKey(MaterialLot, null=True, blank=True, on_delete=models.PROTECT, related_name="movements", verbose_name="Lote")
    serial = models.ForeignKey(MaterialSerial, null=True, blank=True, on_delete=models.PROTECT, related_name="movements", verbose_name="Serie")
    receipt_line = models.ForeignKey(
        InboundReceiptLine, null=True, blank=True, on_delete=models.PROTECT, related_name="movements", verbose_name="Linea de recepcion"
    )
    external_reference = models.CharField("Referencia externa", max_length=120, blank=True)
    reason = models.CharField("Motivo", max_length=240, blank=True)
    moved_at = models.DateTimeField("Fecha/hora", default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-moved_at", "-id"]
        indexes = [
            models.Index(fields=["material", "moved_at"], name="wms_move_material_time_idx"),
            models.Index(fields=["movement_type", "moved_at"], name="wms_move_type_time_idx"),
        ]
        verbose_name = "Movimiento de inventario"
        verbose_name_plural = "Movimientos de inventario"

    def clean(self):
        super().clean()
        if self.quantity <= 0:
            raise ValidationError({"quantity": "La cantidad debe ser mayor a cero."})
        if self.lot_id and self.lot.material_id != self.material_id:
            raise ValidationError({"lot": "El lote no pertenece al material."})
        if self.serial_id:
            if self.serial.material_id != self.material_id:
                raise ValidationError({"serial": "La serie no pertenece al material."})
            if self.quantity != Decimal("1"):
                raise ValidationError({"quantity": "Una serie se mueve individualmente."})
        if self.movement_type == InventoryMovementType.RECEIPT and not self.destination_location_id:
            raise ValidationError({"destination_location": "La recepcion requiere una ubicacion destino."})
        if self.movement_type == InventoryMovementType.TRANSFER and (
            not self.source_location_id or not self.destination_location_id
        ):
            raise ValidationError("El traslado requiere origen y destino.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Los movimientos de inventario son inmutables.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_movement_type_display()} / {self.material.code} / {self.quantity}"
