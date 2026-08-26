from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from assembly.models import AssemblyStation, ProductionPlan, SerializedUnit
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
    CONSUMPTION = "CONSUMPTION", "Consumo de ensamble"


class AssemblyKitStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    RELEASED = "RELEASED", "Liberado"
    READY = "READY", "Completo"
    DELIVERED = "DELIVERED", "Entregado"
    CANCELLED = "CANCELLED", "Cancelado"


class PickMissionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    RELEASED = "RELEASED", "Liberada"
    IN_PROGRESS = "IN_PROGRESS", "En proceso"
    COMPLETED = "COMPLETED", "Completada"
    CANCELLED = "CANCELLED", "Cancelada"


class PickTaskStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    PICKED = "PICKED", "Recogida"
    CANCELLED = "CANCELLED", "Cancelada"


class KanbanSignalStatus(models.TextChoices):
    OPEN = "OPEN", "Pendiente"
    IN_PROGRESS = "IN_PROGRESS", "En proceso"
    FULFILLED = "FULFILLED", "Atendida"
    CANCELLED = "CANCELLED", "Cancelada"


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


class AssemblyKit(AuditModel):
    """Solicitud logistica; no representa aun consumo ni genealogia de ensamble."""

    code = models.CharField("Codigo", max_length=80, unique=True)
    production_plan = models.ForeignKey(
        ProductionPlan,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="wms_kits",
        verbose_name="Plan de produccion",
    )
    serialized_unit = models.ForeignKey(
        SerializedUnit,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="wms_kits",
        verbose_name="Unidad serializada",
    )
    destination_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="destination_kits",
        verbose_name="Ubicacion de entrega",
    )
    station = models.ForeignKey(
        AssemblyStation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="wms_kits",
        verbose_name="Estacion de entrega",
    )
    status = models.CharField("Estado", max_length=20, choices=AssemblyKitStatus.choices, default=AssemblyKitStatus.DRAFT, db_index=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-created_at", "code"]
        verbose_name = "Kit de linea"
        verbose_name_plural = "Kits de linea"

    def clean(self):
        super().clean()
        if bool(self.production_plan_id) == bool(self.serialized_unit_id):
            raise ValidationError("El kit debe corresponder a un plan o a una unidad serializada, pero no a ambos.")
        if self.serialized_unit_id and self.serialized_unit.production_plan_id and self.production_plan_id:
            raise ValidationError("Un kit por unidad no requiere plan de produccion adicional.")
        if self.station_id:
            expected_line_id = self.production_plan.line_id if self.production_plan_id else self.serialized_unit.production_plan.line_id if self.serialized_unit_id and self.serialized_unit.production_plan_id else None
            if expected_line_id and self.station.line_id != expected_line_id:
                raise ValidationError({"station": "La estacion no pertenece a la linea del plan o unidad."})
        profile = WmsLocationProfile.objects.filter(location_id=self.destination_location_id, is_active=True).first()
        if not profile or profile.operational_type not in {LocationOperationalType.SUPERMARKET, LocationOperationalType.LINE_SIDE}:
            raise ValidationError({"destination_location": "El kit debe entregarse a una ubicacion WMS de supermercado o line side."})

    @property
    def picked_quantity(self):
        return sum((line.picked_quantity for line in self.lines.all()), Decimal("0"))

    def __str__(self):
        return self.code


class AssemblyKitLine(AuditModel):
    kit = models.ForeignKey(AssemblyKit, on_delete=models.CASCADE, related_name="lines", verbose_name="Kit")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="kit_lines", verbose_name="Material")
    required_quantity = models.DecimalField("Cantidad requerida", max_digits=14, decimal_places=4)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["kit", "id"]
        constraints = [models.UniqueConstraint(fields=["kit", "material"], name="wms_kit_line_material_uq")]
        verbose_name = "Linea de kit"
        verbose_name_plural = "Lineas de kit"

    def clean(self):
        super().clean()
        if self.required_quantity <= 0:
            raise ValidationError({"required_quantity": "La cantidad requerida debe ser mayor a cero."})

    @property
    def picked_quantity(self):
        return sum((task.quantity for task in self.pick_tasks.filter(status=PickTaskStatus.PICKED)), Decimal("0"))

    @property
    def remaining_quantity(self):
        return max(self.required_quantity - self.picked_quantity, Decimal("0"))

    def __str__(self):
        return f"{self.kit.code} / {self.material.code}"


class ReplenishmentRule(AuditModel):
    code = models.CharField("Codigo", max_length=80, unique=True)
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="replenishment_rules", verbose_name="Material")
    source_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="replenishment_sources", verbose_name="Ubicacion origen")
    destination_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="replenishment_destinations", verbose_name="Ubicacion a reponer")
    minimum_quantity = models.DecimalField("Minimo", max_digits=14, decimal_places=4)
    maximum_quantity = models.DecimalField("Maximo", max_digits=14, decimal_places=4)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Regla de reposicion"
        verbose_name_plural = "Reglas de reposicion"

    def clean(self):
        super().clean()
        if self.minimum_quantity < 0 or self.maximum_quantity <= 0 or self.minimum_quantity > self.maximum_quantity:
            raise ValidationError("Define minimos y maximos validos.")
        if self.source_location_id == self.destination_location_id:
            raise ValidationError({"destination_location": "El origen y destino de reposicion deben ser distintos."})
        profile = WmsLocationProfile.objects.filter(location_id=self.destination_location_id, is_active=True).first()
        if not profile or profile.operational_type not in {LocationOperationalType.SUPERMARKET, LocationOperationalType.LINE_SIDE}:
            raise ValidationError({"destination_location": "La reposicion solo se configura para supermercado o line side."})

    def __str__(self):
        return f"{self.code} / {self.material.code}"


class KanbanSignal(AuditModel):
    code = models.CharField("Codigo", max_length=80, unique=True)
    rule = models.ForeignKey(ReplenishmentRule, on_delete=models.PROTECT, related_name="signals", verbose_name="Regla")
    requested_quantity = models.DecimalField("Cantidad solicitada", max_digits=14, decimal_places=4)
    status = models.CharField("Estado", max_length=20, choices=KanbanSignalStatus.choices, default=KanbanSignalStatus.OPEN, db_index=True)
    pick_mission = models.OneToOneField(
        "PickMission", null=True, blank=True, on_delete=models.SET_NULL, related_name="kanban_signal", verbose_name="Mision de picking"
    )
    reason = models.CharField("Motivo", max_length=240, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Senal Kanban"
        verbose_name_plural = "Senales Kanban"

    def clean(self):
        super().clean()
        if self.requested_quantity <= 0:
            raise ValidationError({"requested_quantity": "La cantidad solicitada debe ser mayor a cero."})

    def __str__(self):
        return self.code


class PickMission(AuditModel):
    code = models.CharField("Codigo", max_length=80, unique=True)
    kit = models.ForeignKey(AssemblyKit, null=True, blank=True, on_delete=models.PROTECT, related_name="pick_missions", verbose_name="Kit")
    source_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="pick_missions_from", verbose_name="Ubicacion origen")
    destination_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="pick_missions_to", verbose_name="Ubicacion destino")
    status = models.CharField("Estado", max_length=20, choices=PickMissionStatus.choices, default=PickMissionStatus.DRAFT, db_index=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-created_at", "code"]
        verbose_name = "Mision de picking"
        verbose_name_plural = "Misiones de picking"

    def clean(self):
        super().clean()
        if self.source_location_id == self.destination_location_id:
            raise ValidationError({"destination_location": "El origen y destino de picking deben ser distintos."})
        if self.kit_id and self.destination_location_id != self.kit.destination_location_id:
            raise ValidationError({"destination_location": "La mision del kit debe entregar en su ubicacion definida."})

    def __str__(self):
        return self.code


class PickTask(AuditModel):
    mission = models.ForeignKey(PickMission, on_delete=models.CASCADE, related_name="tasks", verbose_name="Mision")
    kit_line = models.ForeignKey(AssemblyKitLine, null=True, blank=True, on_delete=models.PROTECT, related_name="pick_tasks", verbose_name="Linea de kit")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="pick_tasks", verbose_name="Material")
    quantity = models.DecimalField("Cantidad", max_digits=14, decimal_places=4)
    lot = models.ForeignKey(MaterialLot, null=True, blank=True, on_delete=models.PROTECT, related_name="pick_tasks", verbose_name="Lote")
    serial = models.ForeignKey(MaterialSerial, null=True, blank=True, on_delete=models.PROTECT, related_name="pick_tasks", verbose_name="Serie")
    status = models.CharField("Estado", max_length=20, choices=PickTaskStatus.choices, default=PickTaskStatus.PENDING, db_index=True)
    picked_at = models.DateTimeField("Fecha de recogida", null=True, blank=True)

    class Meta:
        ordering = ["mission", "id"]
        verbose_name = "Tarea de picking"
        verbose_name_plural = "Tareas de picking"

    def clean(self):
        super().clean()
        if self.quantity <= 0:
            raise ValidationError({"quantity": "La cantidad debe ser mayor a cero."})
        if self.kit_line_id:
            if self.mission.kit_id != self.kit_line.kit_id:
                raise ValidationError({"kit_line": "La linea de kit no pertenece a la mision."})
            if self.material_id != self.kit_line.material_id:
                raise ValidationError({"material": "El material debe coincidir con la linea de kit."})
        if self.lot_id and self.lot.material_id != self.material_id:
            raise ValidationError({"lot": "El lote no pertenece al material."})
        if self.serial_id:
            if self.serial.material_id != self.material_id:
                raise ValidationError({"serial": "La serie no pertenece al material."})
            if self.quantity != Decimal("1"):
                raise ValidationError({"quantity": "Una serie se recoge individualmente."})
        if self.material_id and self.material.traceability == MaterialTraceability.SERIAL and not self.serial_id:
            raise ValidationError({"serial": "El material trazado por serie requiere una serie identificada."})

    def __str__(self):
        return f"{self.mission.code} / {self.material.code}"


class PokaYokeAttemptResult(models.TextChoices):
    ACCEPTED = "ACCEPTED", "Aceptado"
    REJECTED = "REJECTED", "Rechazado"


class AssemblyMaterialConsumption(AuditModel):
    """Evento canonico que une as-built MES y consumo fisico WMS."""

    event_code = models.CharField("Codigo de evento", max_length=120, unique=True)
    installed_component = models.OneToOneField(
        "assembly.InstalledComponent",
        on_delete=models.PROTECT,
        related_name="wms_consumption",
        verbose_name="Componente instalado",
    )
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="assembly_consumptions", verbose_name="Material")
    source_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="assembly_consumptions",
        verbose_name="Ubicacion de consumo",
    )
    lot = models.ForeignKey(MaterialLot, null=True, blank=True, on_delete=models.PROTECT, related_name="assembly_consumptions", verbose_name="Lote")
    serial = models.ForeignKey(MaterialSerial, null=True, blank=True, on_delete=models.PROTECT, related_name="assembly_consumptions", verbose_name="Serie")
    inventory_movement = models.OneToOneField(
        InventoryMovement,
        on_delete=models.PROTECT,
        related_name="assembly_consumption",
        verbose_name="Movimiento de inventario",
    )
    consumed_at = models.DateTimeField("Fecha/hora de consumo", default=timezone.now, db_index=True)
    metadata = models.JSONField("Datos de integracion", default=dict, blank=True)

    class Meta:
        ordering = ["-consumed_at", "-id"]
        verbose_name = "Consumo de material de ensamble"
        verbose_name_plural = "Consumos de material de ensamble"
        indexes = [
            models.Index(fields=["material", "consumed_at"], name="wms_consume_material_time_idx"),
            models.Index(fields=["source_location", "consumed_at"], name="wms_consume_location_time_idx"),
        ]

    def clean(self):
        super().clean()
        if self.installed_component_id and self.material_id and self.installed_component.part_code != self.material.code:
            raise ValidationError({"material": "El material no coincide con el componente instalado."})
        if self.lot_id and self.lot.material_id != self.material_id:
            raise ValidationError({"lot": "El lote no pertenece al material."})
        if self.serial_id:
            if self.serial.material_id != self.material_id:
                raise ValidationError({"serial": "La serie no pertenece al material."})
            if self.installed_component_id and self.installed_component.serial_number != self.serial.number:
                raise ValidationError({"serial": "La serie no coincide con la genealogia instalada."})
        if self.installed_component_id and self.inventory_movement_id:
            if self.inventory_movement.material_id != self.material_id:
                raise ValidationError({"inventory_movement": "El movimiento no corresponde al material."})
            if self.inventory_movement.quantity != self.installed_component.quantity:
                raise ValidationError({"inventory_movement": "La cantidad consumida no coincide con la cantidad instalada."})

    def __str__(self):
        return self.event_code


class PokaYokeAttempt(AuditModel):
    external_reference = models.CharField("Referencia de escaneo", max_length=120, unique=True)
    unit = models.ForeignKey(
        "assembly.SerializedUnit",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="poka_yoke_attempts",
        verbose_name="Unidad",
    )
    station = models.ForeignKey(
        "assembly.AssemblyStation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="poka_yoke_attempts",
        verbose_name="Estacion",
    )
    requirement = models.ForeignKey(
        "assembly.RouteStepComponentRequirement",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="poka_yoke_attempts",
        verbose_name="Requerimiento",
    )
    scanned_material_code = models.CharField("Material escaneado", max_length=80)
    scanned_lot_number = models.CharField("Lote escaneado", max_length=120, blank=True)
    scanned_serial_number = models.CharField("Serie escaneada", max_length=120, blank=True)
    quantity = models.DecimalField("Cantidad", max_digits=14, decimal_places=4, default=Decimal("1"))
    result = models.CharField("Resultado", max_length=20, choices=PokaYokeAttemptResult.choices, db_index=True)
    reason = models.CharField("Motivo", max_length=240, blank=True)
    consumption = models.OneToOneField(
        AssemblyMaterialConsumption,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="poka_yoke_attempt",
        verbose_name="Consumo generado",
    )
    attempted_at = models.DateTimeField("Fecha/hora de intento", default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-attempted_at", "-id"]
        verbose_name = "Intento de poka-yoke"
        verbose_name_plural = "Intentos de poka-yoke"
        indexes = [
            models.Index(fields=["result", "attempted_at"], name="wms_poka_result_time_idx"),
            models.Index(fields=["unit", "attempted_at"], name="wms_poka_unit_time_idx"),
        ]

    def clean(self):
        super().clean()
        if self.quantity <= 0:
            raise ValidationError({"quantity": "La cantidad debe ser mayor a cero."})
        if self.result == PokaYokeAttemptResult.ACCEPTED and not self.consumption_id:
            raise ValidationError({"consumption": "Un intento aceptado debe tener consumo asociado."})
        if self.result == PokaYokeAttemptResult.REJECTED and self.consumption_id:
            raise ValidationError({"consumption": "Un intento rechazado no puede consumir inventario."})

    def __str__(self):
        return self.external_reference
