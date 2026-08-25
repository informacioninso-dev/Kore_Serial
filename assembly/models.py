from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import ApprovalStatus, ApprovableModel, AuditModel


class UnitStatus(models.TextChoices):
    REGISTERED = "REGISTERED", "Registrada"
    IN_PROCESS = "IN_PROCESS", "En proceso"
    QUALITY_HOLD = "QUALITY_HOLD", "En control de calidad"
    REWORK = "REWORK", "Retrabajo"
    COMPLETED = "COMPLETED", "Completada"
    RELEASED = "RELEASED", "Liberada"
    ARCHIVED = "ARCHIVED", "Archivada"


class StationEventType(models.TextChoices):
    ARRIVED = "ARRIVED", "Ingreso a estacion"
    STARTED = "STARTED", "Inicio"
    PAUSED = "PAUSED", "Pausa"
    RESUMED = "RESUMED", "Reinicio"
    COMPLETED = "COMPLETED", "Completado"
    FAILED = "FAILED", "Fallo"
    REWORK_OUT = "REWORK_OUT", "Salida a retrabajo"
    REWORK_IN = "REWORK_IN", "Reingreso de retrabajo"


class StationEventSource(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    API = "API", "API"
    EQUIPMENT = "EQUIPMENT", "Equipo"
    OFFLINE = "OFFLINE", "Offline"


class EquipmentInboundEventStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Recibido"
    PROCESSED = "PROCESSED", "Procesado"
    REJECTED = "REJECTED", "Rechazado"


class QualityGateStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    PASSED = "PASSED", "Aprobado"
    FAILED = "FAILED", "Fallido"
    WAIVED = "WAIVED", "Excepcion aprobada"


class ReworkStatus(models.TextChoices):
    OPEN = "OPEN", "Abierto"
    IN_PROGRESS = "IN_PROGRESS", "En proceso"
    QA_REVIEW = "QA_REVIEW", "Revision calidad"
    CLOSED = "CLOSED", "Cerrado"
    CANCELLED = "CANCELLED", "Cancelado"


class ProductionPlanStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    RELEASED = "RELEASED", "Liberado"
    IN_EXECUTION = "IN_EXECUTION", "En ejecucion"
    CLOSED = "CLOSED", "Cerrado"
    CANCELLED = "CANCELLED", "Cancelado"


class ProductionPlanPriority(models.TextChoices):
    LOW = "LOW", "Baja"
    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "Alta"
    URGENT = "URGENT", "Urgente"


class ProductionQueueStatus(models.TextChoices):
    QUEUED = "QUEUED", "En cola"
    READY = "READY", "Lista"
    IN_PROGRESS = "IN_PROGRESS", "En proceso"
    HOLD = "HOLD", "Retenida"
    COMPLETED = "COMPLETED", "Completada"
    CANCELLED = "CANCELLED", "Cancelada"


class LineBalanceStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    CALCULATED = "CALCULATED", "Calculado"
    APPROVED = "APPROVED", "Aprobado"
    ARCHIVED = "ARCHIVED", "Archivado"


class AndonSeverity(models.TextChoices):
    INFO = "INFO", "Informativa"
    WARNING = "WARNING", "Advertencia"
    CRITICAL = "CRITICAL", "Critica"


class AndonStatus(models.TextChoices):
    OPEN = "OPEN", "Abierta"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Reconocida"
    RESOLVED = "RESOLVED", "Resuelta"
    CANCELLED = "CANCELLED", "Cancelada"


class DowntimeStatus(models.TextChoices):
    OPEN = "OPEN", "Abierto"
    CLOSED = "CLOSED", "Cerrado"
    CANCELLED = "CANCELLED", "Cancelado"


class DowntimeCauseCategory(models.TextChoices):
    EQUIPMENT = "EQUIPMENT", "Equipo"
    MATERIAL = "MATERIAL", "Material"
    QUALITY = "QUALITY", "Calidad"
    CHANGEOVER = "CHANGEOVER", "Cambio de modelo"
    STAFFING = "STAFFING", "Personal"
    MAINTENANCE = "MAINTENANCE", "Mantenimiento"
    OTHER = "OTHER", "Otro"


class StationOfflineEventStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    SYNCED = "SYNCED", "Sincronizado"
    REJECTED = "REJECTED", "Rechazado"


class ModelMixPlanStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    ACTIVE = "ACTIVE", "Activo"
    CLOSED = "CLOSED", "Cerrado"
    CANCELLED = "CANCELLED", "Cancelado"


class ExternalMaterialKitStatus(models.TextChoices):
    PLANNED = "PLANNED", "Planificado"
    RECEIVED = "RECEIVED", "Recibido"
    CONSUMED = "CONSUMED", "Consumido"
    HOLD = "HOLD", "Retenido"
    CANCELLED = "CANCELLED", "Cancelado"


class ReleaseDecision(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    APPROVED = "APPROVED", "Liberada"
    REJECTED = "REJECTED", "Rechazada"


class ComponentTraceability(models.TextChoices):
    SERIAL = "SERIAL", "Serial obligatorio"
    LOT = "LOT", "Lote obligatorio"
    SERIAL_OR_LOT = "SERIAL_OR_LOT", "Serial o lote"
    SERIAL_AND_LOT = "SERIAL_AND_LOT", "Serial y lote"


class ProductionOrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    RELEASED = "RELEASED", "Liberada"
    IN_EXECUTION = "IN_EXECUTION", "En ejecucion"
    COMPLETED = "COMPLETED", "Completada"
    CLOSED = "CLOSED", "Cerrada"
    CANCELLED = "CANCELLED", "Cancelada"


class ProductiveParameterType(models.TextChoices):
    NUMERIC = "NUMERIC", "Numerico"
    TEXT = "TEXT", "Texto"
    BOOLEAN = "BOOLEAN", "Si/No"
    CHOICE = "CHOICE", "Lista"


class ProductiveParameterOrigin(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    PLC = "PLC", "PLC"
    MACHINE = "MACHINE", "Maquina"
    API = "API", "API"
    OPC_UA = "OPC_UA", "OPC UA"
    MQTT = "MQTT", "MQTT"
    SENSOR = "SENSOR", "Sensor"


class MeasurementResult(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    PASS = "PASS", "Aprobado"
    FAIL = "FAIL", "Fuera de rango"
    NOT_APPLICABLE = "NOT_APPLICABLE", "No aplica"


class QualityDefectSeverity(models.TextChoices):
    MINOR = "MINOR", "Menor"
    MAJOR = "MAJOR", "Mayor"
    CRITICAL = "CRITICAL", "Critica"


class QualityDefectClassification(models.TextChoices):
    PROCESS = "PROCESS", "Proceso"
    MATERIAL = "MATERIAL", "Material"
    EQUIPMENT = "EQUIPMENT", "Equipo"
    DOCUMENTATION = "DOCUMENTATION", "Documentacion"
    SAFETY = "SAFETY", "Seguridad"
    OTHER = "OTHER", "Otro"


class AssembledProduct(AuditModel):
    code = models.CharField("Codigo", max_length=50, unique=True)
    name = models.CharField("Nombre", max_length=180)
    description = models.TextField("Descripcion", blank=True)
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Producto ensamblado"
        verbose_name_plural = "Productos ensamblados"

    def __str__(self):
        return f"{self.code} - {self.name}"


class ProductVersion(AuditModel):
    product = models.ForeignKey(
        AssembledProduct,
        on_delete=models.PROTECT,
        related_name="versions",
        verbose_name="Producto ensamblado",
    )
    code = models.CharField("Codigo de version", max_length=50)
    name = models.CharField("Nombre", max_length=180)
    description = models.TextField("Descripcion", blank=True)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["product__code", "code"]
        verbose_name = "Version de producto"
        verbose_name_plural = "Versiones de producto"
        constraints = [
            models.UniqueConstraint(fields=["product", "code"], name="assembly_version_product_code_uniq"),
        ]

    def __str__(self):
        return f"{self.product.code} - {self.code}"


class Plant(AuditModel):
    code = models.CharField("Codigo", max_length=50, unique=True)
    name = models.CharField("Nombre", max_length=180)
    description = models.TextField("Descripcion", blank=True)
    address = models.CharField("Direccion", max_length=240, blank=True)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Planta"
        verbose_name_plural = "Plantas"

    def __str__(self):
        return f"{self.code} - {self.name}"


class PlantArea(AuditModel):
    plant = models.ForeignKey(
        Plant,
        on_delete=models.PROTECT,
        related_name="areas",
        verbose_name="Planta",
    )
    code = models.CharField("Codigo", max_length=50)
    name = models.CharField("Nombre", max_length=180)
    description = models.TextField("Descripcion", blank=True)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["plant__code", "code"]
        verbose_name = "Area de planta"
        verbose_name_plural = "Areas de planta"
        constraints = [
            models.UniqueConstraint(fields=["plant", "code"], name="plant_area_plant_code_uq"),
        ]

    def __str__(self):
        return f"{self.plant.code} / {self.code} - {self.name}"


class ProductionOrder(AuditModel):
    code = models.CharField("OP", max_length=80, unique=True)
    product = models.ForeignKey(
        AssembledProduct,
        on_delete=models.PROTECT,
        related_name="production_orders",
        verbose_name="Producto",
    )
    version = models.ForeignKey(
        ProductVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="production_orders",
        verbose_name="Version",
    )
    plant = models.ForeignKey(
        Plant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="production_orders",
        verbose_name="Planta",
    )
    target_quantity = models.PositiveIntegerField("Cantidad objetivo")
    due_date = models.DateField("Fecha requerida", null=True, blank=True, db_index=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=ProductionOrderStatus.choices,
        default=ProductionOrderStatus.DRAFT,
        db_index=True,
    )
    priority = models.CharField(
        "Prioridad",
        max_length=20,
        choices=ProductionPlanPriority.choices,
        default=ProductionPlanPriority.NORMAL,
        db_index=True,
    )
    external_reference = models.CharField("Referencia externa", max_length=120, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["due_date", "priority", "code"]
        verbose_name = "Orden de produccion"
        verbose_name_plural = "Ordenes de produccion"
        indexes = [
            models.Index(fields=["status", "due_date"], name="prod_order_status_due_idx"),
            models.Index(fields=["product", "status"], name="prod_order_product_status_idx"),
        ]

    def __str__(self):
        return f"{self.code} / {self.product.code}"

    def clean(self):
        super().clean()
        if self.target_quantity < 1:
            raise ValidationError({"target_quantity": "La cantidad objetivo debe ser mayor a cero."})
        if self.version_id and self.version.product_id != self.product_id:
            raise ValidationError({"version": "La version no corresponde al producto seleccionado."})

    @property
    def planned_quantity(self):
        if self.pk is None:
            return 0
        return sum(plan.target_quantity for plan in self.production_plans.all())

    @property
    def linked_unit_quantity(self):
        if self.pk is None:
            return 0
        return self.units.count()

    @property
    def progress_percent(self):
        if not self.target_quantity:
            return 0
        return min(round((self.linked_unit_quantity / self.target_quantity) * 100), 100)

    def release(self, user):
        if self.status != ProductionOrderStatus.DRAFT:
            raise ValidationError("Solo una OP en borrador puede liberarse.")
        self.status = ProductionOrderStatus.RELEASED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def start(self, user):
        if self.status != ProductionOrderStatus.RELEASED:
            raise ValidationError("Solo una OP liberada puede iniciar ejecucion.")
        self.status = ProductionOrderStatus.IN_EXECUTION
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def complete(self, user):
        if self.status not in {ProductionOrderStatus.RELEASED, ProductionOrderStatus.IN_EXECUTION}:
            raise ValidationError("Solo una OP liberada o en ejecucion puede completarse.")
        self.status = ProductionOrderStatus.COMPLETED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def close(self, user):
        if self.status not in {ProductionOrderStatus.COMPLETED, ProductionOrderStatus.IN_EXECUTION}:
            raise ValidationError("Solo una OP completada o en ejecucion puede cerrarse.")
        self.status = ProductionOrderStatus.CLOSED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def cancel(self, user):
        if self.status == ProductionOrderStatus.CLOSED:
            raise ValidationError("Una OP cerrada no puede cancelarse.")
        self.status = ProductionOrderStatus.CANCELLED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])


class SerializedUnit(AuditModel):
    production_order = models.ForeignKey(
        "ProductionOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="units",
        verbose_name="Orden de produccion",
    )
    version = models.ForeignKey(
        ProductVersion,
        on_delete=models.PROTECT,
        related_name="units",
        verbose_name="Version",
    )
    production_plan = models.ForeignKey(
        "ProductionPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="units",
        verbose_name="Plan de produccion",
    )
    serial_number = models.CharField("Numero de serie", max_length=120, unique=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=UnitStatus.choices,
        default=UnitStatus.REGISTERED,
        db_index=True,
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Unidad serializada"
        verbose_name_plural = "Unidades serializadas"

    def __str__(self):
        return self.serial_number

    def active_component_requirements(self):
        return RouteStepComponentRequirement.objects.filter(
            route_step__route__version=self.version,
            route_step__route__is_active=True,
            route_step__is_active=True,
            is_active=True,
        ).select_related("route_step__route", "route_step__station")

    def component_requirement_statuses(self):
        installed_components = list(
            self.installed_components.select_related("station", "route_step", "requirement").all()
        )
        statuses = []
        for requirement in self.active_component_requirements():
            components = [
                component
                for component in installed_components
                if component.route_step_id == requirement.route_step_id and component.part_code == requirement.part_code
            ]
            installed_quantity = sum((component.quantity for component in components), Decimal("0"))
            issues = []
            if installed_quantity < requirement.quantity_required:
                issues.append(
                    f"{requirement.part_code}: cantidad requerida {requirement.quantity_required}, instalada {installed_quantity}."
                )
            for component in components:
                traceability_issue = requirement.traceability_issue_for(component.serial_number, component.lot_number)
                if traceability_issue:
                    issues.append(f"{requirement.part_code}: {traceability_issue}")
            statuses.append(
                {
                    "requirement": requirement,
                    "components": components,
                    "installed_quantity": installed_quantity,
                    "is_complete": not issues,
                    "issues": issues,
                }
            )
        return statuses

    def as_built_issues(self):
        issues = []
        for status in self.component_requirement_statuses():
            issues.extend(status["issues"])
        return issues

    @property
    def as_built_complete(self):
        return not self.as_built_issues()

    def active_parameter_requirements(self):
        return RouteStepParameter.objects.filter(
            route_step__route__version=self.version,
            route_step__route__is_active=True,
            route_step__is_active=True,
            is_active=True,
            is_required=True,
        ).select_related("route_step__route", "route_step__station")

    def measurement_issues(self):
        issues = []
        measurements = list(self.measurements.select_related("parameter", "route_step").all())
        for parameter in self.active_parameter_requirements():
            related_measurements = [
                measurement
                for measurement in measurements
                if measurement.parameter_id == parameter.pk
                or (measurement.route_step_id == parameter.route_step_id and measurement.code == parameter.code)
            ]
            if not related_measurements:
                issues.append(f"{parameter.code}: medicion obligatoria pendiente.")
                continue
            latest = sorted(related_measurements, key=lambda item: (item.measured_at, item.pk or 0), reverse=True)[0]
            if latest.result == MeasurementResult.FAIL:
                issues.append(f"{parameter.code}: ultima medicion fuera de rango.")
            elif latest.result == MeasurementResult.PENDING:
                issues.append(f"{parameter.code}: medicion sin resultado.")
        return issues


class AssemblyLine(AuditModel):
    area = models.ForeignKey(
        PlantArea,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lines",
        verbose_name="Area de planta",
    )
    code = models.CharField("Codigo", max_length=50, unique=True)
    name = models.CharField("Nombre", max_length=180)
    description = models.TextField("Descripcion", blank=True)
    takt_time_seconds = models.PositiveIntegerField("Takt objetivo (segundos)", null=True, blank=True)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Linea de produccion"
        verbose_name_plural = "Lineas de produccion"

    def __str__(self):
        return f"{self.code} - {self.name}"


class ProductionPlan(AuditModel):
    code = models.CharField("Codigo", max_length=80, unique=True)
    production_order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_plans",
        verbose_name="Orden de produccion",
    )
    version = models.ForeignKey(
        ProductVersion,
        on_delete=models.PROTECT,
        related_name="production_plans",
        verbose_name="Version",
    )
    line = models.ForeignKey(
        AssemblyLine,
        on_delete=models.PROTECT,
        related_name="production_plans",
        verbose_name="Linea",
    )
    planned_date = models.DateField("Fecha planificada", db_index=True)
    shift = models.CharField("Turno", max_length=40)
    target_quantity = models.PositiveIntegerField("Cantidad objetivo")
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=ProductionPlanStatus.choices,
        default=ProductionPlanStatus.DRAFT,
        db_index=True,
    )
    priority = models.CharField(
        "Prioridad",
        max_length=20,
        choices=ProductionPlanPriority.choices,
        default=ProductionPlanPriority.NORMAL,
        db_index=True,
    )
    planned_start_at = models.DateTimeField("Inicio planificado", null=True, blank=True)
    planned_end_at = models.DateTimeField("Fin planificado", null=True, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["planned_date", "priority", "code"]
        verbose_name = "Plan de produccion"
        verbose_name_plural = "Planes de produccion"
        indexes = [
            models.Index(fields=["status", "planned_date"], name="prod_plan_status_date_idx"),
            models.Index(fields=["line", "planned_date"], name="prod_plan_line_date_idx"),
        ]

    def __str__(self):
        return f"{self.code} / {self.version} / {self.planned_date}"

    def clean(self):
        super().clean()
        if self.target_quantity < 1:
            raise ValidationError({"target_quantity": "La cantidad objetivo debe ser mayor a cero."})
        if self.planned_start_at and self.planned_end_at and self.planned_end_at <= self.planned_start_at:
            raise ValidationError({"planned_end_at": "El fin planificado debe ser posterior al inicio."})
        if self.production_order_id:
            if self.production_order.version_id and self.production_order.version_id != self.version_id:
                raise ValidationError({"production_order": "La OP no corresponde a la version del plan."})
            if self.production_order.product_id != self.version.product_id:
                raise ValidationError({"production_order": "La OP no corresponde al producto del plan."})
            if self.production_order.plant_id and self.line.area_id and self.line.area.plant_id != self.production_order.plant_id:
                raise ValidationError({"line": "La linea no pertenece a la planta de la OP."})

    @property
    def linked_quantity(self):
        if self.pk is None:
            return 0
        return self.units.count()

    @property
    def remaining_quantity(self):
        return max(self.target_quantity - self.linked_quantity, 0)

    @property
    def progress_percent(self):
        if not self.target_quantity:
            return 0
        return min(round((self.linked_quantity / self.target_quantity) * 100), 100)

    def _ensure_open_for_unit_changes(self):
        if self.status in {ProductionPlanStatus.CLOSED, ProductionPlanStatus.CANCELLED}:
            raise ValidationError("No se pueden modificar unidades de un plan cerrado o cancelado.")

    def release(self, user):
        if self.status != ProductionPlanStatus.DRAFT:
            raise ValidationError("Solo un plan en borrador puede liberarse.")
        self.status = ProductionPlanStatus.RELEASED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def start(self, user):
        if self.status != ProductionPlanStatus.RELEASED:
            raise ValidationError("Solo un plan liberado puede iniciar ejecucion.")
        if not self.units.exists():
            raise ValidationError("Genera o vincula al menos una unidad antes de iniciar.")
        self.status = ProductionPlanStatus.IN_EXECUTION
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def close(self, user):
        if self.status not in {ProductionPlanStatus.RELEASED, ProductionPlanStatus.IN_EXECUTION}:
            raise ValidationError("Solo un plan liberado o en ejecucion puede cerrarse.")
        self.status = ProductionPlanStatus.CLOSED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def cancel(self, user):
        if self.status == ProductionPlanStatus.CLOSED:
            raise ValidationError("Un plan cerrado no puede cancelarse.")
        self.status = ProductionPlanStatus.CANCELLED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def link_unit(self, unit, user):
        self._ensure_open_for_unit_changes()
        if unit.version_id != self.version_id:
            raise ValidationError("La unidad no corresponde a la version del plan.")
        if unit.production_plan_id and unit.production_plan_id != self.pk:
            raise ValidationError("La unidad ya esta vinculada a otro plan.")
        if self.production_order_id and unit.production_order_id and unit.production_order_id != self.production_order_id:
            raise ValidationError("La unidad ya esta vinculada a otra OP.")
        unit.production_plan = self
        if self.production_order_id:
            unit.production_order = self.production_order
        unit.updated_by = user
        unit.save(update_fields=["production_plan", "production_order", "updated_by", "updated_at"])
        return unit

    def generate_serialized_units(self, user, quantity, serial_prefix=""):
        self._ensure_open_for_unit_changes()
        quantity = int(quantity)
        if quantity < 1:
            raise ValidationError("La cantidad a generar debe ser mayor a cero.")
        if quantity > self.remaining_quantity:
            raise ValidationError("La cantidad supera el saldo pendiente del plan.")

        prefix = (serial_prefix or self.code).strip()
        created_units = []
        next_index = self.linked_quantity + 1
        while len(created_units) < quantity:
            serial_number = f"{prefix}-{next_index:04d}"
            next_index += 1
            if SerializedUnit.objects.filter(serial_number=serial_number).exists():
                continue
            created_units.append(
                SerializedUnit.objects.create(
                    production_order=self.production_order,
                    version=self.version,
                    production_plan=self,
                    serial_number=serial_number,
                    status=UnitStatus.REGISTERED,
                    created_by=user,
                    updated_by=user,
                )
            )
        return created_units

    def create_queue_items(self, user):
        return ProductionQueueItem.create_from_plan(self, user)


class AssemblyStation(AuditModel):
    line = models.ForeignKey(
        AssemblyLine,
        on_delete=models.PROTECT,
        related_name="stations",
        verbose_name="Linea",
    )
    code = models.CharField("Codigo", max_length=50)
    name = models.CharField("Nombre", max_length=180)
    sequence = models.PositiveSmallIntegerField("Secuencia")
    takt_time_seconds = models.PositiveIntegerField("Takt objetivo (segundos)", null=True, blank=True)
    requires_quality_gate = models.BooleanField("Requiere control de calidad", default=False)
    equipment = models.ManyToManyField(
        "core.EquipmentIntegration",
        blank=True,
        related_name="assembly_stations",
        verbose_name="Equipos disponibles",
    )
    authorized_operators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="authorized_assembly_stations",
        verbose_name="Operarios autorizados",
    )
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["line__code", "sequence", "code"]
        verbose_name = "Estacion de trabajo"
        verbose_name_plural = "Estaciones de trabajo"
        constraints = [
            models.UniqueConstraint(fields=["line", "code"], name="asem_station_line_code_uq"),
            models.UniqueConstraint(fields=["line", "sequence"], name="asem_station_line_seq_uq"),
        ]

    def __str__(self):
        return f"{self.line.code} / {self.code} - {self.name}"

    def operator_issue_for(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return f"{self.code}: se requiere operario identificado"
        if self.authorized_operators.exists() and not self.authorized_operators.filter(pk=user.pk).exists():
            return f"{self.code}: el operario no esta autorizado para la estacion"
        for equipment in self.equipment.all():
            if not equipment.can_be_used:
                return f"{self.code}: equipo {equipment.code} no habilitado"
            issue = equipment.qualification_issue_for(user)
            if issue:
                return issue
        return ""


class AssemblyRoute(AuditModel, ApprovableModel):
    version = models.ForeignKey(
        ProductVersion,
        on_delete=models.PROTECT,
        related_name="routes",
        verbose_name="Version",
    )
    code = models.CharField("Codigo", max_length=50)
    revision = models.CharField("Revision", max_length=20, default="A")
    name = models.CharField("Nombre", max_length=180)
    description = models.TextField("Descripcion", blank=True)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["version__product__code", "version__code", "code", "revision"]
        verbose_name = "Ruta de produccion"
        verbose_name_plural = "Rutas de produccion"
        constraints = [
            models.UniqueConstraint(fields=["version", "code", "revision"], name="asem_route_ver_code_rev_uq"),
        ]

    def __str__(self):
        return f"{self.version} / {self.code}-{self.revision}"


class AssemblyRouteStep(AuditModel):
    route = models.ForeignKey(
        AssemblyRoute,
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name="Ruta",
    )
    station = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        related_name="route_steps",
        verbose_name="Estacion",
    )
    sequence = models.PositiveSmallIntegerField("Secuencia")
    name = models.CharField("Nombre", max_length=180)
    expected_duration_seconds = models.PositiveIntegerField("Duracion esperada (segundos)", default=0)
    requires_component_trace = models.BooleanField("Requiere trazabilidad de componentes", default=False)
    requires_quality_gate = models.BooleanField("Requiere control de calidad", default=False)
    instructions = models.TextField("Instrucciones", blank=True)
    safety_notes = models.TextField("Notas de seguridad", blank=True)
    acceptance_criteria = models.TextField("Criterios de aceptacion", blank=True)
    media_reference = models.CharField("Referencia visual/documento", max_length=180, blank=True)
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        ordering = ["route", "sequence"]
        verbose_name = "Paso de ruta"
        verbose_name_plural = "Pasos de ruta"
        constraints = [
            models.UniqueConstraint(fields=["route", "sequence"], name="asem_step_route_seq_uq"),
        ]

    def __str__(self):
        return f"{self.route.code} #{self.sequence} - {self.name}"


class RouteStepParameter(AuditModel):
    route_step = models.ForeignKey(
        AssemblyRouteStep,
        on_delete=models.CASCADE,
        related_name="parameters",
        verbose_name="Paso de ruta",
    )
    code = models.CharField("Codigo", max_length=80)
    name = models.CharField("Nombre", max_length=180)
    parameter_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=ProductiveParameterType.choices,
        default=ProductiveParameterType.NUMERIC,
    )
    unit = models.CharField("Unidad", max_length=30, blank=True)
    target_value = models.CharField("Valor objetivo", max_length=80, blank=True)
    min_value = models.DecimalField("Minimo", max_digits=14, decimal_places=4, null=True, blank=True)
    max_value = models.DecimalField("Maximo", max_digits=14, decimal_places=4, null=True, blank=True)
    origin = models.CharField(
        "Origen esperado",
        max_length=20,
        choices=ProductiveParameterOrigin.choices,
        default=ProductiveParameterOrigin.MANUAL,
    )
    is_required = models.BooleanField("Obligatorio", default=True)
    is_quality_critical = models.BooleanField("Critico para calidad", default=False)
    is_active = models.BooleanField("Activo", default=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["route_step__route__code", "route_step__sequence", "code"]
        verbose_name = "Parametro productivo"
        verbose_name_plural = "Parametros productivos"
        constraints = [
            models.UniqueConstraint(fields=["route_step", "code"], name="route_param_step_code_uq"),
        ]
        indexes = [
            models.Index(fields=["code"], name="route_param_code_idx"),
            models.Index(fields=["is_active"], name="route_param_active_idx"),
        ]

    def __str__(self):
        return f"{self.route_step} / {self.code}"

    def clean(self):
        super().clean()
        if self.min_value is not None and self.max_value is not None and self.max_value < self.min_value:
            raise ValidationError({"max_value": "El maximo no puede ser menor al minimo."})

    def evaluate(self, value):
        if self.parameter_type != ProductiveParameterType.NUMERIC or value is None:
            return MeasurementResult.NOT_APPLICABLE
        if self.min_value is not None and value < self.min_value:
            return MeasurementResult.FAIL
        if self.max_value is not None and value > self.max_value:
            return MeasurementResult.FAIL
        return MeasurementResult.PASS


class ProductionQueueItem(AuditModel):
    production_plan = models.ForeignKey(
        ProductionPlan,
        on_delete=models.CASCADE,
        related_name="queue_items",
        verbose_name="Plan de produccion",
    )
    unit = models.OneToOneField(
        SerializedUnit,
        on_delete=models.CASCADE,
        related_name="queue_item",
        verbose_name="Unidad",
    )
    line = models.ForeignKey(
        AssemblyLine,
        on_delete=models.PROTECT,
        related_name="queue_items",
        verbose_name="Linea",
    )
    route = models.ForeignKey(
        AssemblyRoute,
        on_delete=models.PROTECT,
        related_name="queue_items",
        verbose_name="Ruta",
    )
    sequence = models.PositiveIntegerField("Secuencia")
    priority = models.CharField(
        "Prioridad",
        max_length=20,
        choices=ProductionPlanPriority.choices,
        default=ProductionPlanPriority.NORMAL,
        db_index=True,
    )
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=ProductionQueueStatus.choices,
        default=ProductionQueueStatus.QUEUED,
        db_index=True,
    )
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["line__code", "sequence", "id"]
        verbose_name = "Item de secuencia"
        verbose_name_plural = "Items de secuencia"
        indexes = [
            models.Index(fields=["line", "sequence"], name="prod_queue_line_seq_idx"),
            models.Index(fields=["status", "priority"], name="prod_queue_status_pri_idx"),
        ]

    def __str__(self):
        return f"{self.line.code} #{self.sequence} / {self.unit.serial_number}"

    def clean(self):
        super().clean()
        if self.production_plan_id and self.unit_id:
            if self.unit.version_id != self.production_plan.version_id:
                raise ValidationError({"unit": "La unidad no corresponde a la version del plan."})
            if self.unit.production_plan_id and self.unit.production_plan_id != self.production_plan_id:
                raise ValidationError({"unit": "La unidad esta vinculada a otro plan."})
        if self.production_plan_id and self.line_id and self.production_plan.line_id != self.line_id:
            raise ValidationError({"line": "La linea debe coincidir con el plan de produccion."})
        if self.route_id and self.unit_id and self.route.version_id != self.unit.version_id:
            raise ValidationError({"route": "La ruta no corresponde a la version de la unidad."})
        if self.route_id and self.line_id and not self.route.steps.filter(station__line_id=self.line_id, is_active=True).exists():
            raise ValidationError({"route": "La ruta no tiene pasos activos para esta linea."})

    @staticmethod
    def route_for_plan(plan):
        route = AssemblyRoute.objects.filter(
            version=plan.version,
            is_active=True,
            approval_status=ApprovalStatus.APPROVED,
        ).order_by("-approved_at", "code", "revision").first()
        if route is None:
            route = AssemblyRoute.objects.filter(version=plan.version, is_active=True).order_by("code", "revision").first()
        if route is None:
            raise ValidationError("El plan no tiene una ruta activa para secuenciar.")
        return route

    @classmethod
    def create_from_plan(cls, plan, user):
        if plan.status in {ProductionPlanStatus.DRAFT, ProductionPlanStatus.CANCELLED, ProductionPlanStatus.CLOSED}:
            raise ValidationError("Solo un plan liberado o en ejecucion puede generar secuencia.")
        route = cls.route_for_plan(plan)
        units = plan.units.order_by("serial_number", "id")
        if not units.exists():
            raise ValidationError("El plan no tiene unidades para secuenciar.")

        max_sequence = cls.objects.filter(line=plan.line).aggregate(models.Max("sequence"))["sequence__max"] or 0
        created_items = []
        for unit in units:
            if cls.objects.filter(unit=unit).exists():
                continue
            max_sequence += 1
            created_items.append(
                cls.objects.create(
                    production_plan=plan,
                    unit=unit,
                    line=plan.line,
                    route=route,
                    sequence=max_sequence,
                    priority=plan.priority,
                    status=ProductionQueueStatus.QUEUED,
                    created_by=user,
                    updated_by=user,
                )
            )
        return created_items

    def next_route_step(self):
        steps = list(self.route.steps.select_related("station", "station__line").filter(is_active=True).order_by("sequence"))
        for step in steps:
            latest_event = self.unit.station_events.filter(route_step=step).order_by("-event_at", "-id").first()
            if latest_event is None:
                return step
            if latest_event.event_type != StationEventType.COMPLETED:
                return step
        return None

    @property
    def next_station(self):
        step = self.next_route_step()
        return step.station if step else None

    def resequence(self, new_sequence, user, reason=""):
        if self.status in {ProductionQueueStatus.COMPLETED, ProductionQueueStatus.CANCELLED}:
            raise ValidationError("No se puede reordenar una unidad completada o cancelada.")
        new_sequence = int(new_sequence)
        if new_sequence < 1:
            raise ValidationError("La secuencia debe ser mayor a cero.")

        movable_statuses = [
            ProductionQueueStatus.QUEUED,
            ProductionQueueStatus.READY,
            ProductionQueueStatus.IN_PROGRESS,
            ProductionQueueStatus.HOLD,
        ]
        siblings = list(
            ProductionQueueItem.objects.filter(line=self.line, status__in=movable_statuses)
            .exclude(pk=self.pk)
            .order_by("sequence", "id")
        )
        new_sequence = min(new_sequence, len(siblings) + 1)
        siblings.insert(new_sequence - 1, self)

        old_sequence = self.sequence
        now = timezone.now()
        for index, item in enumerate(siblings, start=1):
            if item.sequence != index:
                ProductionQueueItem.objects.filter(pk=item.pk).update(sequence=index, updated_by=user, updated_at=now)

        self.refresh_from_db()
        from core.audit import log_operational_event

        log_operational_event(
            module="PRODUCTION",
            action="UPDATE",
            actor=user,
            obj=self,
            document_type="Secuencia de linea",
            document_code=self.unit.serial_number,
            related_obj=self.line,
            related_code=self.line.code,
            from_status=str(old_sequence),
            to_status=str(self.sequence),
            reason=reason,
            metadata={"queue_item": self.pk, "route": self.route.code, "action": "resequence"},
        )

    def set_status(self, status, user, reason=""):
        if status not in ProductionQueueStatus.values:
            raise ValidationError("Estado de secuencia invalido.")
        previous_status = self.status
        self.status = status
        self.updated_by = user
        if reason:
            self.notes = reason
            self.save(update_fields=["status", "notes", "updated_by", "updated_at"])
        else:
            self.save(update_fields=["status", "updated_by", "updated_at"])

        from core.audit import log_operational_event

        log_operational_event(
            module="PRODUCTION",
            action="STATUS_CHANGE",
            actor=user,
            obj=self,
            document_type="Secuencia de linea",
            document_code=self.unit.serial_number,
            related_obj=self.line,
            related_code=self.line.code,
            from_status=previous_status,
            to_status=self.status,
            reason=reason,
            metadata={"queue_item": self.pk, "route": self.route.code},
        )


class LineBalanceStudy(AuditModel):
    code = models.CharField("Codigo", max_length=80, unique=True)
    line = models.ForeignKey(
        AssemblyLine,
        on_delete=models.PROTECT,
        related_name="balance_studies",
        verbose_name="Linea",
    )
    version = models.ForeignKey(
        ProductVersion,
        on_delete=models.PROTECT,
        related_name="balance_studies",
        verbose_name="Version",
    )
    route = models.ForeignKey(
        AssemblyRoute,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="balance_studies",
        verbose_name="Ruta",
    )
    production_plan = models.ForeignKey(
        ProductionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="balance_studies",
        verbose_name="Plan de produccion",
    )
    planned_units = models.PositiveIntegerField("Unidades planificadas", default=1)
    shift_duration_seconds = models.PositiveIntegerField("Duracion de turno (segundos)", default=28800)
    target_takt_seconds = models.PositiveIntegerField("Takt objetivo (segundos)", null=True, blank=True)
    actual_start_date = models.DateField("Datos reales desde", null=True, blank=True)
    actual_end_date = models.DateField("Datos reales hasta", null=True, blank=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=LineBalanceStatus.choices,
        default=LineBalanceStatus.DRAFT,
        db_index=True,
    )
    generated_at = models.DateTimeField("Fecha/hora de calculo", null=True, blank=True)
    snapshot = models.JSONField("Resultado calculado", default=dict, blank=True)
    recommendations = models.JSONField("Recomendaciones", default=list, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-generated_at", "-created_at", "code"]
        verbose_name = "Estudio de balanceo"
        verbose_name_plural = "Estudios de balanceo"
        indexes = [
            models.Index(fields=["line", "status"], name="line_balance_line_status_idx"),
            models.Index(fields=["version", "status"], name="line_balance_ver_status_idx"),
        ]

    def __str__(self):
        return f"{self.code} / {self.line.code} / {self.version.code}"

    def clean(self):
        super().clean()
        if self.planned_units < 1:
            raise ValidationError({"planned_units": "Las unidades planificadas deben ser mayores a cero."})
        if self.shift_duration_seconds < 1:
            raise ValidationError({"shift_duration_seconds": "La duracion de turno debe ser mayor a cero."})
        if self.production_plan_id:
            if self.production_plan.line_id != self.line_id:
                raise ValidationError({"production_plan": "El plan no corresponde a la linea seleccionada."})
            if self.production_plan.version_id != self.version_id:
                raise ValidationError({"production_plan": "El plan no corresponde a la version seleccionada."})
        if self.route_id and self.route.version_id != self.version_id:
            raise ValidationError({"route": "La ruta no corresponde a la version seleccionada."})
        if self.actual_start_date and self.actual_end_date and self.actual_start_date > self.actual_end_date:
            raise ValidationError({"actual_end_date": "La fecha final de datos reales debe ser posterior a la inicial."})

    def calculate(self, user=None):
        from core.audit import log_operational_event

        from .balancing import build_line_balance_snapshot

        self.full_clean()
        previous_status = self.status
        snapshot, recommendations = build_line_balance_snapshot(self)
        self.snapshot = snapshot
        self.recommendations = recommendations
        self.status = LineBalanceStatus.CALCULATED
        self.generated_at = timezone.now()
        self.updated_by = user or self.updated_by
        self.save(update_fields=["snapshot", "recommendations", "status", "generated_at", "updated_by", "updated_at"])
        log_operational_event(
            module="PRODUCTION",
            action="UPDATE",
            actor=user,
            obj=self,
            document_type="Balanceo de linea",
            document_code=self.code,
            related_obj=self.line,
            related_code=self.line.code,
            from_status=previous_status,
            to_status=self.status,
            metadata={
                "version": self.version.code,
                "route": snapshot.get("route", {}).get("code", ""),
                "bottleneck_station": snapshot.get("summary", {}).get("bottleneck_station_code", ""),
                "balance_efficiency_percent": snapshot.get("summary", {}).get("balance_efficiency_percent"),
            },
        )
        return snapshot


class ModelMixPlan(AuditModel):
    code = models.CharField("Codigo", max_length=80, unique=True)
    line = models.ForeignKey(
        AssemblyLine,
        on_delete=models.PROTECT,
        related_name="model_mix_plans",
        verbose_name="Linea",
    )
    planned_date = models.DateField("Fecha planificada", db_index=True)
    shift = models.CharField("Turno", max_length=40)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=ModelMixPlanStatus.choices,
        default=ModelMixPlanStatus.DRAFT,
        db_index=True,
    )
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["planned_date", "line__code", "shift", "code"]
        verbose_name = "Plan de mix de modelos"
        verbose_name_plural = "Planes de mix de modelos"
        indexes = [
            models.Index(fields=["line", "planned_date"], name="mix_plan_line_date_idx"),
            models.Index(fields=["status", "planned_date"], name="mix_plan_status_date_idx"),
        ]

    def __str__(self):
        return f"{self.code} / {self.line.code} / {self.planned_date}"

    @property
    def total_units(self):
        if self.pk is None:
            return 0
        return sum(item.planned_quantity for item in self.items.all())

    def activate(self, user):
        if self.status != ModelMixPlanStatus.DRAFT:
            raise ValidationError("Solo un mix en borrador puede activarse.")
        if not self.items.exists():
            raise ValidationError("Agrega al menos una version al mix antes de activarlo.")
        self._set_status(ModelMixPlanStatus.ACTIVE, user, "Mix activado para planificacion.")

    def close(self, user):
        if self.status not in {ModelMixPlanStatus.DRAFT, ModelMixPlanStatus.ACTIVE}:
            raise ValidationError("Solo un mix abierto puede cerrarse.")
        self._set_status(ModelMixPlanStatus.CLOSED, user, "Mix cerrado.")

    def cancel(self, user, reason=""):
        if self.status == ModelMixPlanStatus.CLOSED:
            raise ValidationError("Un mix cerrado no puede cancelarse.")
        self._set_status(ModelMixPlanStatus.CANCELLED, user, reason or "Mix cancelado.")

    def generate_production_plans(self, user):
        if self.status == ModelMixPlanStatus.CANCELLED:
            raise ValidationError("No se pueden generar planes desde un mix cancelado.")
        if not self.items.exists():
            raise ValidationError("Agrega al menos una version al mix.")
        created_or_updated = []
        for item in self.items.select_related("version__product"):
            plan_code = f"{self.code}-{item.version.code}"[:80]
            plan, created = ProductionPlan.objects.get_or_create(
                code=plan_code,
                defaults={
                    "version": item.version,
                    "line": self.line,
                    "planned_date": self.planned_date,
                    "shift": self.shift,
                    "target_quantity": item.planned_quantity,
                    "status": ProductionPlanStatus.RELEASED,
                    "priority": item.priority,
                    "notes": f"Generado desde mix {self.code}.",
                    "created_by": user,
                    "updated_by": user,
                },
            )
            if not created and plan.status not in {ProductionPlanStatus.CLOSED, ProductionPlanStatus.CANCELLED}:
                plan.version = item.version
                plan.line = self.line
                plan.planned_date = self.planned_date
                plan.shift = self.shift
                plan.target_quantity = item.planned_quantity
                plan.priority = item.priority
                plan.updated_by = user
                plan.save(
                    update_fields=[
                        "version",
                        "line",
                        "planned_date",
                        "shift",
                        "target_quantity",
                        "priority",
                        "updated_by",
                        "updated_at",
                    ]
                )
            item.production_plan = plan
            item.updated_by = user
            item.save(update_fields=["production_plan", "updated_by", "updated_at"])
            created_or_updated.append(plan)

        from core.audit import log_operational_event

        log_operational_event(
            module="PRODUCTION",
            action="CREATE",
            actor=user,
            obj=self,
            document_type="Mix de modelos",
            document_code=self.code,
            related_obj=self.line,
            related_code=self.line.code,
            to_status=self.status,
            metadata={"production_plans": [plan.code for plan in created_or_updated]},
        )
        return created_or_updated

    def _set_status(self, status, user, reason=""):
        previous_status = self.status
        self.status = status
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

        from core.audit import log_operational_event

        log_operational_event(
            module="PRODUCTION",
            action="STATUS_CHANGE",
            actor=user,
            obj=self,
            document_type="Mix de modelos",
            document_code=self.code,
            related_obj=self.line,
            related_code=self.line.code,
            from_status=previous_status,
            to_status=self.status,
            reason=reason,
        )


class ModelMixPlanItem(AuditModel):
    mix_plan = models.ForeignKey(
        ModelMixPlan,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Mix de modelos",
    )
    version = models.ForeignKey(
        ProductVersion,
        on_delete=models.PROTECT,
        related_name="model_mix_items",
        verbose_name="Version",
    )
    planned_quantity = models.PositiveIntegerField("Cantidad planificada")
    sequence_bias = models.PositiveSmallIntegerField("Peso de secuencia", default=1)
    priority = models.CharField(
        "Prioridad",
        max_length=20,
        choices=ProductionPlanPriority.choices,
        default=ProductionPlanPriority.NORMAL,
        db_index=True,
    )
    production_plan = models.ForeignKey(
        ProductionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="model_mix_items",
        verbose_name="Plan generado",
    )
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["mix_plan", "sequence_bias", "version__product__code", "version__code"]
        verbose_name = "Item de mix de modelos"
        verbose_name_plural = "Items de mix de modelos"
        constraints = [
            models.UniqueConstraint(fields=["mix_plan", "version"], name="mix_item_plan_version_uq"),
        ]

    def __str__(self):
        return f"{self.mix_plan.code} / {self.version.code} / {self.planned_quantity}"

    def clean(self):
        super().clean()
        if self.planned_quantity < 1:
            raise ValidationError({"planned_quantity": "La cantidad planificada debe ser mayor a cero."})
        if self.sequence_bias < 1:
            raise ValidationError({"sequence_bias": "El peso de secuencia debe ser mayor a cero."})
        if self.production_plan_id:
            if self.production_plan.version_id != self.version_id:
                raise ValidationError({"production_plan": "El plan generado no corresponde a la version del item."})
            if self.mix_plan_id and self.production_plan.line_id != self.mix_plan.line_id:
                raise ValidationError({"production_plan": "El plan generado no corresponde a la linea del mix."})


class ExternalMaterialKit(AuditModel):
    code = models.CharField("Codigo", max_length=80, unique=True)
    external_system = models.CharField("Sistema externo", max_length=50, default="B22")
    external_reference = models.CharField("Referencia externa", max_length=120, blank=True)
    version = models.ForeignKey(
        ProductVersion,
        on_delete=models.PROTECT,
        related_name="external_material_kits",
        verbose_name="Version",
    )
    production_plan = models.ForeignKey(
        ProductionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="external_material_kits",
        verbose_name="Plan de produccion",
    )
    line = models.ForeignKey(
        AssemblyLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_material_kits",
        verbose_name="Linea",
    )
    container_code = models.CharField("Contenedor", max_length=120, blank=True)
    lot_number = models.CharField("Lote", max_length=120, blank=True)
    expected_quantity = models.DecimalField("Cantidad esperada", max_digits=14, decimal_places=4, default=Decimal("1.0000"))
    received_quantity = models.DecimalField("Cantidad recibida", max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=ExternalMaterialKitStatus.choices,
        default=ExternalMaterialKitStatus.PLANNED,
        db_index=True,
    )
    received_at = models.DateTimeField("Fecha/hora recepcion", null=True, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["status", "code"]
        verbose_name = "Kit externo de material"
        verbose_name_plural = "Kits externos de material"
        indexes = [
            models.Index(fields=["status", "external_system"], name="ext_kit_status_system_idx"),
            models.Index(fields=["version", "status"], name="ext_kit_version_status_idx"),
        ]

    def __str__(self):
        return f"{self.code} / {self.version.code} / {self.get_status_display()}"

    def clean(self):
        super().clean()
        if self.expected_quantity <= Decimal("0"):
            raise ValidationError({"expected_quantity": "La cantidad esperada debe ser mayor a cero."})
        if self.received_quantity < Decimal("0"):
            raise ValidationError({"received_quantity": "La cantidad recibida no puede ser negativa."})
        if self.production_plan_id:
            if self.production_plan.version_id != self.version_id:
                raise ValidationError({"production_plan": "El plan no corresponde a la version del kit."})
            if self.line_id and self.production_plan.line_id != self.line_id:
                raise ValidationError({"line": "La linea del kit debe coincidir con el plan."})

    @property
    def receipt_percent(self):
        if not self.expected_quantity:
            return 0
        return min(round((self.received_quantity / self.expected_quantity) * 100), 100)

    def receive(self, user, quantity=None):
        previous_status = self.status
        self.received_quantity = quantity if quantity is not None else self.expected_quantity
        self.status = ExternalMaterialKitStatus.RECEIVED
        self.received_at = timezone.now()
        self.updated_by = user
        self.full_clean()
        self.save(update_fields=["received_quantity", "status", "received_at", "updated_by", "updated_at"])
        self._log_status_change(user, previous_status, "Kit recibido desde integracion o recepcion manual.")

    def consume(self, user):
        if self.status not in {ExternalMaterialKitStatus.RECEIVED, ExternalMaterialKitStatus.HOLD}:
            raise ValidationError("Solo un kit recibido o retenido puede marcarse como consumido.")
        previous_status = self.status
        self.status = ExternalMaterialKitStatus.CONSUMED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])
        self._log_status_change(user, previous_status, "Kit consumido en produccion.")

    def _log_status_change(self, user, previous_status, reason=""):
        from core.audit import log_operational_event

        log_operational_event(
            module="INVENTORY",
            action="STATUS_CHANGE",
            actor=user,
            obj=self,
            document_type="Kit externo",
            document_code=self.code,
            related_obj=self.production_plan or self.line,
            related_code=self.production_plan.code if self.production_plan_id else (self.line.code if self.line_id else ""),
            from_status=previous_status,
            to_status=self.status,
            reason=reason,
            metadata={
                "external_system": self.external_system,
                "external_reference": self.external_reference,
                "version": self.version.code,
            },
        )


class AndonSignal(AuditModel):
    code = models.CharField("Codigo", max_length=80, unique=True)
    line = models.ForeignKey(
        AssemblyLine,
        on_delete=models.PROTECT,
        related_name="andon_signals",
        verbose_name="Linea",
    )
    station = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="andon_signals",
        verbose_name="Estacion",
    )
    unit = models.ForeignKey(
        SerializedUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="andon_signals",
        verbose_name="Unidad",
    )
    production_plan = models.ForeignKey(
        ProductionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="andon_signals",
        verbose_name="Plan de produccion",
    )
    severity = models.CharField("Severidad", max_length=20, choices=AndonSeverity.choices, default=AndonSeverity.WARNING, db_index=True)
    status = models.CharField("Estado", max_length=20, choices=AndonStatus.choices, default=AndonStatus.OPEN, db_index=True)
    title = models.CharField("Titulo", max_length=160)
    description = models.TextField("Descripcion", blank=True)
    source = models.CharField("Origen", max_length=20, choices=StationEventSource.choices, default=StationEventSource.MANUAL)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="andon_signals_opened",
        verbose_name="Abierta por",
    )
    opened_at = models.DateTimeField("Fecha/hora apertura", default=timezone.now, db_index=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="andon_signals_acknowledged",
        verbose_name="Reconocida por",
    )
    acknowledged_at = models.DateTimeField("Fecha/hora reconocimiento", null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="andon_signals_resolved",
        verbose_name="Resuelta por",
    )
    resolved_at = models.DateTimeField("Fecha/hora resolucion", null=True, blank=True)
    resolution_notes = models.TextField("Notas de resolucion", blank=True)

    class Meta:
        ordering = ["status", "-severity", "-opened_at", "code"]
        verbose_name = "Senal Andon"
        verbose_name_plural = "Senales Andon"
        indexes = [
            models.Index(fields=["line", "status"], name="andon_line_status_idx"),
            models.Index(fields=["station", "status"], name="andon_station_status_idx"),
            models.Index(fields=["severity", "opened_at"], name="andon_severity_time_idx"),
        ]

    def __str__(self):
        station = self.station.code if self.station_id else self.line.code
        return f"{self.code} / {station} / {self.get_status_display()}"

    @property
    def is_open(self):
        return self.status in {AndonStatus.OPEN, AndonStatus.ACKNOWLEDGED}

    def clean(self):
        super().clean()
        if self.station_id and self.station.line_id != self.line_id:
            raise ValidationError({"station": "La estacion no corresponde a la linea seleccionada."})
        if self.production_plan_id and self.production_plan.line_id != self.line_id:
            raise ValidationError({"production_plan": "El plan no corresponde a la linea seleccionada."})
        if self.unit_id and self.production_plan_id and self.unit.production_plan_id != self.production_plan_id:
            raise ValidationError({"unit": "La unidad no esta vinculada al plan seleccionado."})
        if self.status == AndonStatus.RESOLVED and not self.resolution_notes.strip():
            raise ValidationError({"resolution_notes": "Registra notas de resolucion."})

    def acknowledge(self, user, notes=""):
        if self.status != AndonStatus.OPEN:
            raise ValidationError("Solo una senal abierta puede reconocerse.")
        previous_status = self.status
        self.status = AndonStatus.ACKNOWLEDGED
        self.acknowledged_by = user
        self.acknowledged_at = timezone.now()
        if notes:
            self.resolution_notes = notes
        self.updated_by = user
        self.save(update_fields=["status", "acknowledged_by", "acknowledged_at", "resolution_notes", "updated_by", "updated_at"])
        self._log_status_change(user, previous_status, notes)

    def resolve(self, user, notes):
        if self.status not in {AndonStatus.OPEN, AndonStatus.ACKNOWLEDGED}:
            raise ValidationError("Solo una senal abierta o reconocida puede resolverse.")
        if not notes.strip():
            raise ValidationError("Registra notas de resolucion.")
        previous_status = self.status
        self.status = AndonStatus.RESOLVED
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.resolution_notes = notes
        self.updated_by = user
        self.save(update_fields=["status", "resolved_by", "resolved_at", "resolution_notes", "updated_by", "updated_at"])
        self._log_status_change(user, previous_status, notes)

    def cancel(self, user, notes):
        if self.status in {AndonStatus.RESOLVED, AndonStatus.CANCELLED}:
            raise ValidationError("La senal ya esta cerrada.")
        if not notes.strip():
            raise ValidationError("Registra el motivo de cancelacion.")
        previous_status = self.status
        self.status = AndonStatus.CANCELLED
        self.resolution_notes = notes
        self.updated_by = user
        self.save(update_fields=["status", "resolution_notes", "updated_by", "updated_at"])
        self._log_status_change(user, previous_status, notes)

    def _log_status_change(self, user, previous_status, reason=""):
        from core.audit import log_operational_event

        log_operational_event(
            module="PRODUCTION",
            action="STATUS_CHANGE",
            actor=user,
            obj=self,
            document_type="Andon",
            document_code=self.code,
            related_obj=self.station or self.line,
            related_code=self.station.code if self.station_id else self.line.code,
            from_status=previous_status,
            to_status=self.status,
            reason=reason,
            metadata={"severity": self.severity, "source": self.source},
        )


class ProductionDowntime(AuditModel):
    code = models.CharField("Codigo", max_length=80, unique=True)
    line = models.ForeignKey(
        AssemblyLine,
        on_delete=models.PROTECT,
        related_name="downtimes",
        verbose_name="Linea",
    )
    station = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="downtimes",
        verbose_name="Estacion",
    )
    unit = models.ForeignKey(
        SerializedUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="downtimes",
        verbose_name="Unidad",
    )
    production_plan = models.ForeignKey(
        ProductionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="downtimes",
        verbose_name="Plan de produccion",
    )
    andon_signal = models.ForeignKey(
        AndonSignal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="downtimes",
        verbose_name="Senal Andon",
    )
    status = models.CharField("Estado", max_length=20, choices=DowntimeStatus.choices, default=DowntimeStatus.OPEN, db_index=True)
    cause_category = models.CharField(
        "Categoria",
        max_length=20,
        choices=DowntimeCauseCategory.choices,
        default=DowntimeCauseCategory.OTHER,
        db_index=True,
    )
    cause_code = models.CharField("Codigo de causa", max_length=80)
    cause_description = models.TextField("Descripcion de causa", blank=True)
    started_at = models.DateTimeField("Inicio", default=timezone.now, db_index=True)
    ended_at = models.DateTimeField("Fin", null=True, blank=True)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="downtimes_opened",
        verbose_name="Abierto por",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="downtimes_closed",
        verbose_name="Cerrado por",
    )
    evidence_reference = models.CharField("Evidencia", max_length=120, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["status", "-started_at", "code"]
        verbose_name = "Paro de produccion"
        verbose_name_plural = "Paros de produccion"
        indexes = [
            models.Index(fields=["line", "status"], name="downtime_line_status_idx"),
            models.Index(fields=["station", "status"], name="downtime_station_status_idx"),
            models.Index(fields=["cause_category", "started_at"], name="downtime_cause_time_idx"),
        ]

    def __str__(self):
        station = self.station.code if self.station_id else self.line.code
        return f"{self.code} / {station} / {self.get_status_display()}"

    @property
    def duration_seconds(self):
        end = self.ended_at or timezone.now()
        if end < self.started_at:
            return 0
        return round((end - self.started_at).total_seconds())

    def clean(self):
        super().clean()
        if self.station_id and self.station.line_id != self.line_id:
            raise ValidationError({"station": "La estacion no corresponde a la linea seleccionada."})
        if self.production_plan_id and self.production_plan.line_id != self.line_id:
            raise ValidationError({"production_plan": "El plan no corresponde a la linea seleccionada."})
        if self.andon_signal_id and self.andon_signal.line_id != self.line_id:
            raise ValidationError({"andon_signal": "La senal Andon no corresponde a la linea seleccionada."})
        if self.ended_at and self.ended_at <= self.started_at:
            raise ValidationError({"ended_at": "El fin del paro debe ser posterior al inicio."})
        if self.status == DowntimeStatus.CLOSED and not self.ended_at:
            raise ValidationError({"ended_at": "Un paro cerrado debe tener fecha de fin."})

    def close(self, user, notes="", evidence_reference="", ended_at=None):
        if self.status != DowntimeStatus.OPEN:
            raise ValidationError("Solo un paro abierto puede cerrarse.")
        previous_status = self.status
        self.status = DowntimeStatus.CLOSED
        self.ended_at = ended_at or timezone.now()
        self.closed_by = user
        if notes:
            self.notes = notes
        if evidence_reference:
            self.evidence_reference = evidence_reference
        self.updated_by = user
        self.full_clean()
        self.save(update_fields=["status", "ended_at", "closed_by", "notes", "evidence_reference", "updated_by", "updated_at"])
        self._log_status_change(user, previous_status, notes or "Paro cerrado.")

    def cancel(self, user, notes):
        if self.status != DowntimeStatus.OPEN:
            raise ValidationError("Solo un paro abierto puede cancelarse.")
        if not notes.strip():
            raise ValidationError("Registra el motivo de cancelacion.")
        previous_status = self.status
        self.status = DowntimeStatus.CANCELLED
        self.notes = notes
        self.updated_by = user
        self.save(update_fields=["status", "notes", "updated_by", "updated_at"])
        self._log_status_change(user, previous_status, notes)

    def _log_status_change(self, user, previous_status, reason=""):
        from core.audit import log_operational_event

        log_operational_event(
            module="PRODUCTION",
            action="STATUS_CHANGE",
            actor=user,
            obj=self,
            document_type="Paro de produccion",
            document_code=self.code,
            related_obj=self.station or self.line,
            related_code=self.station.code if self.station_id else self.line.code,
            from_status=previous_status,
            to_status=self.status,
            reason=reason,
            metadata={
                "cause_category": self.cause_category,
                "cause_code": self.cause_code,
                "duration_seconds": self.duration_seconds,
            },
        )


class StationOfflineEvent(AuditModel):
    external_id = models.CharField("Identificador externo", max_length=120, unique=True)
    station = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        related_name="offline_events",
        verbose_name="Estacion",
    )
    unit_serial_number = models.CharField("Serial de unidad", max_length=120)
    operator_username = models.CharField("Operario", max_length=150, blank=True)
    event_type = models.CharField("Tipo de evento", max_length=20, choices=StationEventType.choices)
    captured_at = models.DateTimeField("Capturado en terminal", default=timezone.now, db_index=True)
    payload = models.JSONField("Payload local", default=dict, blank=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=StationOfflineEventStatus.choices,
        default=StationOfflineEventStatus.PENDING,
        db_index=True,
    )
    result_detail = models.TextField("Resultado", blank=True)
    synced_at = models.DateTimeField("Sincronizado en", null=True, blank=True)
    station_event = models.OneToOneField(
        "UnitStationEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offline_source",
        verbose_name="Evento sincronizado",
    )
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["status", "captured_at", "external_id"]
        verbose_name = "Evento offline de estacion"
        verbose_name_plural = "Eventos offline de estacion"
        indexes = [
            models.Index(fields=["station", "status"], name="offline_station_status_idx"),
            models.Index(fields=["status", "captured_at"], name="offline_status_time_idx"),
        ]

    def __str__(self):
        return f"{self.external_id} / {self.station.code} / {self.get_status_display()}"

    def sync(self, user):
        if self.status == StationOfflineEventStatus.SYNCED and self.station_event_id:
            return self.station_event, False

        from .services import record_station_event

        try:
            station_event, created = record_station_event(
                actor=user,
                unit_serial_number=self.unit_serial_number,
                station_code=self.station.code,
                event_type=self.event_type,
                operator_username=self.operator_username,
                event_at=self.captured_at,
                external_reference=self.external_id,
                notes=self.notes,
                metadata={"offline_payload": self.payload},
                source=StationEventSource.OFFLINE,
            )
            self.station_event = station_event
            self.status = StationOfflineEventStatus.SYNCED
            self.result_detail = "Evento sincronizado."
            self.synced_at = timezone.now()
            self.updated_by = user
            self.save(update_fields=["station_event", "status", "result_detail", "synced_at", "updated_by", "updated_at"])
            return station_event, created
        except ValueError as error:
            self.status = StationOfflineEventStatus.REJECTED
            self.result_detail = str(error)
            self.synced_at = timezone.now()
            self.updated_by = user
            self.save(update_fields=["status", "result_detail", "synced_at", "updated_by", "updated_at"])
            raise ValidationError(str(error))


class RouteStepComponentRequirement(AuditModel):
    route_step = models.ForeignKey(
        AssemblyRouteStep,
        on_delete=models.CASCADE,
        related_name="component_requirements",
        verbose_name="Paso de ruta",
    )
    part_code = models.CharField("Codigo de parte", max_length=80)
    part_name = models.CharField("Nombre de parte", max_length=180, blank=True)
    quantity_required = models.DecimalField("Cantidad requerida", max_digits=14, decimal_places=4, default=Decimal("1.0000"))
    traceability = models.CharField(
        "Trazabilidad requerida",
        max_length=20,
        choices=ComponentTraceability.choices,
        default=ComponentTraceability.SERIAL_OR_LOT,
    )
    is_critical = models.BooleanField("Critico", default=False)
    is_active = models.BooleanField("Activo", default=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["route_step__route__code", "route_step__sequence", "part_code"]
        verbose_name = "Componente requerido por paso"
        verbose_name_plural = "Componentes requeridos por paso"
        constraints = [
            models.UniqueConstraint(fields=["route_step", "part_code"], name="asem_req_step_part_uq"),
        ]
        indexes = [
            models.Index(fields=["part_code"], name="asem_req_part_code_idx"),
            models.Index(fields=["is_active"], name="asem_req_active_idx"),
        ]

    def __str__(self):
        return f"{self.route_step} / {self.part_code}"

    def clean(self):
        super().clean()
        if self.quantity_required <= Decimal("0"):
            raise ValidationError({"quantity_required": "La cantidad requerida debe ser mayor a cero."})

    def traceability_issue_for(self, serial_number, lot_number):
        has_serial = bool(serial_number)
        has_lot = bool(lot_number)
        if self.traceability == ComponentTraceability.SERIAL and not has_serial:
            return "requiere numero de serie."
        if self.traceability == ComponentTraceability.LOT and not has_lot:
            return "requiere numero de lote."
        if self.traceability == ComponentTraceability.SERIAL_OR_LOT and not (has_serial or has_lot):
            return "requiere numero de serie o lote."
        if self.traceability == ComponentTraceability.SERIAL_AND_LOT and not (has_serial and has_lot):
            return "requiere numero de serie y lote."
        return ""

    def validate_installed_component(self, component):
        errors = {}
        if component.part_code and component.part_code != self.part_code:
            errors["part_code"] = "El codigo de parte no coincide con el requerimiento."
        if component.route_step_id and component.route_step_id != self.route_step_id:
            errors["route_step"] = "El paso de ruta no coincide con el requerimiento."
        if component.station_id and component.station_id != self.route_step.station_id:
            errors["station"] = "La estacion no coincide con el paso requerido."
        if component.unit_id and component.unit.version_id != self.route_step.route.version_id:
            errors["unit"] = "La version de la unidad no corresponde a la ruta del requerimiento."
        traceability_issue = self.traceability_issue_for(component.serial_number, component.lot_number)
        if traceability_issue:
            errors["serial_number"] = f"El componente {traceability_issue}"
        if errors:
            raise ValidationError(errors)


class UnitStationEvent(AuditModel):
    unit = models.ForeignKey(
        SerializedUnit,
        on_delete=models.CASCADE,
        related_name="station_events",
        verbose_name="Unidad",
    )
    station = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        related_name="unit_events",
        verbose_name="Estacion",
    )
    route_step = models.ForeignKey(
        AssemblyRouteStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="unit_events",
        verbose_name="Paso de ruta",
    )
    event_type = models.CharField("Tipo de evento", max_length=20, choices=StationEventType.choices)
    event_at = models.DateTimeField("Fecha/hora del evento", default=timezone.now, db_index=True)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assembly_station_events",
        verbose_name="Operario",
    )
    source = models.CharField("Origen", max_length=20, choices=StationEventSource.choices, default=StationEventSource.MANUAL)
    external_reference = models.CharField("Referencia externa", max_length=120, blank=True)
    notes = models.TextField("Notas", blank=True)
    metadata = models.JSONField("Datos de soporte", default=dict, blank=True)

    class Meta:
        ordering = ["-event_at", "-id"]
        verbose_name = "Evento de estacion"
        verbose_name_plural = "Eventos de estacion"
        indexes = [
            models.Index(fields=["unit", "event_at"], name="unit_event_unit_time_idx"),
            models.Index(fields=["station", "event_at"], name="unit_event_station_time_idx"),
            models.Index(fields=["event_type", "event_at"], name="unit_event_type_time_idx"),
        ]

    def __str__(self):
        return f"{self.unit.serial_number} / {self.station.code} / {self.get_event_type_display()}"

    def clean(self):
        super().clean()
        if self.route_step_id and self.station_id and self.route_step.station_id != self.station_id:
            raise ValidationError({"route_step": "El paso de ruta no pertenece a la estacion seleccionada."})
        if self.route_step_id and self.unit_id and self.route_step.route.version_id != self.unit.version_id:
            raise ValidationError({"route_step": "La ruta del paso no corresponde a la version de la unidad."})


class ProductionMeasurement(AuditModel):
    unit = models.ForeignKey(
        SerializedUnit,
        on_delete=models.CASCADE,
        related_name="measurements",
        verbose_name="Unidad",
    )
    station = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        related_name="measurements",
        verbose_name="Estacion",
    )
    route_step = models.ForeignKey(
        AssemblyRouteStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="measurements",
        verbose_name="Paso de ruta",
    )
    parameter = models.ForeignKey(
        RouteStepParameter,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="measurements",
        verbose_name="Parametro",
    )
    station_event = models.ForeignKey(
        UnitStationEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="measurements",
        verbose_name="Evento de estacion",
    )
    code = models.CharField("Codigo", max_length=80)
    name = models.CharField("Nombre", max_length=180)
    value = models.DecimalField("Valor numerico", max_digits=14, decimal_places=4, null=True, blank=True)
    text_value = models.CharField("Valor texto", max_length=180, blank=True)
    unit_label = models.CharField("Unidad", max_length=30, blank=True)
    min_value = models.DecimalField("Minimo", max_digits=14, decimal_places=4, null=True, blank=True)
    max_value = models.DecimalField("Maximo", max_digits=14, decimal_places=4, null=True, blank=True)
    result = models.CharField(
        "Resultado",
        max_length=20,
        choices=MeasurementResult.choices,
        default=MeasurementResult.PENDING,
        db_index=True,
    )
    origin = models.CharField(
        "Origen",
        max_length=20,
        choices=ProductiveParameterOrigin.choices,
        default=ProductiveParameterOrigin.MANUAL,
    )
    measured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assembly_measurements",
        verbose_name="Medido por",
    )
    measured_at = models.DateTimeField("Fecha/hora medicion", default=timezone.now, db_index=True)
    evidence_reference = models.CharField("Evidencia", max_length=120, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-measured_at", "-id"]
        verbose_name = "Medicion productiva"
        verbose_name_plural = "Mediciones productivas"
        indexes = [
            models.Index(fields=["unit", "measured_at"], name="measurement_unit_time_idx"),
            models.Index(fields=["station", "result"], name="measurement_station_result_idx"),
            models.Index(fields=["code", "measured_at"], name="measurement_code_time_idx"),
        ]

    def __str__(self):
        return f"{self.unit.serial_number} / {self.code} / {self.get_result_display()}"

    @property
    def display_value(self):
        if self.value is not None:
            if self.unit_label:
                return f"{self.value} {self.unit_label}"
            return str(self.value)
        return self.text_value or "-"

    @property
    def display_range(self):
        minimum = self.min_value if self.min_value is not None else "-"
        maximum = self.max_value if self.max_value is not None else "-"
        if minimum == "-" and maximum == "-":
            return "-"
        return f"Min {minimum} / Max {maximum}"

    def clean(self):
        super().clean()
        if self.route_step_id and self.station_id and self.route_step.station_id != self.station_id:
            raise ValidationError({"route_step": "El paso de ruta no pertenece a la estacion seleccionada."})
        if self.route_step_id and self.unit_id and self.route_step.route.version_id != self.unit.version_id:
            raise ValidationError({"route_step": "La ruta del paso no corresponde a la version de la unidad."})
        if self.parameter_id:
            if self.route_step_id and self.parameter.route_step_id != self.route_step_id:
                raise ValidationError({"parameter": "El parametro no pertenece al paso de ruta seleccionado."})
            if self.station_id and self.parameter.route_step.station_id != self.station_id:
                raise ValidationError({"parameter": "El parametro no corresponde a la estacion seleccionada."})
        if self.min_value is not None and self.max_value is not None and self.max_value < self.min_value:
            raise ValidationError({"max_value": "El maximo no puede ser menor al minimo."})

    def apply_parameter_defaults(self):
        if not self.parameter_id:
            return
        self.route_step = self.parameter.route_step
        self.station = self.parameter.route_step.station
        self.code = self.parameter.code
        self.name = self.parameter.name
        self.unit_label = self.parameter.unit
        self.min_value = self.parameter.min_value
        self.max_value = self.parameter.max_value
        self.origin = self.parameter.origin

    def evaluate_result(self):
        if self.value is None:
            self.result = MeasurementResult.NOT_APPLICABLE if self.text_value else MeasurementResult.PENDING
            return self.result
        if self.min_value is not None and self.value < self.min_value:
            self.result = MeasurementResult.FAIL
            return self.result
        if self.max_value is not None and self.value > self.max_value:
            self.result = MeasurementResult.FAIL
            return self.result
        self.result = MeasurementResult.PASS
        return self.result

    def save(self, *args, **kwargs):
        self.apply_parameter_defaults()
        self.evaluate_result()
        super().save(*args, **kwargs)


class EquipmentInboundEvent(AuditModel):
    """Mensaje recibido desde un recolector externo, procesado una sola vez."""

    external_id = models.CharField("Identificador externo", max_length=120, unique=True)
    equipment_code = models.CharField("Codigo de equipo recibido", max_length=50)
    station_code = models.CharField("Codigo de estacion recibido", max_length=50, blank=True)
    unit_serial_number = models.CharField("Serie de unidad recibida", max_length=120)
    operator_username = models.CharField("Operario recibido", max_length=150)
    event_type = models.CharField("Tipo de evento", max_length=20, choices=StationEventType.choices)
    event_at = models.DateTimeField("Fecha/hora informada", default=timezone.now, db_index=True)
    received_at = models.DateTimeField("Fecha/hora de recepcion", auto_now_add=True)
    payload = models.JSONField("Carga original", default=dict, blank=True)
    status = models.CharField(
        "Estado de procesamiento",
        max_length=20,
        choices=EquipmentInboundEventStatus.choices,
        default=EquipmentInboundEventStatus.RECEIVED,
        db_index=True,
    )
    result_detail = models.TextField("Detalle de resultado", blank=True)
    processed_at = models.DateTimeField("Fecha/hora de procesamiento", null=True, blank=True)
    equipment = models.ForeignKey(
        "core.EquipmentIntegration",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inbound_assembly_events",
        verbose_name="Equipo resuelto",
    )
    station = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inbound_equipment_events",
        verbose_name="Estacion resuelta",
    )
    unit = models.ForeignKey(
        SerializedUnit,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inbound_equipment_events",
        verbose_name="Unidad resuelta",
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_assembly_events",
        verbose_name="Operario resuelto",
    )
    station_event = models.OneToOneField(
        UnitStationEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_equipment_event",
        verbose_name="Evento de estacion creado",
    )

    class Meta:
        ordering = ["-received_at", "-id"]
        verbose_name = "Evento recibido de equipo"
        verbose_name_plural = "Eventos recibidos de equipos"
        indexes = [
            models.Index(fields=["status", "received_at"], name="equip_inbound_status_time_idx"),
            models.Index(fields=["equipment_code", "event_at"], name="equip_inbound_code_time_idx"),
        ]

    def __str__(self):
        return f"{self.external_id} / {self.equipment_code} / {self.get_status_display()}"


class InstalledComponent(AuditModel):
    unit = models.ForeignKey(
        SerializedUnit,
        on_delete=models.CASCADE,
        related_name="installed_components",
        verbose_name="Unidad",
    )
    station = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="installed_components",
        verbose_name="Estacion",
    )
    route_step = models.ForeignKey(
        AssemblyRouteStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="installed_components",
        verbose_name="Paso de ruta",
    )
    requirement = models.ForeignKey(
        RouteStepComponentRequirement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="installed_components",
        verbose_name="Requerimiento",
    )
    part_code = models.CharField("Codigo de parte", max_length=80)
    part_name = models.CharField("Nombre de parte", max_length=180, blank=True)
    serial_number = models.CharField("Numero de serie", max_length=120, blank=True)
    lot_number = models.CharField("Numero de lote", max_length=120, blank=True)
    quantity = models.DecimalField("Cantidad", max_digits=14, decimal_places=4, default=1)
    installed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assembly_components_installed",
        verbose_name="Instalado por",
    )
    installed_at = models.DateTimeField("Fecha/hora de instalacion", default=timezone.now, db_index=True)
    source_event = models.ForeignKey(
        UnitStationEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="installed_components",
        verbose_name="Evento origen",
    )
    is_critical = models.BooleanField("Critico", default=False)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["unit", "part_code", "installed_at"]
        verbose_name = "Componente instalado"
        verbose_name_plural = "Componentes instalados"
        indexes = [
            models.Index(fields=["unit", "part_code"], name="inst_comp_unit_part_idx"),
            models.Index(fields=["serial_number"], name="installed_component_serial_idx"),
            models.Index(fields=["lot_number"], name="installed_component_lot_idx"),
        ]

    def __str__(self):
        trace = self.serial_number or self.lot_number or "sin trazabilidad"
        return f"{self.unit.serial_number} / {self.part_code} / {trace}"

    def clean(self):
        super().clean()
        if self.quantity <= Decimal("0"):
            raise ValidationError({"quantity": "La cantidad debe ser mayor a cero."})
        if self.requirement_id:
            self.requirement.validate_installed_component(self)
        elif not self.serial_number and not self.lot_number:
            raise ValidationError("El componente instalado debe tener numero de serie o numero de lote.")
        if self.route_step_id and self.station_id and self.route_step.station_id != self.station_id:
            raise ValidationError({"route_step": "El paso de ruta no pertenece a la estacion seleccionada."})
        if self.route_step_id and self.unit_id and self.route_step.route.version_id != self.unit.version_id:
            raise ValidationError({"route_step": "La ruta del paso no corresponde a la version de la unidad."})


class QualityGate(AuditModel):
    unit = models.ForeignKey(
        SerializedUnit,
        on_delete=models.CASCADE,
        related_name="quality_gates",
        verbose_name="Unidad",
    )
    station = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quality_gates",
        verbose_name="Estacion",
    )
    route_step = models.ForeignKey(
        AssemblyRouteStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quality_gates",
        verbose_name="Paso de ruta",
    )
    status = models.CharField("Estado", max_length=20, choices=QualityGateStatus.choices, default=QualityGateStatus.PENDING, db_index=True)
    is_blocking = models.BooleanField("Bloquea liberacion", default=True)
    defect_code = models.CharField("Codigo de defecto", max_length=80, blank=True)
    defect_classification = models.CharField(
        "Clasificacion",
        max_length=20,
        choices=QualityDefectClassification.choices,
        default=QualityDefectClassification.OTHER,
    )
    defect_severity = models.CharField(
        "Severidad",
        max_length=20,
        choices=QualityDefectSeverity.choices,
        default=QualityDefectSeverity.MINOR,
    )
    root_cause = models.CharField("Causa raiz", max_length=180, blank=True)
    responsible_area = models.CharField("Responsable/area", max_length=120, blank=True)
    inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assembly_quality_gates",
        verbose_name="Inspeccionado por",
    )
    inspected_at = models.DateTimeField("Fecha/hora de inspeccion", null=True, blank=True)
    evidence_reference = models.CharField("Referencia de evidencia", max_length=120, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["unit", "station__sequence", "id"]
        verbose_name = "Control de calidad"
        verbose_name_plural = "Controles de calidad"
        indexes = [
            models.Index(fields=["unit", "status"], name="qgate_unit_status_idx"),
            models.Index(fields=["station", "status"], name="qgate_station_status_idx"),
            models.Index(fields=["defect_code"], name="qgate_defect_code_idx"),
        ]

    def __str__(self):
        station = self.station.code if self.station_id else "general"
        return f"{self.unit.serial_number} / {station} / {self.get_status_display()}"

    @property
    def is_closed(self):
        return self.status in {QualityGateStatus.PASSED, QualityGateStatus.FAILED, QualityGateStatus.WAIVED}

    def sync_reinspection_reworks(self, user=None):
        reworks = self.rework_reinspections.exclude(
            status__in=[ReworkStatus.CLOSED, ReworkStatus.CANCELLED],
        )
        for rework in reworks:
            rework.updated_by = user or self.updated_by
            if self.status in {QualityGateStatus.PASSED, QualityGateStatus.WAIVED}:
                rework.status = ReworkStatus.CLOSED
                rework.closed_by = user or self.inspected_by
                rework.closed_at = timezone.now()
                if not rework.closure_notes:
                    rework.closure_notes = "Retrabajo cerrado por reinspeccion de calidad."
                rework.save(
                    update_fields=[
                        "status",
                        "closed_by",
                        "closed_at",
                        "closure_notes",
                        "updated_by",
                        "updated_at",
                    ]
                )
            elif self.status == QualityGateStatus.FAILED:
                rework.status = ReworkStatus.IN_PROGRESS
                rework.save(update_fields=["status", "updated_by", "updated_at"])

    def clean(self):
        super().clean()
        if self.route_step_id and self.station_id and self.route_step.station_id != self.station_id:
            raise ValidationError({"route_step": "El paso de ruta no pertenece a la estacion seleccionada."})
        if self.route_step_id and self.unit_id and self.route_step.route.version_id != self.unit.version_id:
            raise ValidationError({"route_step": "La ruta del paso no corresponde a la version de la unidad."})

    def apply_result_to_unit(self, user=None):
        if not self.unit_id or self.unit.status == UnitStatus.RELEASED:
            return
        if self.status == QualityGateStatus.FAILED:
            has_rework_reinspection = self.rework_reinspections.exclude(
                status__in=[ReworkStatus.CLOSED, ReworkStatus.CANCELLED],
            ).exists()
            self.sync_reinspection_reworks(user)
            self.unit.status = UnitStatus.REWORK if has_rework_reinspection else UnitStatus.QUALITY_HOLD
        elif self.status in {QualityGateStatus.PASSED, QualityGateStatus.WAIVED}:
            self.sync_reinspection_reworks(user)
            has_blocking_quality = self.unit.quality_gates.filter(is_blocking=True).exclude(
                status__in=[QualityGateStatus.PASSED, QualityGateStatus.WAIVED],
            ).exists()
            has_open_rework = self.unit.rework_orders.exclude(
                status__in=[ReworkStatus.CLOSED, ReworkStatus.CANCELLED],
            ).exists()
            if has_blocking_quality or has_open_rework:
                return
            if self.route_step_id and not AssemblyRouteStep.objects.filter(
                route=self.route_step.route,
                is_active=True,
                sequence__gt=self.route_step.sequence,
            ).exists():
                self.unit.status = UnitStatus.COMPLETED
            else:
                self.unit.status = UnitStatus.IN_PROCESS
        else:
            return
        self.unit.updated_by = user or self.updated_by
        self.unit.save(update_fields=["status", "updated_by", "updated_at"])


class ReworkOrder(AuditModel):
    unit = models.ForeignKey(
        SerializedUnit,
        on_delete=models.CASCADE,
        related_name="rework_orders",
        verbose_name="Unidad",
    )
    station_detected = models.ForeignKey(
        AssemblyStation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rework_orders",
        verbose_name="Estacion detectada",
    )
    route_step_detected = models.ForeignKey(
        AssemblyRouteStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rework_orders",
        verbose_name="Paso detectado",
    )
    defect_code = models.CharField("Codigo de defecto", max_length=80, blank=True)
    description = models.TextField("Descripcion")
    status = models.CharField("Estado", max_length=20, choices=ReworkStatus.choices, default=ReworkStatus.OPEN, db_index=True)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assembly_reworks_opened",
        verbose_name="Abierto por",
    )
    opened_at = models.DateTimeField("Fecha/hora de apertura", default=timezone.now, db_index=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assembly_reworks_closed",
        verbose_name="Cerrado por",
    )
    closed_at = models.DateTimeField("Fecha/hora de cierre", null=True, blank=True)
    closure_evidence_reference = models.CharField("Evidencia de cierre", max_length=120, blank=True)
    closure_notes = models.TextField("Notas de cierre", blank=True)
    reinspection_gate = models.ForeignKey(
        "QualityGate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rework_reinspections",
        verbose_name="Control de reinspeccion",
    )

    class Meta:
        ordering = ["-opened_at", "-id"]
        verbose_name = "Retrabajo"
        verbose_name_plural = "Retrabajos"
        indexes = [
            models.Index(fields=["unit", "status"], name="rework_unit_status_idx"),
            models.Index(fields=["station_detected", "status"], name="rework_station_status_idx"),
        ]

    def __str__(self):
        return f"{self.unit.serial_number} / {self.defect_code or self.pk}"

    def clean(self):
        super().clean()
        if self.route_step_detected_id and self.station_detected_id and self.route_step_detected.station_id != self.station_detected_id:
            raise ValidationError({"route_step_detected": "El paso de ruta no pertenece a la estacion seleccionada."})
        if self.route_step_detected_id and self.unit_id and self.route_step_detected.route.version_id != self.unit.version_id:
            raise ValidationError({"route_step_detected": "La ruta del paso no corresponde a la version de la unidad."})

    def start(self, user):
        self.status = ReworkStatus.IN_PROGRESS
        self.unit.status = UnitStatus.REWORK
        self.updated_by = user
        self.unit.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])
        self.unit.save(update_fields=["status", "updated_by", "updated_at"])

    def refresh_unit_status_after_resolution(self, user=None):
        if not self.unit_id or self.unit.status == UnitStatus.RELEASED:
            return
        has_blocking_quality = self.unit.quality_gates.filter(is_blocking=True).exclude(
            status__in=[QualityGateStatus.PASSED, QualityGateStatus.WAIVED],
        ).exists()
        if has_blocking_quality:
            self.unit.status = UnitStatus.QUALITY_HOLD
        elif self.unit.rework_orders.exclude(status__in=[ReworkStatus.CLOSED, ReworkStatus.CANCELLED]).exists():
            self.unit.status = UnitStatus.REWORK
        elif self.route_step_detected_id and AssemblyRouteStep.objects.filter(
            route=self.route_step_detected.route,
            is_active=True,
            sequence__gt=self.route_step_detected.sequence,
        ).exists():
            self.unit.status = UnitStatus.IN_PROCESS
        else:
            self.unit.status = UnitStatus.COMPLETED
        self.unit.updated_by = user or self.updated_by
        self.unit.save(update_fields=["status", "updated_by", "updated_at"])

    def send_to_quality_review(self, user, evidence_reference, notes=""):
        gate = self.reinspection_gate
        if gate is None:
            gate = QualityGate.objects.create(
                unit=self.unit,
                station=self.station_detected,
                route_step=self.route_step_detected,
                status=QualityGateStatus.PENDING,
                is_blocking=True,
                evidence_reference=f"REWORK-{self.pk}-QA",
                notes="Reinspeccion posterior a retrabajo.",
                created_by=user,
                updated_by=user,
            )
            self.reinspection_gate = gate
        if self.station_detected_id:
            UnitStationEvent.objects.create(
                unit=self.unit,
                station=self.station_detected,
                route_step=self.route_step_detected,
                event_type=StationEventType.REWORK_IN,
                event_at=timezone.now(),
                operator=user,
                source=StationEventSource.MANUAL,
                external_reference=f"RW-IN-{timezone.now().strftime('%Y%m%d%H%M%S%f')}-{self.pk}",
                notes=notes or "Unidad enviada a reinspeccion posterior a retrabajo.",
                metadata={"rework_order": self.pk, "reinspection_gate": gate.pk},
                created_by=user,
                updated_by=user,
            )
        self.status = ReworkStatus.QA_REVIEW
        self.closure_evidence_reference = evidence_reference
        if notes:
            self.closure_notes = notes
        self.unit.status = UnitStatus.QUALITY_HOLD
        self.updated_by = user
        self.unit.updated_by = user
        self.save(
            update_fields=[
                "status",
                "closure_evidence_reference",
                "closure_notes",
                "reinspection_gate",
                "updated_by",
                "updated_at",
            ]
        )
        self.unit.save(update_fields=["status", "updated_by", "updated_at"])
        return gate

    def close(self, user, notes="", evidence_reference=""):
        self.status = ReworkStatus.CLOSED
        self.closed_by = user
        self.closed_at = timezone.now()
        self.closure_notes = notes
        self.closure_evidence_reference = evidence_reference or self.closure_evidence_reference
        self.updated_by = user
        self.save(
            update_fields=[
                "status",
                "closed_by",
                "closed_at",
                "closure_notes",
                "closure_evidence_reference",
                "updated_by",
                "updated_at",
            ]
        )
        self.refresh_unit_status_after_resolution(user)

    def cancel(self, user, notes=""):
        self.status = ReworkStatus.CANCELLED
        if notes:
            self.closure_notes = notes
        self.updated_by = user
        self.save(update_fields=["status", "closure_notes", "updated_by", "updated_at"])
        self.refresh_unit_status_after_resolution(user)


class ReleaseApproval(AuditModel):
    unit = models.ForeignKey(
        SerializedUnit,
        on_delete=models.CASCADE,
        related_name="release_approvals",
        verbose_name="Unidad",
    )
    decision = models.CharField("Decision", max_length=20, choices=ReleaseDecision.choices, default=ReleaseDecision.PENDING, db_index=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assembly_release_decisions",
        verbose_name="Decidido por",
    )
    decided_at = models.DateTimeField("Fecha/hora de decision", null=True, blank=True)
    evidence_reference = models.CharField("Referencia de evidencia", max_length=120, blank=True)
    notes = models.TextField("Notas", blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Liberacion de unidad"
        verbose_name_plural = "Liberaciones de unidad"
        indexes = [
            models.Index(fields=["unit", "decision"], name="release_unit_decision_idx"),
        ]

    def __str__(self):
        return f"{self.unit.serial_number} / {self.get_decision_display()}"

    def clean(self):
        super().clean()
        if self.decision != ReleaseDecision.APPROVED or not self.unit_id:
            return
        open_reworks = self.unit.rework_orders.exclude(
            status__in=[ReworkStatus.CLOSED, ReworkStatus.CANCELLED],
        ).exists()
        if open_reworks:
            raise ValidationError("La unidad tiene retrabajos abiertos y no puede liberarse.")
        blocking_quality = self.unit.quality_gates.filter(is_blocking=True).exclude(
            status__in=[QualityGateStatus.PASSED, QualityGateStatus.WAIVED],
        ).exists()
        if blocking_quality:
            raise ValidationError("La unidad tiene controles de calidad bloqueantes pendientes o fallidos.")
        as_built_issues = self.unit.as_built_issues()
        if as_built_issues:
            issue_summary = " ".join(as_built_issues[:3])
            raise ValidationError(f"La unidad tiene componentes requeridos pendientes: {issue_summary}")
        measurement_issues = self.unit.measurement_issues()
        if measurement_issues:
            issue_summary = " ".join(measurement_issues[:3])
            raise ValidationError(f"La unidad tiene mediciones obligatorias pendientes: {issue_summary}")

    def apply_decision_to_unit(self, user=None):
        if not self.unit_id:
            return
        if self.decision == ReleaseDecision.APPROVED:
            self.unit.status = UnitStatus.RELEASED
        elif self.decision == ReleaseDecision.REJECTED and self.unit.status != UnitStatus.RELEASED:
            self.unit.status = UnitStatus.QUALITY_HOLD
        else:
            return
        self.unit.updated_by = user or self.updated_by
        self.unit.save(update_fields=["status", "updated_by", "updated_at"])
