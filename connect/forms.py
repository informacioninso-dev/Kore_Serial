from django import forms
from django.utils import timezone

from eventbus.models import EventType

from .models import Connector, ConnectorContract


class ConnectFormMixin:
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


class ConnectorForm(ConnectFormMixin, forms.ModelForm):
    class Meta:
        model = Connector
        fields = [
            "code",
            "name",
            "system",
            "direction",
            "transport",
            "endpoint",
            "auth_header",
            "auth_token",
            "inbound_token",
            "timeout_seconds",
            "max_attempts",
            "retry_backoff_seconds",
            "is_active",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["transport"].help_text = (
            "LOG arma y registra el mensaje sin salir a la red. Cambialo a HTTP solo "
            "cuando el endpoint este confirmado."
        )


class ConnectorContractForm(ConnectFormMixin, forms.ModelForm):
    class Meta:
        model = ConnectorContract
        fields = [
            "connector",
            "code",
            "name",
            "direction",
            "event_type",
            "field_map",
            "static_fields",
            "is_active",
        ]
        widgets = {
            "field_map": forms.Textarea(attrs={"rows": 4}),
            "static_fields": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["connector"].queryset = Connector.objects.filter(is_active=True).order_by("code")
        self.fields["event_type"].queryset = EventType.objects.filter(is_active=True).order_by(
            "domain", "code"
        )
        self.fields["event_type"].required = False
        self.fields["field_map"].required = False
        self.fields["static_fields"].required = False


class ReconciliationForm(ConnectFormMixin, forms.Form):
    connector = forms.ModelChoiceField(
        queryset=Connector.objects.filter(is_active=True).order_by("code"), label="Conector"
    )
    date_from = forms.DateField(label="Desde", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label="Hasta", widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["date_from"].initial = today
        self.fields["date_to"].initial = today

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get("date_from")
        date_to = cleaned.get("date_to")
        if date_from and date_to and date_from > date_to:
            self.add_error("date_to", "La fecha final no puede ser anterior a la inicial.")
        return cleaned
