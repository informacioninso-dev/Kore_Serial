from django import forms

from core.models import Location

from .models import (
    AssemblyKit,
    AssemblyKitLine,
    InboundReceipt,
    InboundReceiptLine,
    InventoryState,
    LocationOperationalType,
    Material,
    MaterialCategory,
    MaterialLot,
    MaterialSerial,
    KanbanSignal,
    PickMission,
    PickTask,
    ReplenishmentRule,
    WmsLocationProfile,
)


class WMSFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "h-4 w-4 rounded border-gray-300 text-orange-600 focus:ring-orange-500")
                continue
            field.widget.attrs.setdefault(
                "class",
                "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-200",
            )


class MaterialCategoryForm(WMSFormMixin, forms.ModelForm):
    class Meta:
        model = MaterialCategory
        fields = ["code", "name", "is_active"]


class MaterialForm(WMSFormMixin, forms.ModelForm):
    class Meta:
        model = Material
        fields = ["code", "name", "description", "category", "base_unit", "traceability", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class WmsLocationProfileForm(WMSFormMixin, forms.ModelForm):
    class Meta:
        model = WmsLocationProfile
        fields = ["location", "operational_type", "allows_mixed_materials", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.objects.filter(is_active=True).select_related("warehouse").order_by(
            "warehouse__code", "code"
        )


class InboundReceiptForm(WMSFormMixin, forms.ModelForm):
    class Meta:
        model = InboundReceipt
        fields = ["code", "supplier_name", "container_number", "asn_reference", "destination_location", "received_at", "notes"]
        widgets = {"received_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destination_location"].queryset = Location.objects.filter(is_active=True).select_related("warehouse").order_by(
            "warehouse__code", "code"
        )


class InboundReceiptLineForm(WMSFormMixin, forms.ModelForm):
    class Meta:
        model = InboundReceiptLine
        fields = ["material", "expected_quantity", "lot_number", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["material"].queryset = Material.objects.filter(is_active=True).order_by("code")


class ReceiveReceiptLineForm(WMSFormMixin, forms.Form):
    quantity = forms.DecimalField(max_digits=14, decimal_places=4, min_value=0.0001, label="Cantidad a recibir")
    lot_number = forms.CharField(max_length=120, required=False, label="Lote")
    serial_numbers = forms.CharField(
        required=False,
        label="Series",
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Una serie por linea"}),
        help_text="Obligatorio para materiales trazados por serie.",
    )
    reason = forms.CharField(max_length=240, required=False, label="Nota de recepcion")

    def serial_list(self):
        return self.cleaned_data["serial_numbers"].splitlines()


class InventoryOperationForm(WMSFormMixin, forms.Form):
    OPERATION_TRANSFER = "TRANSFER"
    OPERATION_STATE = "STATE"
    OPERATION_ADJUST_IN = "ADJUST_IN"
    OPERATION_ADJUST_OUT = "ADJUST_OUT"
    operation = forms.ChoiceField(
        label="Operacion",
        choices=(
            (OPERATION_TRANSFER, "Traslado"),
            (OPERATION_STATE, "Cambio de estado"),
            (OPERATION_ADJUST_IN, "Ajuste positivo"),
            (OPERATION_ADJUST_OUT, "Ajuste negativo"),
        ),
    )
    material = forms.ModelChoiceField(queryset=Material.objects.none(), label="Material")
    quantity = forms.DecimalField(max_digits=14, decimal_places=4, min_value=0.0001, label="Cantidad")
    source_location = forms.ModelChoiceField(queryset=Location.objects.none(), required=False, label="Ubicacion origen")
    destination_location = forms.ModelChoiceField(queryset=Location.objects.none(), required=False, label="Ubicacion destino")
    source_state = forms.ChoiceField(choices=InventoryState.choices, required=False, label="Estado origen")
    destination_state = forms.ChoiceField(choices=InventoryState.choices, required=False, label="Estado destino")
    lot = forms.ModelChoiceField(queryset=MaterialLot.objects.none(), required=False, label="Lote")
    serial = forms.ModelChoiceField(queryset=MaterialSerial.objects.none(), required=False, label="Serie")
    reason = forms.CharField(max_length=240, label="Motivo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["material"].queryset = Material.objects.filter(is_active=True).order_by("code")
        self.fields["source_location"].queryset = Location.objects.filter(is_active=True).select_related("warehouse").order_by(
            "warehouse__code", "code"
        )
        self.fields["destination_location"].queryset = self.fields["source_location"].queryset
        self.fields["lot"].queryset = MaterialLot.objects.select_related("material").order_by("material__code", "number")
        self.fields["serial"].queryset = MaterialSerial.objects.select_related("material").order_by("material__code", "number")

    def clean(self):
        cleaned = super().clean()
        operation = cleaned.get("operation")
        material = cleaned.get("material")
        lot = cleaned.get("lot")
        serial = cleaned.get("serial")
        if lot and material and lot.material_id != material.pk:
            self.add_error("lot", "El lote no pertenece al material.")
        if serial and material and serial.material_id != material.pk:
            self.add_error("serial", "La serie no pertenece al material.")
        if serial and cleaned.get("quantity") != 1:
            self.add_error("quantity", "Una serie se mueve de una en una.")
        if operation == self.OPERATION_TRANSFER:
            if not cleaned.get("source_location"):
                self.add_error("source_location", "Indica origen para el traslado.")
            if not cleaned.get("destination_location"):
                self.add_error("destination_location", "Indica destino para el traslado.")
            if not cleaned.get("source_state"):
                self.add_error("source_state", "Indica el estado de origen.")
        elif operation == self.OPERATION_STATE:
            if not cleaned.get("source_location"):
                self.add_error("source_location", "Indica la ubicacion.")
            if not cleaned.get("source_state") or not cleaned.get("destination_state"):
                self.add_error("destination_state", "Indica ambos estados.")
        elif operation == self.OPERATION_ADJUST_IN:
            if not cleaned.get("destination_location") or not cleaned.get("destination_state"):
                self.add_error("destination_location", "Indica destino y estado para el ajuste positivo.")
        elif operation == self.OPERATION_ADJUST_OUT:
            if not cleaned.get("source_location") or not cleaned.get("source_state"):
                self.add_error("source_location", "Indica origen y estado para el ajuste negativo.")
        return cleaned


class AssemblyKitForm(WMSFormMixin, forms.ModelForm):
    class Meta:
        model = AssemblyKit
        fields = ["code", "production_plan", "serialized_unit", "destination_location", "station", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destination_location"].queryset = Location.objects.filter(
            is_active=True,
            wms_profile__is_active=True,
            wms_profile__operational_type__in=[LocationOperationalType.SUPERMARKET, LocationOperationalType.LINE_SIDE],
        ).select_related("warehouse").order_by("warehouse__code", "code")


class AssemblyKitLineForm(WMSFormMixin, forms.ModelForm):
    class Meta:
        model = AssemblyKitLine
        fields = ["material", "required_quantity", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["material"].queryset = Material.objects.filter(is_active=True).order_by("code")


class PickMissionForm(WMSFormMixin, forms.ModelForm):
    class Meta:
        model = PickMission
        fields = ["code", "kit", "source_location", "destination_location", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        locations = Location.objects.filter(is_active=True).select_related("warehouse").order_by("warehouse__code", "code")
        self.fields["source_location"].queryset = locations
        self.fields["destination_location"].queryset = locations.filter(
            wms_profile__is_active=True,
            wms_profile__operational_type__in=[LocationOperationalType.SUPERMARKET, LocationOperationalType.LINE_SIDE],
        )
        self.fields["kit"].queryset = AssemblyKit.objects.filter(status="RELEASED").order_by("code")


class PickTaskForm(WMSFormMixin, forms.ModelForm):
    class Meta:
        model = PickTask
        fields = ["kit_line", "material", "quantity", "lot", "serial"]

    def __init__(self, *args, mission=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.mission = mission
        self.fields["material"].queryset = Material.objects.filter(is_active=True).order_by("code")
        self.fields["lot"].queryset = MaterialLot.objects.select_related("material").order_by("material__code", "number")
        self.fields["serial"].queryset = MaterialSerial.objects.select_related("material").order_by("material__code", "number")
        if mission and mission.kit_id:
            self.fields["kit_line"].queryset = mission.kit.lines.select_related("material").all()
        else:
            self.fields["kit_line"].queryset = AssemblyKitLine.objects.none()


class ReplenishmentRuleForm(WMSFormMixin, forms.ModelForm):
    class Meta:
        model = ReplenishmentRule
        fields = ["code", "material", "source_location", "destination_location", "minimum_quantity", "maximum_quantity", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        locations = Location.objects.filter(is_active=True).select_related("warehouse").order_by("warehouse__code", "code")
        self.fields["material"].queryset = Material.objects.filter(is_active=True).order_by("code")
        self.fields["source_location"].queryset = locations
        self.fields["destination_location"].queryset = locations.filter(
            wms_profile__is_active=True,
            wms_profile__operational_type__in=[LocationOperationalType.SUPERMARKET, LocationOperationalType.LINE_SIDE],
        )


class KanbanSignalCreateForm(WMSFormMixin, forms.Form):
    rule = forms.ModelChoiceField(queryset=ReplenishmentRule.objects.none(), label="Regla de reposicion")
    reason = forms.CharField(max_length=240, required=False, label="Motivo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rule"].queryset = ReplenishmentRule.objects.filter(is_active=True).select_related("material", "destination_location").order_by("code")
