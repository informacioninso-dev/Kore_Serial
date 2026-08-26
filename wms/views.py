from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from core.mixins import ModulePermissionMixin
from core.models import Location
from core.views import AuditSaveMixin

from .forms import (
    AssemblyKitForm,
    AssemblyKitLineForm,
    InboundReceiptForm,
    InboundReceiptLineForm,
    InventoryOperationForm,
    KanbanSignalCreateForm,
    MaterialCategoryForm,
    MaterialForm,
    PickMissionForm,
    PickTaskForm,
    ReceiveReceiptLineForm,
    ReplenishmentRuleForm,
    WmsLocationProfileForm,
)
from .models import (
    AssemblyKit,
    AssemblyKitLine,
    AssemblyKitStatus,
    InboundReceipt,
    InboundReceiptLine,
    InventoryBalance,
    InventoryMovement,
    InventoryMovementType,
    InventoryState,
    LocationOperationalType,
    Material,
    MaterialCategory,
    KanbanSignal,
    KanbanSignalStatus,
    PickMission,
    PickMissionStatus,
    PickTask,
    PickTaskStatus,
    ReplenishmentRule,
    WmsLocationProfile,
)
from .services import (
    adjust_inventory,
    change_inventory_state,
    complete_pick_task,
    create_kanban_pick_mission,
    create_kanban_signal,
    create_pick_mission,
    deliver_kit,
    fulfill_kanban_signal,
    receive_receipt_line,
    release_kit,
    release_pick_mission,
    transfer_inventory,
)


PER_PAGE_CHOICES = (20, 50, 100)


def _per_page(request, default=20):
    try:
        value = int(request.GET.get("per_page", default))
    except (TypeError, ValueError):
        return default
    return value if value in PER_PAGE_CHOICES else default


def _badge(value, label):
    tones = {
        "AVAILABLE": "success",
        "RECEIVED": "success",
        "QUARANTINE": "warning",
        "BLOCKED": "danger",
        "SCRAP": "danger",
        "CANCELLED": "neutral",
        "DRAFT": "neutral",
        "RELEASED": "warning",
        "IN_PROGRESS": "warning",
        "PENDING": "warning",
        "READY": "success",
        "DELIVERED": "success",
        "COMPLETED": "success",
        "PICKED": "success",
        "FULFILLED": "success",
    }
    return {"label": label, "tone": tones.get(value, "neutral")}


class WMSListMixin(LoginRequiredMixin, ModulePermissionMixin, ListView):
    template_name = "assembly/generic_list.html"
    context_object_name = "items"
    title = ""
    subtitle = ""
    nav_key = ""
    create_url_name = ""
    create_label = "Nuevo"
    create_permission = ""
    update_url_name = ""
    search_fields = ()
    filter_specs = ()
    columns = ()
    search_placeholder = "Buscar"

    def get_paginate_by(self, queryset):
        return _per_page(self.request)

    def get_base_queryset(self):
        return self.model.objects.all()

    def get_queryset(self):
        queryset = self.get_base_queryset()
        q = self.request.GET.get("q", "").strip()
        if q:
            query = Q()
            for field in self.search_fields:
                query |= Q(**{f"{field}__icontains": q})
            queryset = queryset.filter(query)
        for spec in self.filter_specs:
            value = self.request.GET.get(spec["param"], "").strip()
            if value:
                queryset = queryset.filter(**{spec["field"]: value})
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
                "nav_template": "wms/_nav.html",
                "columns": self.columns,
                "rows": [self.row_for(obj) for obj in context["object_list"]],
                "create_url": reverse(self.create_url_name) if self.create_url_name else "",
                "create_label": self.create_label,
                "can_create": bool(self.create_permission and self.request.user.has_perm(self.create_permission)),
                "search_placeholder": self.search_placeholder,
                "filter_specs": self.filter_specs,
                "per_page": self.get_paginate_by(None),
            }
        )
        return context


class WMSFormMixin(LoginRequiredMixin, ModulePermissionMixin, AuditSaveMixin):
    template_name = "assembly/generic_form.html"
    title = ""
    subtitle = ""
    nav_key = ""
    back_url_name = ""

    def get_success_url(self):
        return reverse(self.back_url_name)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {"title": self.title, "subtitle": self.subtitle, "nav_key": self.nav_key, "nav_template": "wms/_nav.html", "back_url": reverse(self.back_url_name)}
        )
        return context


class WMSDashboardView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    template_name = "wms/dashboard.html"
    permission_required = "wms.view_inventorybalance"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "material_count": Material.objects.filter(is_active=True).count(),
                "receipt_count": InboundReceipt.objects.count(),
                "quarantine_quantity": InventoryBalance.objects.filter(state=InventoryState.QUARANTINE).aggregate(total=Sum("quantity"))["total"] or 0,
                "available_quantity": InventoryBalance.objects.filter(state=InventoryState.AVAILABLE).aggregate(total=Sum("quantity"))["total"] or 0,
                "open_kanban_count": KanbanSignal.objects.filter(status__in=[KanbanSignalStatus.OPEN, KanbanSignalStatus.IN_PROGRESS]).count(),
                "open_pick_count": PickMission.objects.filter(status__in=[PickMissionStatus.RELEASED, PickMissionStatus.IN_PROGRESS]).count(),
                "recent_movements": InventoryMovement.objects.select_related("material", "source_location", "destination_location").all()[:8],
            }
        )
        return context


class MaterialCategoryListView(WMSListMixin):
    model = MaterialCategory
    permission_required = "wms.view_materialcategory"
    create_permission = "wms.add_materialcategory"
    create_url_name = "wms:category_create"
    update_url_name = "wms:category_update"
    title = "Categorias de materiales"
    subtitle = "Clasifica los materiales operativos del WMS."
    nav_key = "categories"
    columns = ("Codigo", "Categoria", "Estado")
    search_fields = ("code", "name")

    def row_for(self, obj):
        return {"cells": [{"primary": obj.code}, {"primary": obj.name}, {"badge": _badge("AVAILABLE" if obj.is_active else "", "Activa" if obj.is_active else "Inactiva")}], "edit_url": reverse(self.update_url_name, args=[obj.pk])}


class MaterialCategoryCreateView(WMSFormMixin, CreateView):
    model = MaterialCategory
    form_class = MaterialCategoryForm
    permission_required = "wms.add_materialcategory"
    title = "Nueva categoria"
    subtitle = "Crea una categoria de material."
    nav_key = "categories"
    back_url_name = "wms:category_list"


class MaterialCategoryUpdateView(WMSFormMixin, UpdateView):
    model = MaterialCategory
    form_class = MaterialCategoryForm
    permission_required = "wms.change_materialcategory"
    title = "Editar categoria"
    subtitle = "Actualiza la categoria de material."
    nav_key = "categories"
    back_url_name = "wms:category_list"


class MaterialListView(WMSListMixin):
    model = Material
    permission_required = "wms.view_material"
    create_permission = "wms.add_material"
    create_url_name = "wms:material_create"
    update_url_name = "wms:material_update"
    title = "Materiales"
    subtitle = "Catalogo de partes CKD, consumibles y politicas de trazabilidad."
    nav_key = "materials"
    columns = ("Codigo", "Material", "Unidad", "Trazabilidad", "Estado")
    search_fields = ("code", "name", "description")
    filter_specs = ({"param": "traceability", "field": "traceability", "label": "Trazabilidad", "choices": Material._meta.get_field("traceability").choices},)

    def get_base_queryset(self):
        return Material.objects.select_related("category", "base_unit").order_by("code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name, "secondary": obj.category.name if obj.category_id else "Sin categoria"},
                {"primary": obj.base_unit.code},
                {"primary": obj.get_traceability_display()},
                {"badge": _badge("AVAILABLE" if obj.is_active else "", "Activo" if obj.is_active else "Inactivo")},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class MaterialCreateView(WMSFormMixin, CreateView):
    model = Material
    form_class = MaterialForm
    permission_required = "wms.add_material"
    title = "Nuevo material"
    subtitle = "Define la unidad base y trazabilidad operativa."
    nav_key = "materials"
    back_url_name = "wms:material_list"


class MaterialUpdateView(WMSFormMixin, UpdateView):
    model = Material
    form_class = MaterialForm
    permission_required = "wms.change_material"
    title = "Editar material"
    subtitle = "Actualiza el maestro de material."
    nav_key = "materials"
    back_url_name = "wms:material_list"


class LocationProfileListView(WMSListMixin):
    model = WmsLocationProfile
    permission_required = "wms.view_wmslocationprofile"
    create_permission = "wms.add_wmslocationprofile"
    create_url_name = "wms:location_profile_create"
    update_url_name = "wms:location_profile_update"
    title = "Perfiles de ubicacion"
    subtitle = "Clasifica ubicaciones existentes para la operacion WMS."
    nav_key = "locations"
    columns = ("Ubicacion", "Bodega", "Tipo operativo", "Mezcla", "Estado")
    search_fields = ("location__code", "location__name", "location__warehouse__code")
    filter_specs = ({"param": "type", "field": "operational_type", "label": "Tipo", "choices": LocationOperationalType.choices},)

    def get_base_queryset(self):
        return WmsLocationProfile.objects.select_related("location__warehouse").order_by("location__warehouse__code", "location__code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.location.code, "secondary": obj.location.name or ""},
                {"primary": obj.location.warehouse.code},
                {"primary": obj.get_operational_type_display()},
                {"primary": "Permitida" if obj.allows_mixed_materials else "No permitida"},
                {"badge": _badge("AVAILABLE" if obj.is_active else "", "Activo" if obj.is_active else "Inactivo")},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class LocationProfileCreateView(WMSFormMixin, CreateView):
    model = WmsLocationProfile
    form_class = WmsLocationProfileForm
    permission_required = "wms.add_wmslocationprofile"
    title = "Nuevo perfil WMS"
    subtitle = "Asigna comportamiento operativo a una ubicacion existente."
    nav_key = "locations"
    back_url_name = "wms:location_profile_list"


class LocationProfileUpdateView(WMSFormMixin, UpdateView):
    model = WmsLocationProfile
    form_class = WmsLocationProfileForm
    permission_required = "wms.change_wmslocationprofile"
    title = "Editar perfil WMS"
    subtitle = "Actualiza el comportamiento operativo de la ubicacion."
    nav_key = "locations"
    back_url_name = "wms:location_profile_list"


class InboundReceiptListView(WMSListMixin):
    model = InboundReceipt
    permission_required = "wms.view_inboundreceipt"
    create_permission = "wms.add_inboundreceipt"
    create_url_name = "wms:receipt_create"
    update_url_name = "wms:receipt_update"
    title = "Recepciones CKD"
    subtitle = "Contenedores, ASN y materiales recibidos a planta."
    nav_key = "receipts"
    columns = ("Recepcion", "Proveedor / contenedor", "Destino", "Fecha", "Estado")
    search_fields = ("code", "supplier_name", "container_number", "asn_reference")
    filter_specs = ({"param": "status", "field": "status", "label": "Estado", "choices": InboundReceipt._meta.get_field("status").choices},)

    def get_base_queryset(self):
        return InboundReceipt.objects.select_related("destination_location__warehouse").order_by("-received_at", "-id")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code, "secondary": obj.asn_reference},
                {"primary": obj.supplier_name or "-", "secondary": obj.container_number},
                {"primary": obj.destination_location.code, "secondary": obj.destination_location.warehouse.code},
                {"primary": obj.received_at.strftime("%d/%m/%Y %H:%M")},
                {"badge": _badge(obj.status, obj.get_status_display())},
            ],
            "action_url": reverse("wms:receipt_detail", args=[obj.pk]),
            "action_label": "Ver",
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class InboundReceiptCreateView(WMSFormMixin, CreateView):
    model = InboundReceipt
    form_class = InboundReceiptForm
    permission_required = "wms.add_inboundreceipt"
    title = "Nueva recepcion CKD"
    subtitle = "Registra el contenedor o ASN antes de recibir sus materiales."
    nav_key = "receipts"
    back_url_name = "wms:receipt_list"

    def get_success_url(self):
        return reverse("wms:receipt_detail", args=[self.object.pk])


class InboundReceiptUpdateView(WMSFormMixin, UpdateView):
    model = InboundReceipt
    form_class = InboundReceiptForm
    permission_required = "wms.change_inboundreceipt"
    title = "Editar recepcion CKD"
    subtitle = "Actualiza los datos documentales de la recepcion."
    nav_key = "receipts"
    back_url_name = "wms:receipt_list"


class InboundReceiptDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = InboundReceipt
    template_name = "wms/receipt_detail.html"
    context_object_name = "receipt"
    permission_required = "wms.view_inboundreceipt"

    def get_queryset(self):
        return InboundReceipt.objects.select_related("destination_location__warehouse").prefetch_related("lines__material__base_unit")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "nav_key": "receipts",
                "can_add_line": self.request.user.has_perm("wms.add_inboundreceiptline"),
                "can_receive": self.request.user.has_perm("wms.add_inventorymovement"),
            }
        )
        return context


class InboundReceiptLineCreateView(WMSFormMixin, CreateView):
    model = InboundReceiptLine
    form_class = InboundReceiptLineForm
    permission_required = "wms.add_inboundreceiptline"
    title = "Nueva linea de recepcion"
    subtitle = "Agrega un material esperado en el contenedor o ASN."
    nav_key = "receipts"
    back_url_name = "wms:receipt_list"

    def dispatch(self, request, *args, **kwargs):
        self.receipt = get_object_or_404(InboundReceipt, pk=kwargs["receipt_pk"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.receipt = self.receipt
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("wms:receipt_detail", args=[self.receipt.pk])


class ReceiveReceiptLineView(LoginRequiredMixin, ModulePermissionMixin, FormView):
    template_name = "wms/receipt_line_receive.html"
    form_class = ReceiveReceiptLineForm
    permission_required = "wms.add_inventorymovement"

    def dispatch(self, request, *args, **kwargs):
        self.line = get_object_or_404(InboundReceiptLine.objects.select_related("receipt", "material"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"line": self.line, "receipt": self.line.receipt, "nav_key": "receipts"})
        return context

    def form_valid(self, form):
        try:
            receive_receipt_line(
                actor=self.request.user,
                receipt_line=self.line,
                quantity=form.cleaned_data["quantity"],
                lot_number=form.cleaned_data["lot_number"],
                serial_numbers=form.serial_list(),
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "Material recibido a cuarentena y registrado en inventario.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("wms:receipt_detail", args=[self.line.receipt_id])


class InventoryBalanceListView(WMSListMixin):
    model = InventoryBalance
    permission_required = "wms.view_inventorybalance"
    title = "Inventario"
    subtitle = "Saldo actual por material, ubicacion, estado, lote o serie."
    nav_key = "inventory"
    columns = ("Material", "Ubicacion", "Estado", "Trazabilidad", "Saldo")
    search_fields = ("material__code", "material__name", "location__code", "lot__number", "serial__number")
    filter_specs = ({"param": "state", "field": "state", "label": "Estado", "choices": InventoryState.choices},)

    def get_base_queryset(self):
        return InventoryBalance.objects.select_related("material__base_unit", "location__warehouse", "lot", "serial").order_by(
            "material__code", "location__warehouse__code", "location__code", "state", "id"
        )

    def row_for(self, obj):
        trace = obj.serial.number if obj.serial_id else (obj.lot.number if obj.lot_id else "-")
        trace_label = "Serie" if obj.serial_id else ("Lote" if obj.lot_id else "Sin trazabilidad")
        return {
            "cells": [
                {"primary": obj.material.code, "secondary": obj.material.name},
                {"primary": obj.location.code, "secondary": obj.location.warehouse.code},
                {"badge": _badge(obj.state, obj.get_state_display())},
                {"primary": trace, "secondary": trace_label},
                {"primary": f"{obj.quantity} {obj.material.base_unit.code}"},
            ]
        }


class InventoryMovementListView(WMSListMixin):
    model = InventoryMovement
    permission_required = "wms.view_inventorymovement"
    create_permission = "wms.add_inventorymovement"
    create_url_name = "wms:movement_create"
    create_label = "Nuevo movimiento"
    title = "Movimientos de inventario"
    subtitle = "Libro inmutable de recepciones, traslados, estados y ajustes."
    nav_key = "movements"
    columns = ("Fecha", "Tipo", "Material", "Origen", "Destino", "Cantidad")
    search_fields = ("material__code", "material__name", "lot__number", "serial__number", "external_reference", "reason")
    filter_specs = ({"param": "type", "field": "movement_type", "label": "Tipo", "choices": InventoryMovementType.choices},)

    def get_base_queryset(self):
        return InventoryMovement.objects.select_related("material__base_unit", "source_location", "destination_location", "lot", "serial").order_by(
            "-moved_at", "-id"
        )

    def row_for(self, obj):
        origin = obj.source_location.code if obj.source_location_id else "-"
        if obj.source_state:
            origin = f"{origin} / {obj.get_source_state_display()}"
        destination = obj.destination_location.code if obj.destination_location_id else "-"
        if obj.destination_state:
            destination = f"{destination} / {obj.get_destination_state_display()}"
        return {
            "cells": [
                {"primary": obj.moved_at.strftime("%d/%m/%Y %H:%M")},
                {"primary": obj.get_movement_type_display()},
                {"primary": obj.material.code, "secondary": obj.serial.number if obj.serial_id else (obj.lot.number if obj.lot_id else "")},
                {"primary": origin},
                {"primary": destination},
                {"primary": f"{obj.quantity} {obj.material.base_unit.code}"},
            ]
        }


class InventoryOperationCreateView(LoginRequiredMixin, ModulePermissionMixin, FormView):
    template_name = "wms/inventory_operation_form.html"
    form_class = InventoryOperationForm
    permission_required = "wms.add_inventorymovement"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"title": "Nuevo movimiento", "subtitle": "Traslada, cambia estado o ajusta inventario con evidencia.", "nav_key": "movements"})
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            if data["operation"] == InventoryOperationForm.OPERATION_TRANSFER:
                transfer_inventory(
                    actor=self.request.user,
                    material=data["material"],
                    quantity=data["quantity"],
                    source_location=data["source_location"],
                    destination_location=data["destination_location"],
                    state=data["source_state"],
                    lot=data["lot"],
                    serial=data["serial"],
                    reason=data["reason"],
                )
            elif data["operation"] == InventoryOperationForm.OPERATION_STATE:
                change_inventory_state(
                    actor=self.request.user,
                    material=data["material"],
                    quantity=data["quantity"],
                    location=data["source_location"],
                    source_state=data["source_state"],
                    destination_state=data["destination_state"],
                    lot=data["lot"],
                    serial=data["serial"],
                    reason=data["reason"],
                )
            else:
                adjust_inventory(
                    actor=self.request.user,
                    material=data["material"],
                    quantity=data["quantity"],
                    location=data["destination_location"] if data["operation"] == InventoryOperationForm.OPERATION_ADJUST_IN else data["source_location"],
                    state=data["destination_state"] if data["operation"] == InventoryOperationForm.OPERATION_ADJUST_IN else data["source_state"],
                    direction="IN" if data["operation"] == InventoryOperationForm.OPERATION_ADJUST_IN else "OUT",
                    lot=data["lot"],
                    serial=data["serial"],
                    reason=data["reason"],
                )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "Movimiento registrado y saldo actualizado.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("wms:movement_list")


class AssemblyKitListView(WMSListMixin):
    model = AssemblyKit
    permission_required = "wms.view_assemblykit"
    create_permission = "wms.add_assemblykit"
    create_url_name = "wms:kit_create"
    update_url_name = "wms:kit_update"
    title = "Kits de linea"
    subtitle = "Materiales preparados para un plan o una unidad serializada, sin consumo automatico."
    nav_key = "kits"
    columns = ("Kit", "Destino", "Estacion", "Objetivo", "Estado")
    search_fields = ("code", "production_plan__code", "serialized_unit__serial_number", "destination_location__code", "station__code")
    filter_specs = ({"param": "status", "field": "status", "label": "Estado", "choices": AssemblyKitStatus.choices},)

    def get_base_queryset(self):
        return AssemblyKit.objects.select_related("production_plan", "serialized_unit", "destination_location__warehouse", "station").order_by("-created_at", "code")

    def row_for(self, obj):
        objective = obj.production_plan.code if obj.production_plan_id else obj.serialized_unit.serial_number
        return {
            "cells": [
                {"primary": obj.code, "secondary": f"{obj.lines.count()} lineas"},
                {"primary": obj.destination_location.code, "secondary": obj.destination_location.warehouse.code},
                {"primary": obj.station.code if obj.station_id else "-"},
                {"primary": objective, "secondary": "Plan" if obj.production_plan_id else "Unidad"},
                {"badge": _badge(obj.status, obj.get_status_display())},
            ],
            "action_url": reverse("wms:kit_detail", args=[obj.pk]),
            "action_label": "Ver",
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if obj.status == AssemblyKitStatus.DRAFT else "",
        }


class AssemblyKitCreateView(WMSFormMixin, CreateView):
    model = AssemblyKit
    form_class = AssemblyKitForm
    permission_required = "wms.add_assemblykit"
    title = "Nuevo kit de linea"
    subtitle = "Define el destino logistico para un plan o una unidad serializada."
    nav_key = "kits"
    back_url_name = "wms:kit_list"

    def get_success_url(self):
        return reverse("wms:kit_detail", args=[self.object.pk])


class AssemblyKitUpdateView(WMSFormMixin, UpdateView):
    model = AssemblyKit
    form_class = AssemblyKitForm
    permission_required = "wms.change_assemblykit"
    title = "Editar kit de linea"
    subtitle = "Los kits liberados ya no admiten cambios de cabecera."
    nav_key = "kits"
    back_url_name = "wms:kit_list"

    def get_queryset(self):
        return AssemblyKit.objects.filter(status=AssemblyKitStatus.DRAFT)


class AssemblyKitDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = AssemblyKit
    template_name = "wms/kit_detail.html"
    context_object_name = "kit"
    permission_required = "wms.view_assemblykit"

    def get_queryset(self):
        return AssemblyKit.objects.select_related("production_plan", "serialized_unit", "destination_location__warehouse", "station").prefetch_related("lines__material__base_unit", "lines__pick_tasks", "pick_missions")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "nav_key": "kits",
                "can_add_line": self.request.user.has_perm("wms.add_assemblykitline") and self.object.status == AssemblyKitStatus.DRAFT,
                "can_release": self.request.user.has_perm("wms.change_assemblykit") and self.object.status == AssemblyKitStatus.DRAFT,
                "can_deliver": self.request.user.has_perm("wms.change_assemblykit") and self.object.status == AssemblyKitStatus.READY,
                "can_create_mission": self.request.user.has_perm("wms.add_pickmission") and self.object.status in {AssemblyKitStatus.RELEASED, AssemblyKitStatus.READY},
            }
        )
        return context


class AssemblyKitLineCreateView(WMSFormMixin, CreateView):
    model = AssemblyKitLine
    form_class = AssemblyKitLineForm
    permission_required = "wms.add_assemblykitline"
    title = "Nueva linea de kit"
    subtitle = "Define la cantidad requerida antes de liberar el kit."
    nav_key = "kits"
    back_url_name = "wms:kit_list"

    def dispatch(self, request, *args, **kwargs):
        self.kit = get_object_or_404(AssemblyKit, pk=kwargs["kit_pk"], status=AssemblyKitStatus.DRAFT)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.kit = self.kit
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("wms:kit_detail", args=[self.kit.pk])


class KitActionView(LoginRequiredMixin, ModulePermissionMixin, FormView):
    form_class = None
    permission_required = "wms.change_assemblykit"

    def post(self, request, *args, **kwargs):
        kit = get_object_or_404(AssemblyKit, pk=kwargs["pk"])
        try:
            if kwargs["action"] == "release":
                release_kit(actor=request.user, kit=kit)
                message = "Kit liberado para picking."
            else:
                deliver_kit(actor=request.user, kit=kit)
                message = "Kit entregado a estacion."
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, message)
        return self._redirect(kit)

    def _redirect(self, kit):
        from django.shortcuts import redirect

        return redirect("wms:kit_detail", pk=kit.pk)


class PickMissionListView(WMSListMixin):
    model = PickMission
    permission_required = "wms.view_pickmission"
    create_permission = "wms.add_pickmission"
    create_url_name = "wms:pick_mission_create"
    title = "Misiones de picking"
    subtitle = "Traslados controlados desde bodega hacia supermercado o line side."
    nav_key = "picking"
    columns = ("Mision", "Origen", "Destino", "Kit", "Estado")
    search_fields = ("code", "kit__code", "source_location__code", "destination_location__code")
    filter_specs = ({"param": "status", "field": "status", "label": "Estado", "choices": PickMissionStatus.choices},)

    def get_base_queryset(self):
        return PickMission.objects.select_related("kit", "source_location__warehouse", "destination_location__warehouse").prefetch_related("tasks").order_by("-created_at", "code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code, "secondary": f"{obj.tasks.count()} tareas"},
                {"primary": obj.source_location.code, "secondary": obj.source_location.warehouse.code},
                {"primary": obj.destination_location.code, "secondary": obj.destination_location.warehouse.code},
                {"primary": obj.kit.code if obj.kit_id else "Reposicion directa"},
                {"badge": _badge(obj.status, obj.get_status_display())},
            ],
            "action_url": reverse("wms:pick_mission_detail", args=[obj.pk]),
            "action_label": "Ver",
        }


class PickMissionCreateView(LoginRequiredMixin, ModulePermissionMixin, FormView):
    template_name = "assembly/generic_form.html"
    form_class = PickMissionForm
    permission_required = "wms.add_pickmission"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"title": "Nueva mision de picking", "subtitle": "Crea una mision antes de cargar sus tareas.", "nav_key": "picking", "nav_template": "wms/_nav.html", "back_url": reverse("wms:pick_mission_list")})
        return context

    def get_initial(self):
        initial = super().get_initial()
        kit_id = self.request.GET.get("kit", "").strip()
        if kit_id.isdigit():
            initial["kit"] = kit_id
            kit = AssemblyKit.objects.filter(pk=kit_id, status=AssemblyKitStatus.RELEASED).first()
            if kit:
                initial["destination_location"] = kit.destination_location_id
        return initial

    def form_valid(self, form):
        try:
            mission = create_pick_mission(actor=self.request.user, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        return self._redirect(mission)

    def _redirect(self, mission):
        from django.shortcuts import redirect

        return redirect("wms:pick_mission_detail", pk=mission.pk)


class PickMissionDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = PickMission
    template_name = "wms/pick_mission_detail.html"
    context_object_name = "mission"
    permission_required = "wms.view_pickmission"

    def get_queryset(self):
        return PickMission.objects.select_related("kit", "source_location__warehouse", "destination_location__warehouse").prefetch_related("tasks__material__base_unit", "tasks__lot", "tasks__serial")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "nav_key": "picking",
                "can_add_task": self.request.user.has_perm("wms.add_picktask") and self.object.status == PickMissionStatus.DRAFT,
                "can_release": self.request.user.has_perm("wms.change_pickmission") and self.object.status == PickMissionStatus.DRAFT,
                "can_pick": self.request.user.has_perm("wms.add_inventorymovement") and self.object.status in {PickMissionStatus.RELEASED, PickMissionStatus.IN_PROGRESS},
            }
        )
        return context


class PickTaskCreateView(WMSFormMixin, CreateView):
    model = PickTask
    form_class = PickTaskForm
    permission_required = "wms.add_picktask"
    title = "Nueva tarea de picking"
    subtitle = "Identifica lote o serie cuando el material lo requiere."
    nav_key = "picking"
    back_url_name = "wms:pick_mission_list"

    def dispatch(self, request, *args, **kwargs):
        self.mission = get_object_or_404(PickMission, pk=kwargs["mission_pk"], status=PickMissionStatus.DRAFT)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["mission"] = self.mission
        return kwargs

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.instance.mission = self.mission
        return form

    def form_valid(self, form):
        form.instance.mission = self.mission
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("wms:pick_mission_detail", args=[self.mission.pk])


class PickMissionActionView(LoginRequiredMixin, ModulePermissionMixin, FormView):
    form_class = None
    permission_required = "wms.view_pickmission"

    def post(self, request, *args, **kwargs):
        mission = get_object_or_404(PickMission, pk=kwargs["pk"])
        action = kwargs["action"]
        try:
            if action == "release":
                if not request.user.has_perm("wms.change_pickmission"):
                    return self.handle_no_permission()
                release_pick_mission(actor=request.user, mission=mission)
                message = "Mision liberada para picking."
            else:
                if not request.user.has_perm("wms.add_inventorymovement"):
                    return self.handle_no_permission()
                task = get_object_or_404(PickTask, pk=kwargs["task_pk"], mission=mission)
                complete_pick_task(actor=request.user, task=task)
                message = "Tarea recogida y traslado registrado."
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, message)
        from django.shortcuts import redirect

        return redirect("wms:pick_mission_detail", pk=mission.pk)


class ReplenishmentRuleListView(WMSListMixin):
    model = ReplenishmentRule
    permission_required = "wms.view_replenishmentrule"
    create_permission = "wms.add_replenishmentrule"
    create_url_name = "wms:replenishment_rule_create"
    update_url_name = "wms:replenishment_rule_update"
    title = "Reposicion min/max"
    subtitle = "Reglas para supermercado y line side que disparan Kanban digital."
    nav_key = "kanban"
    columns = ("Regla", "Material", "Origen", "Destino", "Min / Max")
    search_fields = ("code", "material__code", "material__name", "source_location__code", "destination_location__code")
    filter_specs = ({"param": "active", "field": "is_active", "label": "Estado", "choices": (("True", "Activa"), ("False", "Inactiva"))},)

    def get_base_queryset(self):
        return ReplenishmentRule.objects.select_related("material__base_unit", "source_location", "destination_location").order_by("code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code, "secondary": "Activa" if obj.is_active else "Inactiva"},
                {"primary": obj.material.code, "secondary": obj.material.name},
                {"primary": obj.source_location.code},
                {"primary": obj.destination_location.code},
                {"primary": f"{obj.minimum_quantity} / {obj.maximum_quantity} {obj.material.base_unit.code}"},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class ReplenishmentRuleCreateView(WMSFormMixin, CreateView):
    model = ReplenishmentRule
    form_class = ReplenishmentRuleForm
    permission_required = "wms.add_replenishmentrule"
    title = "Nueva regla min/max"
    subtitle = "Define cuando reponer y hasta que nivel en la linea."
    nav_key = "kanban"
    back_url_name = "wms:replenishment_rule_list"


class ReplenishmentRuleUpdateView(WMSFormMixin, UpdateView):
    model = ReplenishmentRule
    form_class = ReplenishmentRuleForm
    permission_required = "wms.change_replenishmentrule"
    title = "Editar regla min/max"
    subtitle = "Actualiza el abastecimiento de supermercado o line side."
    nav_key = "kanban"
    back_url_name = "wms:replenishment_rule_list"


class KanbanSignalListView(WMSListMixin):
    model = KanbanSignal
    permission_required = "wms.view_kanbansignal"
    title = "Kanban digital"
    subtitle = "Senales por saldo bajo minimo y sus misiones de reposicion."
    nav_key = "kanban"
    columns = ("Senal", "Material", "Destino", "Solicitada", "Estado")
    search_fields = ("code", "rule__code", "rule__material__code", "rule__destination_location__code")
    filter_specs = ({"param": "status", "field": "status", "label": "Estado", "choices": KanbanSignalStatus.choices},)

    def get_base_queryset(self):
        return KanbanSignal.objects.select_related("rule__material__base_unit", "rule__destination_location", "pick_mission").order_by("-created_at", "-id")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code, "secondary": obj.rule.code},
                {"primary": obj.rule.material.code, "secondary": obj.pick_mission.code if obj.pick_mission_id else "Sin mision"},
                {"primary": obj.rule.destination_location.code},
                {"primary": f"{obj.requested_quantity} {obj.rule.material.base_unit.code}"},
                {"badge": _badge(obj.status, obj.get_status_display())},
            ],
            "action_url": reverse("wms:kanban_signal_detail", args=[obj.pk]),
            "action_label": "Ver",
        }


class KanbanSignalDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = KanbanSignal
    template_name = "wms/kanban_signal_detail.html"
    context_object_name = "signal"
    permission_required = "wms.view_kanbansignal"

    def get_queryset(self):
        return KanbanSignal.objects.select_related("rule__material__base_unit", "rule__source_location", "rule__destination_location", "pick_mission")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"nav_key": "kanban", "can_start": self.request.user.has_perm("wms.add_pickmission") and self.object.status == KanbanSignalStatus.OPEN, "can_fulfill": self.request.user.has_perm("wms.change_kanbansignal") and self.object.status == KanbanSignalStatus.IN_PROGRESS})
        return context


class KanbanSignalActionView(LoginRequiredMixin, ModulePermissionMixin, FormView):
    form_class = None
    permission_required = "wms.view_kanbansignal"

    def post(self, request, *args, **kwargs):
        signal = get_object_or_404(KanbanSignal, pk=kwargs["pk"])
        try:
            if kwargs["action"] == "start":
                if not request.user.has_perm("wms.add_pickmission"):
                    return self.handle_no_permission()
                mission = create_kanban_pick_mission(actor=request.user, signal=signal)
                message = f"Mision {mission.code} creada para la reposicion."
            else:
                if not request.user.has_perm("wms.change_kanbansignal"):
                    return self.handle_no_permission()
                fulfill_kanban_signal(actor=request.user, signal=signal)
                message = "Senal Kanban atendida."
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, message)
        from django.shortcuts import redirect

        return redirect("wms:kanban_signal_detail", pk=signal.pk)


class KanbanSignalCreateView(LoginRequiredMixin, ModulePermissionMixin, FormView):
    template_name = "wms/kanban_signal_create.html"
    form_class = KanbanSignalCreateForm
    permission_required = "wms.add_kanbansignal"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"title": "Nueva senal Kanban", "nav_key": "kanban"})
        return context

    def form_valid(self, form):
        try:
            signal = create_kanban_signal(actor=self.request.user, rule=form.cleaned_data["rule"], reason=form.cleaned_data["reason"])
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        from django.shortcuts import redirect

        return redirect("wms:kanban_signal_detail", pk=signal.pk)
