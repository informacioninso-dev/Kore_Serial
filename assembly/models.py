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


class ReleaseDecision(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    APPROVED = "APPROVED", "Liberada"
    REJECTED = "REJECTED", "Rechazada"


class ComponentTraceability(models.TextChoices):
    SERIAL = "SERIAL", "Serial obligatorio"
    LOT = "LOT", "Lote obligatorio"
    SERIAL_OR_LOT = "SERIAL_OR_LOT", "Serial o lote"
    SERIAL_AND_LOT = "SERIAL_AND_LOT", "Serial y lote"


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


class SerializedUnit(AuditModel):
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


class AssemblyLine(AuditModel):
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
        unit.production_plan = self
        unit.updated_by = user
        unit.save(update_fields=["production_plan", "updated_by", "updated_at"])
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
