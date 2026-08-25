from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from .forms import CompanyConfigForm, LocationForm, UnitForm, WarehouseForm
from .mixins import TenantAdminRequiredMixin
from .models import CompanyConfig, EquipmentIntegration, Location, Unit, Warehouse
from .system_info import get_system_release_info


PER_PAGE_CHOICES = (20, 50, 100)


def _per_page(request, default=20):
    try:
        per_page = int(request.GET.get("per_page", default))
    except (TypeError, ValueError):
        return default
    return per_page if per_page in PER_PAGE_CHOICES else default


def _yes_no(value):
    return {
        "label": "Activo" if value else "Inactivo",
        "tone": "success" if value else "neutral",
    }


class AuditSaveMixin:
    success_message = "Registro guardado."

    def form_valid(self, form):
        if not getattr(self, "object", None):
            form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return response


class SettingsDashboardView(LoginRequiredMixin, TenantAdminRequiredMixin, TemplateView):
    template_name = "core/settings.html"

    def get_context_data(self, **kwargs):
        from assembly.models import (
            AssembledProduct,
            AssemblyLine,
            AssemblyRoute,
            AssemblyRouteStep,
            AssemblyStation,
            Plant,
            PlantArea,
            ProductVersion,
            RouteStepParameter,
            RouteStepComponentRequirement,
        )

        context = super().get_context_data(**kwargs)
        company_config = CompanyConfig.objects.first()
        company_display = "Pendiente"
        if company_config is not None:
            company_display = company_config.trade_name or company_config.legal_name or "Pendiente"
        context.update(
            {
                "company_config": company_config,
                "company_display": company_display,
                "unit_count": Unit.objects.count(),
                "warehouse_count": Warehouse.objects.count(),
                "location_count": Location.objects.count(),
                "product_count": AssembledProduct.objects.count(),
                "version_count": ProductVersion.objects.count(),
                "plant_count": Plant.objects.count(),
                "area_count": PlantArea.objects.count(),
                "line_count": AssemblyLine.objects.count(),
                "station_count": AssemblyStation.objects.count(),
                "route_count": AssemblyRoute.objects.count(),
                "step_count": AssemblyRouteStep.objects.count(),
                "parameter_count": RouteStepParameter.objects.count(),
                "requirement_count": RouteStepComponentRequirement.objects.count(),
                "equipment_count": EquipmentIntegration.objects.count(),
            }
        )
        return context


class SystemInfoView(LoginRequiredMixin, TenantAdminRequiredMixin, TemplateView):
    template_name = "core/system_info.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "release": get_system_release_info(),
                "runtime_info_file": settings.KORE_RELEASE_INFO_FILE,
            }
        )
        return context


class CompanyConfigView(LoginRequiredMixin, TenantAdminRequiredMixin, AuditSaveMixin, UpdateView):
    model = CompanyConfig
    form_class = CompanyConfigForm
    template_name = "core/generic_form.html"
    success_url = reverse_lazy("core:settings")
    success_message = "Configuracion de empresa guardada."

    def get_object(self, queryset=None):
        config = CompanyConfig.objects.first()
        if config:
            return config
        tenant_name = getattr(getattr(self.request, "tenant", None), "name", "")
        return CompanyConfig.objects.create(
            ruc="0000000000000",
            legal_name=tenant_name or "Empresa",
            trade_name=tenant_name or "",
            address="Pendiente",
            created_by=self.request.user,
            updated_by=self.request.user,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "title": "Empresa",
                "subtitle": "Datos generales y parametros base del tenant.",
                "nav_key": "company",
                "back_url": reverse("core:settings"),
            }
        )
        return context


class ConfigListMixin(LoginRequiredMixin, TenantAdminRequiredMixin, ListView):
    template_name = "core/generic_list.html"
    context_object_name = "items"
    title = ""
    subtitle = ""
    nav_key = ""
    create_url_name = ""
    create_label = "Nuevo"
    update_url_name = ""
    columns = ()
    search_fields = ()
    search_placeholder = "Buscar"

    def get_paginate_by(self, queryset):
        return _per_page(self.request)

    def get_base_queryset(self):
        return self.model.objects.all()

    def get_queryset(self):
        queryset = self.get_base_queryset()
        q = self.request.GET.get("q", "").strip()
        if q and self.search_fields:
            query = Q()
            for field in self.search_fields:
                query |= Q(**{f"{field}__icontains": q})
            queryset = queryset.filter(query)
        return queryset

    def row_for(self, obj):
        return {"cells": [], "edit_url": ""}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "title": self.title,
                "subtitle": self.subtitle,
                "nav_key": self.nav_key,
                "columns": self.columns,
                "rows": [self.row_for(obj) for obj in context["object_list"]],
                "create_url": reverse(self.create_url_name),
                "create_label": self.create_label,
                "search_placeholder": self.search_placeholder,
                "per_page": self.get_paginate_by(None),
            }
        )
        return context


class ConfigFormMixin(LoginRequiredMixin, TenantAdminRequiredMixin, AuditSaveMixin):
    template_name = "core/generic_form.html"
    title = ""
    subtitle = ""
    nav_key = ""
    back_url_name = ""

    def get_success_url(self):
        return reverse(self.back_url_name)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "title": self.title,
                "subtitle": self.subtitle,
                "nav_key": self.nav_key,
                "back_url": reverse(self.back_url_name),
            }
        )
        return context


class UnitListView(ConfigListMixin):
    model = Unit
    title = "Unidades"
    subtitle = "Unidades de medida para partes, materiales y operaciones."
    nav_key = "units"
    create_url_name = "core:unit_create"
    create_label = "Nueva unidad"
    update_url_name = "core:unit_update"
    columns = ("Codigo", "Nombre", "Categoria", "Factor", "Estado")
    search_fields = ("code", "name")

    def get_base_queryset(self):
        return Unit.objects.order_by("code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name},
                {"primary": obj.get_category_display()},
                {"primary": obj.factor_to_base},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class UnitCreateView(ConfigFormMixin, CreateView):
    model = Unit
    form_class = UnitForm
    title = "Nueva unidad"
    subtitle = "Crea una unidad de medida base."
    nav_key = "units"
    back_url_name = "core:unit_list"
    success_message = "Unidad creada."


class UnitUpdateView(ConfigFormMixin, UpdateView):
    model = Unit
    form_class = UnitForm
    title = "Editar unidad"
    subtitle = "Actualiza la unidad de medida."
    nav_key = "units"
    back_url_name = "core:unit_list"
    success_message = "Unidad actualizada."


class WarehouseListView(ConfigListMixin):
    model = Warehouse
    title = "Bodegas"
    subtitle = "Bodegas y zonas logicas usadas por planta."
    nav_key = "warehouses"
    create_url_name = "core:warehouse_create"
    create_label = "Nueva bodega"
    update_url_name = "core:warehouse_update"
    columns = ("Codigo", "Bodega", "Tipo", "Predeterminada", "Estado")
    search_fields = ("code", "name")

    def get_base_queryset(self):
        return Warehouse.objects.order_by("code")

    def row_for(self, obj):
        defaults = []
        if obj.is_default_quarantine:
            defaults.append("Cuarentena")
        if obj.is_default_for_raw:
            defaults.append("Materia prima")
        if obj.is_default_fg_released:
            defaults.append("Liberado")
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name},
                {"primary": obj.get_type_display()},
                {"primary": ", ".join(defaults) or "-"},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class WarehouseCreateView(ConfigFormMixin, CreateView):
    model = Warehouse
    form_class = WarehouseForm
    title = "Nueva bodega"
    subtitle = "Crea una bodega o zona operativa."
    nav_key = "warehouses"
    back_url_name = "core:warehouse_list"
    success_message = "Bodega creada."


class WarehouseUpdateView(ConfigFormMixin, UpdateView):
    model = Warehouse
    form_class = WarehouseForm
    title = "Editar bodega"
    subtitle = "Actualiza los parametros de la bodega."
    nav_key = "warehouses"
    back_url_name = "core:warehouse_list"
    success_message = "Bodega actualizada."


class LocationListView(ConfigListMixin):
    model = Location
    title = "Ubicaciones"
    subtitle = "Ubicaciones internas por bodega."
    nav_key = "locations"
    create_url_name = "core:location_create"
    create_label = "Nueva ubicacion"
    update_url_name = "core:location_update"
    columns = ("Codigo", "Ubicacion", "Bodega", "Posicion", "Capacidad", "Estado")
    search_fields = ("code", "name", "warehouse__code", "warehouse__name")

    def get_base_queryset(self):
        return Location.objects.select_related("warehouse").order_by("warehouse__code", "code")

    def row_for(self, obj):
        position = " / ".join(part for part in [obj.row, obj.rack, obj.level] if part)
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name or "-", "secondary": obj.description},
                {"primary": obj.warehouse.name, "secondary": obj.warehouse.code},
                {"primary": position or "-"},
                {"primary": obj.max_units or "-"},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class LocationCreateView(ConfigFormMixin, CreateView):
    model = Location
    form_class = LocationForm
    title = "Nueva ubicacion"
    subtitle = "Crea una ubicacion dentro de una bodega."
    nav_key = "locations"
    back_url_name = "core:location_list"
    success_message = "Ubicacion creada."


class LocationUpdateView(ConfigFormMixin, UpdateView):
    model = Location
    form_class = LocationForm
    title = "Editar ubicacion"
    subtitle = "Actualiza la ubicacion fisica o logica."
    nav_key = "locations"
    back_url_name = "core:location_list"
    success_message = "Ubicacion actualizada."
