from django import forms

from .models import CompanyConfig, Location, Unit, Warehouse


class CoreFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "h-4 w-4 rounded border-gray-300 text-orange-600 focus:ring-orange-500")
            else:
                widget.attrs.setdefault(
                    "class",
                    "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-200",
                )


class CompanyConfigForm(CoreFormMixin, forms.ModelForm):
    class Meta:
        model = CompanyConfig
        fields = [
            "ruc",
            "legal_name",
            "trade_name",
            "address",
            "establishment_code",
            "emission_point",
            "special_taxpayer",
            "obligated_accounting",
            "environment",
            "email_mode",
            "mp_shortage_tolerance_pct",
            "require_supplier_evaluation_for_purchase",
            "supplier_evaluation_approval_threshold",
            "supplier_evaluation_frequency_months",
            "critical_supplier_evaluation_frequency_months",
            "regulatory_agency",
            "regulatory_agency_full",
            "logo",
        ]


class UnitForm(CoreFormMixin, forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["code", "name", "category", "factor_to_base", "is_active"]


class WarehouseForm(CoreFormMixin, forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = [
            "code",
            "name",
            "type",
            "is_active",
            "is_default_quarantine",
            "is_default_for_raw",
            "is_default_fg_released",
        ]


class LocationForm(CoreFormMixin, forms.ModelForm):
    class Meta:
        model = Location
        fields = [
            "warehouse",
            "code",
            "name",
            "description",
            "row",
            "rack",
            "level",
            "max_units",
            "is_active",
        ]
