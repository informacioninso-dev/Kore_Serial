from django import forms

from assembly.models import AssemblyStation
from core.models import EquipmentIntegration

from .models import (
    EdgeCommand,
    EdgeCommandType,
    EdgeDevice,
    EdgeGateway,
    EdgeSignalRule,
)


class EdgeFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault(
                    "class", "h-4 w-4 rounded border-gray-300 text-orange-600 focus:ring-orange-500"
                )
                continue
            field.widget.attrs.setdefault(
                "class",
                "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-200",
            )


class EdgeGatewayForm(EdgeFormMixin, forms.ModelForm):
    class Meta:
        model = EdgeGateway
        fields = [
            "code",
            "name",
            "plant",
            "host",
            "agent_version",
            "heartbeat_interval_seconds",
            "degraded_after_missed",
            "offline_after_missed",
            "is_active",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class EdgeDeviceForm(EdgeFormMixin, forms.ModelForm):
    class Meta:
        model = EdgeDevice
        fields = [
            "gateway",
            "code",
            "name",
            "device_type",
            "protocol",
            "address",
            "equipment",
            "station",
            "is_active",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gateway"].queryset = EdgeGateway.objects.filter(is_active=True).order_by("code")
        self.fields["equipment"].queryset = EquipmentIntegration.objects.filter(is_active=True).order_by("code")
        self.fields["station"].queryset = AssemblyStation.objects.filter(is_active=True).select_related("line").order_by(
            "line__code", "code"
        )


class EdgeSignalRuleForm(EdgeFormMixin, forms.ModelForm):
    class Meta:
        model = EdgeSignalRule
        fields = [
            "code",
            "name",
            "signal_key",
            "device",
            "device_type",
            "action",
            "station_event_type",
            "measurement_code",
            "measurement_name",
            "unit_of_measure",
            "min_value",
            "max_value",
            "priority",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["device"].queryset = EdgeDevice.objects.filter(is_active=True).select_related("gateway").order_by(
            "gateway__code", "code"
        )
        self.fields["device"].required = False
        self.fields["station_event_type"].required = False


class EdgeCommandForm(EdgeFormMixin, forms.ModelForm):
    class Meta:
        model = EdgeCommand
        fields = ["gateway", "device", "command_type", "payload"]
        widgets = {"payload": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gateway"].queryset = EdgeGateway.objects.filter(is_active=True).order_by("code")
        self.fields["device"].queryset = EdgeDevice.objects.filter(is_active=True).select_related("gateway").order_by(
            "gateway__code", "code"
        )
        self.fields["device"].required = False
        self.fields["payload"].required = False
        self.fields["payload"].help_text = 'JSON con los parametros del comando. Ej: {"zpl": "^XA^XZ"}'

    def clean(self):
        cleaned = super().clean()
        gateway = cleaned.get("gateway")
        device = cleaned.get("device")
        if gateway and device and device.gateway_id != gateway.pk:
            self.add_error("device", "El dispositivo no pertenece al gateway seleccionado.")
        if cleaned.get("command_type") == EdgeCommandType.PRINT_LABEL and not device:
            self.add_error("device", "Imprimir etiqueta requiere un dispositivo destino.")
        return cleaned
