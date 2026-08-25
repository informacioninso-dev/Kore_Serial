from django import forms

from core.models import EquipmentIntegration

from .models import (
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    AndonSignal,
    DowntimeStatus,
    ExternalMaterialKit,
    InstalledComponent,
    LineBalanceStudy,
    MeasurementResult,
    ModelMixPlan,
    ModelMixPlanItem,
    Plant,
    PlantArea,
    ProductVersion,
    ProductionMeasurement,
    ProductionOrder,
    ProductionPlan,
    ProductionDowntime,
    ProductionQueueItem,
    ProductionQueueStatus,
    QualityDefectClassification,
    QualityDefectSeverity,
    QualityGate,
    QualityGateStatus,
    ReleaseApproval,
    ReleaseDecision,
    ReworkOrder,
    RouteStepParameter,
    RouteStepComponentRequirement,
    SerializedUnit,
    StationOfflineEvent,
    UnitStationEvent,
)


class SerialFormMixin:
    date_fields = set()
    datetime_fields = set()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "h-4 w-4 rounded border-gray-300 text-orange-600 focus:ring-orange-500")
                continue
            if isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs.setdefault("class", "space-y-1 text-sm")
                continue
            base_class = "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-200"
            if isinstance(widget, forms.SelectMultiple):
                base_class += " min-h-32"
            widget.attrs.setdefault("class", base_class)
            if name in self.date_fields:
                widget.input_type = "date"
            if name in self.datetime_fields:
                widget.input_type = "datetime-local"


class AssembledProductForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = AssembledProduct
        fields = ["code", "name", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class ProductVersionForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = ProductVersion
        fields = ["product", "code", "name", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class PlantForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = Plant
        fields = ["code", "name", "description", "address", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class PlantAreaForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = PlantArea
        fields = ["plant", "code", "name", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class ProductionOrderForm(SerialFormMixin, forms.ModelForm):
    date_fields = {"due_date"}

    class Meta:
        model = ProductionOrder
        fields = [
            "code",
            "product",
            "version",
            "plant",
            "target_quantity",
            "due_date",
            "priority",
            "status",
            "external_reference",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class SerializedUnitForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = SerializedUnit
        fields = ["production_order", "version", "production_plan", "serial_number", "status"]

    def clean(self):
        cleaned_data = super().clean()
        version = cleaned_data.get("version")
        production_plan = cleaned_data.get("production_plan")
        production_order = cleaned_data.get("production_order")
        if production_plan and version and production_plan.version_id != version.pk:
            raise forms.ValidationError("La unidad debe tener la misma version que el plan seleccionado.")
        if production_order and version:
            if production_order.version_id and production_order.version_id != version.pk:
                raise forms.ValidationError("La unidad debe tener la misma version que la OP seleccionada.")
            if production_order.product_id != version.product_id:
                raise forms.ValidationError("La unidad debe pertenecer al producto de la OP seleccionada.")
        if production_plan and production_order and production_plan.production_order_id and production_plan.production_order_id != production_order.pk:
            raise forms.ValidationError("El plan seleccionado pertenece a otra OP.")
        return cleaned_data


class AssemblyLineForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = AssemblyLine
        fields = ["area", "code", "name", "description", "takt_time_seconds", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class ProductionPlanForm(SerialFormMixin, forms.ModelForm):
    date_fields = {"planned_date"}
    datetime_fields = {"planned_start_at", "planned_end_at"}

    class Meta:
        model = ProductionPlan
        fields = [
            "code",
            "production_order",
            "version",
            "line",
            "planned_date",
            "shift",
            "target_quantity",
            "priority",
            "status",
            "planned_start_at",
            "planned_end_at",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class ProductionPlanActionForm(SerialFormMixin, forms.Form):
    ACTION_RELEASE = "release"
    ACTION_START = "start"
    ACTION_CLOSE = "close"
    ACTION_CANCEL = "cancel"
    ACTION_GENERATE = "generate"
    ACTION_LINK = "link"
    ACTION_SEQUENCE = "sequence"
    ACTION_CHOICES = (
        (ACTION_RELEASE, "Liberar"),
        (ACTION_START, "Iniciar"),
        (ACTION_CLOSE, "Cerrar"),
        (ACTION_CANCEL, "Cancelar"),
        (ACTION_GENERATE, "Generar unidades"),
        (ACTION_LINK, "Vincular unidad"),
        (ACTION_SEQUENCE, "Generar secuencia"),
    )

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    quantity = forms.IntegerField(label="Cantidad", min_value=1, required=False)
    serial_prefix = forms.CharField(label="Prefijo serial", max_length=80, required=False)
    serial_number = forms.CharField(label="Serial existente", max_length=120, required=False)
    notes = forms.CharField(label="Notas", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        quantity = cleaned_data.get("quantity")
        serial_number = cleaned_data.get("serial_number", "").strip()
        if action == self.ACTION_GENERATE and not quantity:
            raise forms.ValidationError("Indica la cantidad de unidades a generar.")
        if action == self.ACTION_LINK and not serial_number:
            raise forms.ValidationError("Indica el serial existente que deseas vincular.")
        return cleaned_data


class ProductionQueueItemForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = ProductionQueueItem
        fields = [
            "production_plan",
            "unit",
            "line",
            "route",
            "sequence",
            "priority",
            "status",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        cleaned_data = super().clean()
        plan = cleaned_data.get("production_plan")
        unit = cleaned_data.get("unit")
        line = cleaned_data.get("line")
        route = cleaned_data.get("route")
        if plan:
            cleaned_data["line"] = plan.line
            if unit and unit.version_id != plan.version_id:
                raise forms.ValidationError("La unidad no corresponde a la version del plan.")
            if route and route.version_id != plan.version_id:
                raise forms.ValidationError("La ruta no corresponde a la version del plan.")
        if line and route and not route.steps.filter(station__line=line, is_active=True).exists():
            raise forms.ValidationError("La ruta no tiene pasos activos para la linea seleccionada.")
        return cleaned_data


class ProductionQueueActionForm(SerialFormMixin, forms.Form):
    ACTION_MOVE = "move"
    ACTION_READY = "ready"
    ACTION_HOLD = "hold"
    ACTION_CANCEL = "cancel"
    ACTION_CHOICES = (
        (ACTION_MOVE, "Mover"),
        (ACTION_READY, "Marcar lista"),
        (ACTION_HOLD, "Retener"),
        (ACTION_CANCEL, "Cancelar"),
    )

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    new_sequence = forms.IntegerField(label="Nueva secuencia", min_value=1, required=False)
    notes = forms.CharField(label="Motivo", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        new_sequence = cleaned_data.get("new_sequence")
        notes = cleaned_data.get("notes", "").strip()
        if action == self.ACTION_MOVE and not new_sequence:
            raise forms.ValidationError("Indica la nueva posicion en la cola.")
        if action in {self.ACTION_HOLD, self.ACTION_CANCEL} and not notes:
            raise forms.ValidationError("Registra el motivo para retener o cancelar.")
        return cleaned_data


class LineBalanceStudyForm(SerialFormMixin, forms.ModelForm):
    date_fields = {"actual_start_date", "actual_end_date"}

    class Meta:
        model = LineBalanceStudy
        fields = [
            "code",
            "line",
            "version",
            "route",
            "production_plan",
            "planned_units",
            "shift_duration_seconds",
            "target_takt_seconds",
            "actual_start_date",
            "actual_end_date",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        cleaned_data = super().clean()
        plan = cleaned_data.get("production_plan")
        line = cleaned_data.get("line")
        version = cleaned_data.get("version")
        route = cleaned_data.get("route")
        if plan:
            if line and plan.line_id != line.pk:
                raise forms.ValidationError("El plan no corresponde a la linea seleccionada.")
            if version and plan.version_id != version.pk:
                raise forms.ValidationError("El plan no corresponde a la version seleccionada.")
            if not cleaned_data.get("planned_units"):
                cleaned_data["planned_units"] = plan.target_quantity
        if route and version and route.version_id != version.pk:
            raise forms.ValidationError("La ruta no corresponde a la version seleccionada.")
        return cleaned_data


class LineBalanceActionForm(SerialFormMixin, forms.Form):
    ACTION_CALCULATE = "calculate"
    ACTION_CHOICES = ((ACTION_CALCULATE, "Calcular balanceo"),)

    action = forms.ChoiceField(choices=ACTION_CHOICES)


class AndonSignalForm(SerialFormMixin, forms.ModelForm):
    datetime_fields = {"opened_at"}

    class Meta:
        model = AndonSignal
        fields = [
            "code",
            "line",
            "station",
            "unit",
            "production_plan",
            "severity",
            "status",
            "title",
            "description",
            "source",
            "opened_by",
            "opened_at",
            "resolution_notes",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "resolution_notes": forms.Textarea(attrs={"rows": 3}),
        }


class AndonActionForm(SerialFormMixin, forms.Form):
    ACTION_ACKNOWLEDGE = "acknowledge"
    ACTION_RESOLVE = "resolve"
    ACTION_CANCEL = "cancel"
    ACTION_CHOICES = (
        (ACTION_ACKNOWLEDGE, "Reconocer"),
        (ACTION_RESOLVE, "Resolver"),
        (ACTION_CANCEL, "Cancelar"),
    )

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    notes = forms.CharField(label="Notas", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        notes = cleaned_data.get("notes", "").strip()
        if action in {self.ACTION_RESOLVE, self.ACTION_CANCEL} and not notes:
            raise forms.ValidationError("Registra notas para resolver o cancelar.")
        return cleaned_data


class ProductionDowntimeForm(SerialFormMixin, forms.ModelForm):
    datetime_fields = {"started_at", "ended_at"}

    class Meta:
        model = ProductionDowntime
        fields = [
            "code",
            "line",
            "station",
            "unit",
            "production_plan",
            "andon_signal",
            "status",
            "cause_category",
            "cause_code",
            "cause_description",
            "started_at",
            "ended_at",
            "opened_by",
            "closed_by",
            "evidence_reference",
            "notes",
        ]
        widgets = {
            "cause_description": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class DowntimeActionForm(SerialFormMixin, forms.Form):
    ACTION_CLOSE = "close"
    ACTION_CANCEL = "cancel"
    ACTION_CHOICES = (
        (ACTION_CLOSE, "Cerrar paro"),
        (ACTION_CANCEL, "Cancelar paro"),
    )

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    ended_at = forms.DateTimeField(label="Fin", required=False)
    evidence_reference = forms.CharField(label="Evidencia", max_length=120, required=False)
    notes = forms.CharField(label="Notas", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    datetime_fields = {"ended_at"}

    def clean(self):
        cleaned_data = super().clean()
        notes = cleaned_data.get("notes", "").strip()
        if cleaned_data.get("action") == self.ACTION_CANCEL and not notes:
            raise forms.ValidationError("Registra el motivo para cancelar el paro.")
        return cleaned_data


class StationOfflineEventForm(SerialFormMixin, forms.ModelForm):
    datetime_fields = {"captured_at"}

    class Meta:
        model = StationOfflineEvent
        fields = [
            "external_id",
            "station",
            "unit_serial_number",
            "operator_username",
            "event_type",
            "captured_at",
            "payload",
            "notes",
        ]
        widgets = {
            "payload": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class OfflineEventActionForm(SerialFormMixin, forms.Form):
    ACTION_SYNC = "sync"
    ACTION_CHOICES = ((ACTION_SYNC, "Sincronizar"),)

    action = forms.ChoiceField(choices=ACTION_CHOICES)


class ModelMixPlanForm(SerialFormMixin, forms.ModelForm):
    date_fields = {"planned_date"}

    class Meta:
        model = ModelMixPlan
        fields = ["code", "line", "planned_date", "shift", "status", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class ModelMixPlanItemForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = ModelMixPlanItem
        fields = ["mix_plan", "version", "planned_quantity", "sequence_bias", "priority", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class ModelMixActionForm(SerialFormMixin, forms.Form):
    ACTION_ACTIVATE = "activate"
    ACTION_GENERATE_PLANS = "generate_plans"
    ACTION_CLOSE = "close"
    ACTION_CANCEL = "cancel"
    ACTION_CHOICES = (
        (ACTION_ACTIVATE, "Activar mix"),
        (ACTION_GENERATE_PLANS, "Generar planes"),
        (ACTION_CLOSE, "Cerrar mix"),
        (ACTION_CANCEL, "Cancelar mix"),
    )

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    notes = forms.CharField(label="Notas", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("action") == self.ACTION_CANCEL and not cleaned_data.get("notes", "").strip():
            raise forms.ValidationError("Registra el motivo para cancelar el mix.")
        return cleaned_data


class ExternalMaterialKitForm(SerialFormMixin, forms.ModelForm):
    datetime_fields = {"received_at"}

    class Meta:
        model = ExternalMaterialKit
        fields = [
            "code",
            "external_system",
            "external_reference",
            "version",
            "production_plan",
            "line",
            "container_code",
            "lot_number",
            "expected_quantity",
            "received_quantity",
            "status",
            "received_at",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class AssemblyStationForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = AssemblyStation
        fields = [
            "line",
            "code",
            "name",
            "sequence",
            "takt_time_seconds",
            "requires_quality_gate",
            "equipment",
            "authorized_operators",
            "is_active",
        ]


class AssemblyRouteForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = AssemblyRoute
        fields = ["version", "code", "revision", "name", "description", "approval_status", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class AssemblyRouteStepForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = AssemblyRouteStep
        fields = [
            "route",
            "station",
            "sequence",
            "name",
            "expected_duration_seconds",
            "requires_component_trace",
            "requires_quality_gate",
            "instructions",
            "safety_notes",
            "acceptance_criteria",
            "media_reference",
            "is_active",
        ]
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 4}),
            "safety_notes": forms.Textarea(attrs={"rows": 3}),
            "acceptance_criteria": forms.Textarea(attrs={"rows": 3}),
        }


class RouteStepParameterForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = RouteStepParameter
        fields = [
            "route_step",
            "code",
            "name",
            "parameter_type",
            "unit",
            "target_value",
            "min_value",
            "max_value",
            "origin",
            "is_required",
            "is_quality_critical",
            "is_active",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class RouteStepComponentRequirementForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = RouteStepComponentRequirement
        fields = [
            "route_step",
            "part_code",
            "part_name",
            "quantity_required",
            "traceability",
            "is_critical",
            "is_active",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class UnitStationEventForm(SerialFormMixin, forms.ModelForm):
    datetime_fields = {"event_at"}

    class Meta:
        model = UnitStationEvent
        fields = [
            "unit",
            "station",
            "route_step",
            "event_type",
            "event_at",
            "operator",
            "source",
            "external_reference",
            "notes",
            "metadata",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3}), "metadata": forms.Textarea(attrs={"rows": 4})}


class ProductionMeasurementForm(SerialFormMixin, forms.ModelForm):
    datetime_fields = {"measured_at"}

    class Meta:
        model = ProductionMeasurement
        fields = [
            "unit",
            "station",
            "route_step",
            "parameter",
            "station_event",
            "code",
            "name",
            "value",
            "text_value",
            "unit_label",
            "min_value",
            "max_value",
            "result",
            "origin",
            "measured_by",
            "measured_at",
            "evidence_reference",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].required = False
        self.fields["name"].required = False
        self.fields["result"].choices = MeasurementResult.choices

    def clean(self):
        cleaned_data = super().clean()
        parameter = cleaned_data.get("parameter")
        if parameter:
            cleaned_data["route_step"] = parameter.route_step
            cleaned_data["station"] = parameter.route_step.station
            cleaned_data["code"] = parameter.code
            cleaned_data["name"] = parameter.name
            cleaned_data["unit_label"] = parameter.unit
            cleaned_data["min_value"] = parameter.min_value
            cleaned_data["max_value"] = parameter.max_value
            cleaned_data["origin"] = parameter.origin
        if not cleaned_data.get("code"):
            raise forms.ValidationError("Indica codigo de parametro o selecciona un parametro configurado.")
        if not cleaned_data.get("name"):
            cleaned_data["name"] = cleaned_data["code"]
        return cleaned_data


class InstalledComponentForm(SerialFormMixin, forms.ModelForm):
    datetime_fields = {"installed_at"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["part_code"].required = False

    class Meta:
        model = InstalledComponent
        fields = [
            "unit",
            "station",
            "route_step",
            "requirement",
            "part_code",
            "part_name",
            "serial_number",
            "lot_number",
            "quantity",
            "installed_by",
            "installed_at",
            "source_event",
            "is_critical",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        cleaned_data = super().clean()
        requirement = cleaned_data.get("requirement")
        if requirement:
            cleaned_data["route_step"] = requirement.route_step
            cleaned_data["station"] = requirement.route_step.station
            cleaned_data["part_code"] = requirement.part_code
            cleaned_data["part_name"] = requirement.part_name
            cleaned_data["is_critical"] = requirement.is_critical
        return cleaned_data


class QualityGateForm(SerialFormMixin, forms.ModelForm):
    datetime_fields = {"inspected_at"}

    class Meta:
        model = QualityGate
        fields = [
            "unit",
            "station",
            "route_step",
            "status",
            "is_blocking",
            "defect_code",
            "defect_classification",
            "defect_severity",
            "root_cause",
            "responsible_area",
            "inspected_by",
            "inspected_at",
            "evidence_reference",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class QualityGateDecisionForm(SerialFormMixin, forms.ModelForm):
    class Meta:
        model = QualityGate
        fields = [
            "status",
            "defect_code",
            "defect_classification",
            "defect_severity",
            "root_cause",
            "responsible_area",
            "evidence_reference",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (QualityGateStatus.PASSED, "Aprobar"),
            (QualityGateStatus.FAILED, "Fallar"),
            (QualityGateStatus.WAIVED, "Aprobar excepcion"),
        ]
        self.fields["evidence_reference"].required = True
        self.fields["defect_classification"].required = False
        self.fields["defect_severity"].required = False

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get("status")
        notes = cleaned_data.get("notes", "").strip()
        if not cleaned_data.get("defect_classification"):
            cleaned_data["defect_classification"] = QualityDefectClassification.OTHER
        if not cleaned_data.get("defect_severity"):
            cleaned_data["defect_severity"] = QualityDefectSeverity.MINOR
        if status in {QualityGateStatus.FAILED, QualityGateStatus.WAIVED} and not notes:
            raise forms.ValidationError("Registra notas para fallas o excepciones aprobadas.")
        return cleaned_data


class ReworkOrderForm(SerialFormMixin, forms.ModelForm):
    datetime_fields = {"opened_at", "closed_at"}

    class Meta:
        model = ReworkOrder
        fields = [
            "unit",
            "station_detected",
            "route_step_detected",
            "defect_code",
            "description",
            "status",
            "opened_by",
            "opened_at",
            "closed_by",
            "closed_at",
            "closure_evidence_reference",
            "closure_notes",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "closure_notes": forms.Textarea(attrs={"rows": 3}),
        }


class ReworkActionForm(SerialFormMixin, forms.Form):
    ACTION_START = "start"
    ACTION_SEND_QA = "send_qa"
    ACTION_CLOSE = "close"
    ACTION_CANCEL = "cancel"
    ACTION_CHOICES = (
        (ACTION_START, "Iniciar retrabajo"),
        (ACTION_SEND_QA, "Enviar a reinspeccion"),
        (ACTION_CLOSE, "Cerrar sin reinspeccion"),
        (ACTION_CANCEL, "Cancelar"),
    )

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    closure_evidence_reference = forms.CharField(label="Evidencia", max_length=120, required=False)
    notes = forms.CharField(label="Notas", required=False, widget=forms.Textarea(attrs={"rows": 4}))

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        evidence = cleaned_data.get("closure_evidence_reference", "").strip()
        notes = cleaned_data.get("notes", "").strip()
        if action in {self.ACTION_SEND_QA, self.ACTION_CLOSE} and not evidence:
            raise forms.ValidationError("Registra evidencia para cerrar o enviar a reinspeccion.")
        if action in {self.ACTION_SEND_QA, self.ACTION_CLOSE, self.ACTION_CANCEL} and not notes:
            raise forms.ValidationError("Registra notas para esta accion.")
        return cleaned_data


class ReleaseApprovalForm(SerialFormMixin, forms.ModelForm):
    datetime_fields = {"decided_at"}

    class Meta:
        model = ReleaseApproval
        fields = ["unit", "decision", "decided_by", "decided_at", "evidence_reference", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get("decision")
        evidence_reference = cleaned_data.get("evidence_reference", "").strip()
        if decision in {ReleaseDecision.APPROVED, ReleaseDecision.REJECTED} and not evidence_reference:
            raise forms.ValidationError("La liberacion o rechazo requiere referencia de evidencia.")
        return cleaned_data


class EquipmentIntegrationForm(SerialFormMixin, forms.ModelForm):
    date_fields = {"last_calibration_date", "next_calibration_date", "last_maintenance_date", "next_maintenance_date"}

    class Meta:
        model = EquipmentIntegration
        fields = [
            "code",
            "name",
            "equipment_type",
            "asset_code",
            "manufacturer",
            "model",
            "serial_number",
            "operating_parameters",
            "is_quality_critical",
            "connection_protocol",
            "host",
            "port",
            "serial_port",
            "warehouse",
            "location",
            "is_active",
            "requires_calibration",
            "last_calibration_date",
            "next_calibration_date",
            "calibration_certificate_ref",
            "requires_qualification",
            "requires_maintenance",
            "last_maintenance_date",
            "next_maintenance_date",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}
