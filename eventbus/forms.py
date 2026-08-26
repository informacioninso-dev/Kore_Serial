from django import forms

from .models import EventSubscription, EventType


class EventBusFormMixin:
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


class EventTypeForm(EventBusFormMixin, forms.ModelForm):
    class Meta:
        model = EventType
        fields = ["code", "name", "domain", "description", "payload_keys", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "payload_keys": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payload_keys"].required = False
        self.fields["payload_keys"].help_text = 'Lista JSON. Ej: ["unit", "station", "line"]'


class EventSubscriptionForm(EventBusFormMixin, forms.ModelForm):
    class Meta:
        model = EventSubscription
        fields = ["code", "name", "event_type", "domain", "handler", "max_attempts", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event_type"].queryset = EventType.objects.filter(is_active=True).order_by(
            "domain", "code"
        )
        self.fields["event_type"].required = False
        self.fields["domain"].required = False
