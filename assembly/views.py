from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from core.mixins import ModulePermissionMixin
from core.models import ApprovalStatus, EquipmentIntegration

from .forms import (
    AssembledProductForm,
    AssemblyLineForm,
    AssemblyRouteForm,
    AssemblyRouteStepForm,
    AssemblyStationForm,
    EquipmentIntegrationForm,
    InstalledComponentForm,
    ProductVersionForm,
    ProductionPlanActionForm,
    ProductionPlanForm,
    ProductionQueueActionForm,
    ProductionQueueItemForm,
    QualityGateDecisionForm,
    QualityGateForm,
    ReleaseApprovalForm,
    ReworkActionForm,
    ReworkOrderForm,
    RouteStepComponentRequirementForm,
    SerializedUnitForm,
    UnitStationEventForm,
)
from .models import (
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    ComponentTraceability,
    InstalledComponent,
    ProductVersion,
    ProductionPlan,
    ProductionPlanStatus,
    ProductionQueueItem,
    ProductionQueueStatus,
    QualityGate,
    QualityGateStatus,
    ReleaseApproval,
    ReleaseDecision,
    ReworkOrder,
    ReworkStatus,
    RouteStepComponentRequirement,
    SerializedUnit,
    StationEventType,
    StationEventSource,
    UnitStationEvent,
    UnitStatus,
)


PER_PAGE_CHOICES = (20, 50, 100)
CONFIGURATION_NAV_KEYS = {
    "products",
    "versions",
    "lines",
    "stations",
    "routes",
    "steps",
    "requirements",
    "equipment",
}


def _per_page(request, default=20):
    try:
        per_page = int(request.GET.get("per_page", default))
    except (TypeError, ValueError):
        return default
    return per_page if per_page in PER_PAGE_CHOICES else default


def _status_badge(value, label=None):
    label = label or value or "-"
    normalized = str(value or "").upper()
    if normalized in {"ACTIVE", "APPROVED", "PASSED", "COMPLETED", "RELEASED", "CLOSED", "READY"}:
        tone = "success"
    elif normalized in {"PENDING", "IN_PROCESS", "QUALITY_HOLD", "QA_REVIEW", "IN_EXECUTION", "QUEUED"}:
        tone = "warning"
    elif normalized in {"FAILED", "REJECTED", "REWORK", "OPEN", "HOLD"}:
        tone = "danger"
    elif normalized in {"WAIVED", "CANCELLED", "ARCHIVED", "OBSOLETE"}:
        tone = "neutral"
    else:
        tone = "neutral"
    return {"label": label, "tone": tone}


def _yes_no(value):
    return _status_badge("ACTIVE" if value else "INACTIVE", "Si" if value else "No")


def _fmt_dt(value):
    if not value:
        return "-"
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")


class AuditSaveMixin:
    def form_valid(self, form):
        if not getattr(self, "object", None):
            form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return response


class SerialListMixin(LoginRequiredMixin, ModulePermissionMixin, ListView):
    template_name = "assembly/generic_list.html"
    context_object_name = "items"
    paginate_by = 20
    title = ""
    subtitle = ""
    nav_key = ""
    create_url_name = ""
    create_label = "Nuevo"
    search_placeholder = "Buscar"
    search_fields = ()
    filter_specs = ()
    columns = ()
    update_url_name = ""

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
        for spec in self.filter_specs:
            value = self.request.GET.get(spec["param"], "").strip()
            field = spec.get("field")
            if value and field:
                queryset = queryset.filter(**{spec["field"]: value})
        return queryset

    def row_for(self, obj):
        return {"cells": [], "edit_url": ""}

    def get_create_url(self):
        if not self.create_url_name:
            return ""
        return reverse(self.create_url_name)

    def can_create(self):
        permission = getattr(self, "create_permission", "")
        return bool(permission and self.request.user.has_perm(permission))

    def get_nav_template(self):
        if self.nav_key in CONFIGURATION_NAV_KEYS:
            return "core/_settings_nav.html"
        return "assembly/_nav.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "title": self.title,
                "subtitle": self.subtitle,
                "nav_key": self.nav_key,
                "nav_template": self.get_nav_template(),
                "columns": self.columns,
                "rows": [self.row_for(obj) for obj in context["object_list"]],
                "create_url": self.get_create_url(),
                "create_label": self.create_label,
                "can_create": self.can_create(),
                "secondary_url": getattr(self, "secondary_url", ""),
                "secondary_label": getattr(self, "secondary_label", ""),
                "search_placeholder": self.search_placeholder,
                "filter_specs": self.filter_specs,
                "per_page": self.get_paginate_by(None),
            }
        )
        return context


class SerialFormViewMixin(LoginRequiredMixin, ModulePermissionMixin, AuditSaveMixin):
    template_name = "assembly/generic_form.html"
    title = ""
    subtitle = ""
    nav_key = ""
    back_url_name = ""
    success_message = "Registro guardado."

    def get_success_url(self):
        return reverse(self.back_url_name)

    def get_nav_template(self):
        if self.nav_key in CONFIGURATION_NAV_KEYS:
            return "core/_settings_nav.html"
        return "assembly/_nav.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "title": self.title,
                "subtitle": self.subtitle,
                "nav_key": self.nav_key,
                "nav_template": self.get_nav_template(),
                "back_url": reverse(self.back_url_name),
            }
        )
        return context


class ProductionDashboardView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    template_name = "assembly/dashboard.html"
    permission_required = "assembly.view_serializedunit"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "unit_count": SerializedUnit.objects.count(),
                "registered_count": SerializedUnit.objects.filter(status=UnitStatus.REGISTERED).count(),
                "in_process_count": SerializedUnit.objects.filter(
                    status__in=[UnitStatus.IN_PROCESS, UnitStatus.QUALITY_HOLD, UnitStatus.REWORK],
                ).count(),
                "completed_count": SerializedUnit.objects.filter(status=UnitStatus.COMPLETED).count(),
                "released_count": SerializedUnit.objects.filter(status=UnitStatus.RELEASED).count(),
                "active_plan_count": ProductionPlan.objects.filter(
                    status__in=[ProductionPlanStatus.RELEASED, ProductionPlanStatus.IN_EXECUTION],
                ).count(),
                "active_queue_count": ProductionQueueItem.objects.filter(
                    status__in=[
                        ProductionQueueStatus.QUEUED,
                        ProductionQueueStatus.READY,
                        ProductionQueueStatus.IN_PROGRESS,
                        ProductionQueueStatus.HOLD,
                    ],
                ).count(),
                "open_rework_count": ReworkOrder.objects.exclude(
                    status__in=[ReworkStatus.CLOSED, ReworkStatus.CANCELLED],
                ).count(),
                "pending_quality_count": QualityGate.objects.filter(
                    is_blocking=True,
                ).exclude(status__in=[QualityGateStatus.PASSED, QualityGateStatus.WAIVED]).count(),
            }
        )
        return context


class StationConsoleView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    template_name = "assembly/station_console.html"
    permission_required = "assembly.add_unitstationevent"
    action_labels = {
        StationEventType.STARTED: "Iniciar",
        StationEventType.PAUSED: "Pausar",
        StationEventType.RESUMED: "Reanudar",
        StationEventType.COMPLETED: "Completar",
        StationEventType.FAILED: "Fallar",
        StationEventType.REWORK_OUT: "Enviar a retrabajo",
        StationEventType.REWORK_IN: "Reingresar",
    }

    def station_queryset(self):
        return AssemblyStation.objects.select_related("line").prefetch_related("equipment").filter(is_active=True).order_by(
            "line__code",
            "sequence",
            "code",
        )

    def _station_issue_for(self, station):
        if self.request.user.is_superuser:
            return ""
        return station.operator_issue_for(self.request.user)

    def _route_step_for(self, unit, station):
        approved_route = AssemblyRoute.objects.filter(
            version=unit.version,
            approval_status=ApprovalStatus.APPROVED,
            is_active=True,
        ).order_by("-approved_at", "code").first()
        route = approved_route or AssemblyRoute.objects.filter(version=unit.version, is_active=True).order_by("code").first()
        if route is None:
            return None, None
        step = route.steps.filter(station=station, is_active=True).select_related("station", "route").order_by("sequence").first()
        return route, step

    def _latest_station_event(self, unit, station):
        return unit.station_events.filter(station=station).select_related("operator").order_by("-event_at", "-id").first()

    def _available_actions(self, last_event):
        if last_event is None:
            return [StationEventType.STARTED]
        if last_event.event_type in {StationEventType.STARTED, StationEventType.RESUMED}:
            return [
                StationEventType.PAUSED,
                StationEventType.COMPLETED,
                StationEventType.FAILED,
                StationEventType.REWORK_OUT,
            ]
        if last_event.event_type == StationEventType.PAUSED:
            return [StationEventType.RESUMED, StationEventType.REWORK_OUT]
        if last_event.event_type == StationEventType.FAILED:
            return [StationEventType.REWORK_OUT, StationEventType.STARTED]
        if last_event.event_type == StationEventType.REWORK_OUT:
            return [StationEventType.REWORK_IN]
        if last_event.event_type == StationEventType.REWORK_IN:
            return [StationEventType.STARTED]
        return []

    def _is_last_step(self, step):
        return not AssemblyRouteStep.objects.filter(
            route=step.route,
            is_active=True,
            sequence__gt=step.sequence,
        ).exists()

    def _set_unit_status(self, unit, station, step, event_type, user):
        if event_type in {StationEventType.STARTED, StationEventType.PAUSED, StationEventType.RESUMED, StationEventType.REWORK_IN}:
            unit.status = UnitStatus.IN_PROCESS
        elif event_type == StationEventType.COMPLETED:
            requires_quality = station.requires_quality_gate or step.requires_quality_gate
            if requires_quality:
                QualityGate.objects.get_or_create(
                    unit=unit,
                    station=station,
                    route_step=step,
                    defaults={
                        "status": QualityGateStatus.PENDING,
                        "is_blocking": True,
                        "notes": "Control generado desde estacion.",
                        "created_by": user,
                        "updated_by": user,
                    },
                )
                unit.status = UnitStatus.QUALITY_HOLD
            elif self._is_last_step(step):
                unit.status = UnitStatus.COMPLETED
            else:
                unit.status = UnitStatus.IN_PROCESS
        elif event_type == StationEventType.FAILED:
            unit.status = UnitStatus.QUALITY_HOLD
        elif event_type == StationEventType.REWORK_OUT:
            unit.status = UnitStatus.REWORK
        unit.updated_by = user
        unit.save(update_fields=["status", "updated_by", "updated_at"])

    def _open_rework(self, unit, station, step, user, defect_code, notes):
        code = defect_code or f"RW-{unit.serial_number}-{station.code}"
        ReworkOrder.objects.get_or_create(
            unit=unit,
            station_detected=station,
            route_step_detected=step,
            defect_code=code,
            defaults={
                "description": notes or f"Retrabajo abierto desde {station.code}.",
                "status": ReworkStatus.OPEN,
                "opened_by": user,
                "opened_at": timezone.now(),
                "created_by": user,
                "updated_by": user,
            },
        )

    def _redirect_to_console(self, station=None, serial_number=""):
        params = {}
        if station is not None:
            params["station"] = station.pk
        if serial_number:
            params["serial"] = serial_number
        url = reverse("assembly:station_console")
        if params:
            url = f"{url}?{urlencode(params)}"
        return redirect(url)

    def post(self, request, *args, **kwargs):
        station = get_object_or_404(AssemblyStation, pk=request.POST.get("station"))
        serial_number = request.POST.get("serial_number", "").strip()
        event_type = request.POST.get("action", "").strip()
        notes = request.POST.get("notes", "").strip()
        defect_code = request.POST.get("defect_code", "").strip()

        unit = SerializedUnit.objects.filter(serial_number=serial_number).select_related("version__product").first()
        if unit is None:
            messages.error(request, "Unidad no encontrada.")
            return self._redirect_to_console(station, serial_number)

        station_issue = self._station_issue_for(station)
        if station_issue:
            messages.error(request, station_issue)
            return self._redirect_to_console(station, serial_number)

        route, step = self._route_step_for(unit, station)
        if route is None or step is None:
            messages.error(request, "La unidad no tiene un paso activo para esta estacion.")
            return self._redirect_to_console(station, serial_number)

        last_event = self._latest_station_event(unit, station)
        available_actions = self._available_actions(last_event)
        if event_type not in available_actions:
            messages.error(request, "La accion no corresponde al estado actual de la unidad en esta estacion.")
            return self._redirect_to_console(station, serial_number)

        UnitStationEvent.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            event_type=event_type,
            event_at=timezone.now(),
            operator=request.user,
            source=StationEventSource.MANUAL,
            external_reference=f"UI-{timezone.now().strftime('%Y%m%d%H%M%S%f')}-{unit.pk}-{station.pk}-{event_type}",
            notes=notes,
            metadata={"station_console": True, "route": route.code},
            created_by=request.user,
            updated_by=request.user,
        )
        self._set_unit_status(unit, station, step, event_type, request.user)
        if event_type == StationEventType.REWORK_OUT:
            self._open_rework(unit, station, step, request.user, defect_code, notes)

        messages.success(request, f"Evento registrado: {self.action_labels.get(event_type, event_type)}.")
        return self._redirect_to_console(station, serial_number)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stations = list(self.station_queryset())
        selected_station = None
        station_id = self.request.GET.get("station", "").strip()
        if station_id:
            selected_station = next((station for station in stations if str(station.pk) == station_id), None)

        serial_number = self.request.GET.get("serial", "").strip()
        unit = None
        route = None
        step = None
        last_event = None
        available_actions = []
        if selected_station and serial_number:
            unit = SerializedUnit.objects.filter(serial_number=serial_number).select_related("version__product").first()
            if unit:
                route, step = self._route_step_for(unit, selected_station)
                last_event = self._latest_station_event(unit, selected_station)
                if step is not None:
                    available_actions = self._available_actions(last_event)

        station_issue = self._station_issue_for(selected_station) if selected_station else ""
        recent_events = UnitStationEvent.objects.none()
        if selected_station:
            recent_events = UnitStationEvent.objects.filter(station=selected_station).select_related(
                "unit",
                "operator",
            ).order_by("-event_at", "-id")[:12]

        context.update(
            {
                "nav_key": "station_console",
                "stations": stations,
                "selected_station": selected_station,
                "station_issue": station_issue,
                "station_options": [
                    {"station": station, "issue": self._station_issue_for(station)}
                    for station in stations
                ],
                "serial_number": serial_number,
                "unit": unit,
                "route": route,
                "step": step,
                "last_event": last_event,
                "available_actions": [
                    {"value": action, "label": self.action_labels.get(action, action)}
                    for action in available_actions
                ],
                "recent_events": recent_events,
            }
        )
        return context


class SerializedUnitListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    model = SerializedUnit
    template_name = "assembly/unit_list.html"
    context_object_name = "units"
    permission_required = "assembly.view_serializedunit"

    def get_queryset(self):
        queryset = SerializedUnit.objects.select_related("version__product")
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()

        if q:
            queryset = queryset.filter(
                Q(serial_number__icontains=q)
                | Q(version__code__icontains=q)
                | Q(version__name__icontains=q)
                | Q(version__product__code__icontains=q)
                | Q(version__product__name__icontains=q)
            )
        if status in UnitStatus.values:
            queryset = queryset.filter(status=status)
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset

    def get_paginate_by(self, queryset):
        return _per_page(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["per_page"] = self.get_paginate_by(None)
        context["status_choices"] = UnitStatus.choices
        return context


class SerializedUnitDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = SerializedUnit
    template_name = "assembly/unit_detail.html"
    context_object_name = "unit"
    permission_required = "assembly.view_serializedunit"

    def get_queryset(self):
        return SerializedUnit.objects.select_related("version__product", "production_plan__line")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        unit = self.object
        context.update(
            {
                "nav_key": "units",
                "requirement_statuses": unit.component_requirement_statuses(),
                "as_built_issues": unit.as_built_issues(),
                "events": unit.station_events.select_related("station", "route_step", "operator").order_by("-event_at", "-id"),
                "components": unit.installed_components.select_related(
                    "station",
                    "route_step",
                    "requirement",
                    "installed_by",
                ).order_by("station__sequence", "part_code", "installed_at"),
                "quality_gates": unit.quality_gates.select_related("station", "route_step", "inspected_by").order_by(
                    "station__sequence",
                    "id",
                ),
                "rework_orders": unit.rework_orders.select_related(
                    "station_detected",
                    "route_step_detected",
                    "opened_by",
                    "closed_by",
                ).order_by("-opened_at", "-id"),
                "release_approvals": unit.release_approvals.select_related("decided_by").order_by("-created_at", "-id"),
            }
        )
        return context


class SerializedUnitCreateView(SerialFormViewMixin, CreateView):
    model = SerializedUnit
    form_class = SerializedUnitForm
    permission_required = "assembly.add_serializedunit"
    title = "Nueva unidad"
    subtitle = "Registro individual de una unidad fisica."
    nav_key = "units"
    back_url_name = "assembly:unit_list"
    success_message = "Unidad registrada."


class SerializedUnitUpdateView(SerialFormViewMixin, UpdateView):
    model = SerializedUnit
    form_class = SerializedUnitForm
    permission_required = "assembly.change_serializedunit"
    title = "Editar unidad"
    subtitle = "Actualiza version, serie o estado operativo."
    nav_key = "units"
    back_url_name = "assembly:unit_list"
    success_message = "Unidad actualizada."


class ProductionPlanListView(SerialListMixin):
    model = ProductionPlan
    permission_required = "assembly.view_productionplan"
    create_permission = "assembly.add_productionplan"
    title = "Planes"
    subtitle = "Planificacion por version, linea, fecha y turno."
    nav_key = "plans"
    create_url_name = "assembly:plan_create"
    create_label = "Nuevo plan"
    update_url_name = "assembly:plan_update"
    search_placeholder = "Plan, producto, version o linea"
    search_fields = ("code", "version__code", "version__name", "version__product__code", "line__code", "line__name")
    filter_specs = (
        {"param": "status", "field": "status", "label": "Estado", "choices": ProductionPlanStatus.choices},
        {"param": "line", "field": "line_id", "label": "Linea", "choices_getter": "line_choices"},
    )
    columns = ("Plan", "Version", "Linea", "Fecha/turno", "Estado", "Avance")

    def get_base_queryset(self):
        return ProductionPlan.objects.select_related("version__product", "line").order_by("planned_date", "code")

    def line_choices(self):
        return [(line.pk, f"{line.code} - {line.name}") for line in AssemblyLine.objects.order_by("code")]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for spec in context["filter_specs"]:
            if spec.get("choices_getter"):
                spec["choices"] = getattr(self, spec["choices_getter"])()
        return context

    def row_for(self, obj):
        linked_quantity = obj.linked_quantity
        return {
            "cells": [
                {"primary": obj.code, "secondary": obj.get_priority_display()},
                {"primary": obj.version.code, "secondary": obj.version.product.code},
                {"primary": obj.line.name, "secondary": obj.line.code},
                {"primary": obj.planned_date.strftime("%d/%m/%Y"), "secondary": obj.shift},
                {"badge": _status_badge(obj.status, obj.get_status_display())},
                {"primary": f"{linked_quantity}/{obj.target_quantity}", "secondary": f"{obj.progress_percent}% generado/vinculado"},
            ],
            "action_url": reverse("assembly:plan_control", args=[obj.pk])
            if self.request.user.has_perm("assembly.change_productionplan")
            else "",
            "action_label": "Gestionar",
            "edit_url": reverse(self.update_url_name, args=[obj.pk])
            if self.request.user.has_perm("assembly.change_productionplan")
            else "",
        }


class ProductionPlanCreateView(SerialFormViewMixin, CreateView):
    model = ProductionPlan
    form_class = ProductionPlanForm
    permission_required = "assembly.add_productionplan"
    title = "Nuevo plan"
    subtitle = "Define demanda ejecutable por linea y turno."
    nav_key = "plans"
    back_url_name = "assembly:plan_list"
    success_message = "Plan creado."


class ProductionPlanUpdateView(SerialFormViewMixin, UpdateView):
    model = ProductionPlan
    form_class = ProductionPlanForm
    permission_required = "assembly.change_productionplan"
    title = "Editar plan"
    subtitle = "Ajusta cantidad, ventana, prioridad o estado."
    nav_key = "plans"
    back_url_name = "assembly:plan_list"
    success_message = "Plan actualizado."


class ProductionPlanControlView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = ProductionPlan
    template_name = "assembly/production_plan_control.html"
    context_object_name = "plan"
    permission_required = "assembly.change_productionplan"

    def get_queryset(self):
        return ProductionPlan.objects.select_related("version__product", "line").prefetch_related("units")

    def get_success_url(self):
        return reverse("assembly:plan_control", args=[self.object.pk])

    def available_actions(self):
        actions = set()
        if self.object.status == ProductionPlanStatus.DRAFT:
            actions.add(ProductionPlanActionForm.ACTION_RELEASE)
        if self.object.status == ProductionPlanStatus.RELEASED:
            actions.update({ProductionPlanActionForm.ACTION_START, ProductionPlanActionForm.ACTION_CLOSE})
        if self.object.status == ProductionPlanStatus.IN_EXECUTION:
            actions.add(ProductionPlanActionForm.ACTION_CLOSE)
        if self.object.status not in {ProductionPlanStatus.CLOSED, ProductionPlanStatus.CANCELLED}:
            actions.add(ProductionPlanActionForm.ACTION_CANCEL)
            actions.add(ProductionPlanActionForm.ACTION_LINK)
            if self.object.remaining_quantity:
                actions.add(ProductionPlanActionForm.ACTION_GENERATE)
            if self.object.status in {ProductionPlanStatus.RELEASED, ProductionPlanStatus.IN_EXECUTION} and self.object.units.exists():
                actions.add(ProductionPlanActionForm.ACTION_SEQUENCE)
        return actions

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = ProductionPlanActionForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(action_form=form))

        action = form.cleaned_data["action"]
        if action not in self.available_actions():
            form.add_error(None, "La accion no corresponde al estado actual del plan.")
            return self.render_to_response(self.get_context_data(action_form=form))

        try:
            if action == ProductionPlanActionForm.ACTION_RELEASE:
                self.object.release(request.user)
                messages.success(request, "Plan liberado.")
            elif action == ProductionPlanActionForm.ACTION_START:
                self.object.start(request.user)
                messages.success(request, "Plan iniciado.")
            elif action == ProductionPlanActionForm.ACTION_CLOSE:
                self.object.close(request.user)
                messages.success(request, "Plan cerrado.")
            elif action == ProductionPlanActionForm.ACTION_CANCEL:
                self.object.cancel(request.user)
                messages.warning(request, "Plan cancelado.")
            elif action == ProductionPlanActionForm.ACTION_GENERATE:
                if not request.user.has_perm("assembly.add_serializedunit"):
                    raise ValidationError("No tienes permiso para generar unidades.")
                created_units = self.object.generate_serialized_units(
                    request.user,
                    form.cleaned_data["quantity"],
                    form.cleaned_data.get("serial_prefix", ""),
                )
                messages.success(request, f"Unidades generadas: {len(created_units)}.")
            elif action == ProductionPlanActionForm.ACTION_LINK:
                serial_number = form.cleaned_data.get("serial_number", "").strip()
                unit = SerializedUnit.objects.filter(serial_number=serial_number).first()
                if unit is None:
                    raise ValidationError("Unidad no encontrada.")
                self.object.link_unit(unit, request.user)
                messages.success(request, f"Unidad vinculada: {unit.serial_number}.")
            elif action == ProductionPlanActionForm.ACTION_SEQUENCE:
                if not request.user.has_perm("assembly.add_productionqueueitem"):
                    raise ValidationError("No tienes permiso para generar secuencia.")
                created_items = self.object.create_queue_items(request.user)
                messages.success(request, f"Items de secuencia creados: {len(created_items)}.")
        except ValidationError as exc:
            form.add_error(None, exc.messages[0] if hasattr(exc, "messages") else str(exc))
            return self.render_to_response(self.get_context_data(action_form=form))

        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plan = self.object
        units = plan.units.select_related("version__product").order_by("serial_number")
        queue_items = plan.queue_items.select_related("unit", "line", "route").order_by("sequence", "id")
        context.update(
            {
                "nav_key": "plans",
                "title": "Gestion de plan",
                "back_url": reverse("assembly:plan_list"),
                "edit_url": reverse("assembly:plan_update", args=[plan.pk]),
                "action_form": kwargs.get("action_form") or ProductionPlanActionForm(
                    initial={"serial_prefix": plan.code, "quantity": min(plan.remaining_quantity, 10) or 1}
                ),
                "available_actions": self.available_actions(),
                "units": units,
                "queue_items": queue_items,
                "queue_count": queue_items.count(),
                "linked_quantity": plan.linked_quantity,
                "remaining_quantity": plan.remaining_quantity,
                "progress_percent": plan.progress_percent,
            }
        )
        return context


class ProductionQueueListView(SerialListMixin):
    model = ProductionQueueItem
    permission_required = "assembly.view_productionqueueitem"
    create_permission = "assembly.add_productionqueueitem"
    title = "Secuencia"
    subtitle = "Cola ordenada de unidades por linea, ruta y proxima estacion."
    nav_key = "sequence"
    create_url_name = "assembly:queue_create"
    create_label = "Asignar unidad"
    update_url_name = "assembly:queue_update"
    search_placeholder = "Serial, plan, ruta o linea"
    search_fields = ("unit__serial_number", "production_plan__code", "route__code", "line__code", "line__name")
    filter_specs = (
        {"param": "status", "field": "status", "label": "Estado", "choices": ProductionQueueStatus.choices},
        {"param": "line", "field": "line_id", "label": "Linea", "choices_getter": "line_choices"},
        {"param": "station", "field": "", "label": "Proxima estacion", "choices_getter": "station_choices"},
    )
    columns = ("Sec.", "Unidad", "Plan", "Ruta", "Proxima estacion", "Estado", "Prioridad")

    def get_base_queryset(self):
        return ProductionQueueItem.objects.select_related(
            "unit",
            "production_plan",
            "line",
            "route__version__product",
        ).order_by("line__code", "sequence", "id")

    def line_choices(self):
        return [(line.pk, f"{line.code} - {line.name}") for line in AssemblyLine.objects.order_by("code")]

    def station_choices(self):
        return [(station.pk, f"{station.code} - {station.name}") for station in AssemblyStation.objects.select_related("line").order_by("line__code", "sequence")]

    def get_queryset(self):
        queryset = super().get_queryset()
        station_id = self.request.GET.get("station", "").strip()
        if station_id:
            matching_ids = []
            for item in queryset:
                next_step = item.next_route_step()
                if next_step and str(next_step.station_id) == station_id:
                    matching_ids.append(item.pk)
            queryset = self.get_base_queryset().filter(pk__in=matching_ids)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for spec in context["filter_specs"]:
            if spec.get("choices_getter"):
                spec["choices"] = getattr(self, spec["choices_getter"])()
        context["secondary_url"] = reverse("assembly:station_queue")
        context["secondary_label"] = "Por estacion"
        return context

    def row_for(self, obj):
        next_step = obj.next_route_step()
        return {
            "cells": [
                {"primary": obj.sequence},
                {"primary": obj.unit.serial_number, "secondary": obj.unit.get_status_display()},
                {"primary": obj.production_plan.code, "secondary": obj.production_plan.shift},
                {"primary": f"{obj.route.code}-{obj.route.revision}", "secondary": obj.route.version.code},
                {"primary": next_step.station.code if next_step else "Completa", "secondary": next_step.name if next_step else ""},
                {"badge": _status_badge(obj.status, obj.get_status_display())},
                {"primary": obj.get_priority_display()},
            ],
            "action_url": reverse("assembly:queue_control", args=[obj.pk])
            if self.request.user.has_perm("assembly.change_productionqueueitem")
            else "",
            "action_label": "Gestionar",
            "edit_url": reverse(self.update_url_name, args=[obj.pk])
            if self.request.user.has_perm("assembly.change_productionqueueitem")
            else "",
        }


class ProductionQueueItemCreateView(SerialFormViewMixin, CreateView):
    model = ProductionQueueItem
    form_class = ProductionQueueItemForm
    permission_required = "assembly.add_productionqueueitem"
    title = "Asignar unidad"
    subtitle = "Agrega una unidad a la cola de linea."
    nav_key = "sequence"
    back_url_name = "assembly:queue_list"
    success_message = "Unidad asignada a secuencia."


class ProductionQueueItemUpdateView(SerialFormViewMixin, UpdateView):
    model = ProductionQueueItem
    form_class = ProductionQueueItemForm
    permission_required = "assembly.change_productionqueueitem"
    title = "Editar secuencia"
    subtitle = "Actualiza linea, ruta, prioridad, estado o posicion."
    nav_key = "sequence"
    back_url_name = "assembly:queue_list"
    success_message = "Secuencia actualizada."


class ProductionQueueControlView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = ProductionQueueItem
    template_name = "assembly/production_queue_control.html"
    context_object_name = "item"
    permission_required = "assembly.change_productionqueueitem"

    def get_queryset(self):
        return ProductionQueueItem.objects.select_related(
            "unit__version__product",
            "production_plan",
            "line",
            "route",
        )

    def get_success_url(self):
        return reverse("assembly:queue_control", args=[self.object.pk])

    def available_actions(self):
        if self.object.status in {ProductionQueueStatus.COMPLETED, ProductionQueueStatus.CANCELLED}:
            return set()
        return {
            ProductionQueueActionForm.ACTION_MOVE,
            ProductionQueueActionForm.ACTION_READY,
            ProductionQueueActionForm.ACTION_HOLD,
            ProductionQueueActionForm.ACTION_CANCEL,
        }

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = ProductionQueueActionForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(action_form=form))

        action = form.cleaned_data["action"]
        if action not in self.available_actions():
            form.add_error(None, "La accion no corresponde al estado actual de la cola.")
            return self.render_to_response(self.get_context_data(action_form=form))

        notes = form.cleaned_data.get("notes", "").strip()
        try:
            if action == ProductionQueueActionForm.ACTION_MOVE:
                self.object.resequence(form.cleaned_data["new_sequence"], request.user, notes)
                messages.success(request, "Secuencia reordenada.")
            elif action == ProductionQueueActionForm.ACTION_READY:
                self.object.set_status(ProductionQueueStatus.READY, request.user, notes)
                messages.success(request, "Unidad marcada como lista.")
            elif action == ProductionQueueActionForm.ACTION_HOLD:
                self.object.set_status(ProductionQueueStatus.HOLD, request.user, notes)
                messages.warning(request, "Unidad retenida en secuencia.")
            elif action == ProductionQueueActionForm.ACTION_CANCEL:
                self.object.set_status(ProductionQueueStatus.CANCELLED, request.user, notes)
                messages.warning(request, "Item de secuencia cancelado.")
        except ValidationError as exc:
            form.add_error(None, exc.messages[0] if hasattr(exc, "messages") else str(exc))
            return self.render_to_response(self.get_context_data(action_form=form))
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        next_step = self.object.next_route_step()
        context.update(
            {
                "nav_key": "sequence",
                "title": "Gestion de secuencia",
                "back_url": reverse("assembly:queue_list"),
                "edit_url": reverse("assembly:queue_update", args=[self.object.pk]),
                "plan_url": reverse("assembly:plan_control", args=[self.object.production_plan_id]),
                "unit_detail_url": reverse("assembly:unit_detail", args=[self.object.unit_id]),
                "action_form": kwargs.get("action_form") or ProductionQueueActionForm(initial={"new_sequence": self.object.sequence}),
                "available_actions": self.available_actions(),
                "next_step": next_step,
                "recent_events": self.object.unit.station_events.select_related("station", "route_step", "operator").order_by("-event_at", "-id")[:8],
            }
        )
        return context


class StationQueueView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    template_name = "assembly/station_queue.html"
    permission_required = "assembly.view_productionqueueitem"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_statuses = [
            ProductionQueueStatus.QUEUED,
            ProductionQueueStatus.READY,
            ProductionQueueStatus.IN_PROGRESS,
            ProductionQueueStatus.HOLD,
        ]
        stations = list(AssemblyStation.objects.select_related("line").filter(is_active=True).order_by("line__code", "sequence", "code"))
        buckets = {station.pk: {"station": station, "items": []} for station in stations}
        items = ProductionQueueItem.objects.select_related("unit", "production_plan", "line", "route").filter(
            status__in=active_statuses,
        ).order_by("line__code", "sequence", "id")
        for item in items:
            next_step = item.next_route_step()
            if next_step and next_step.station_id in buckets:
                buckets[next_step.station_id]["items"].append(item)
        context.update(
            {
                "nav_key": "sequence",
                "title": "Proximos trabajos por estacion",
                "back_url": reverse("assembly:queue_list"),
                "station_buckets": buckets.values(),
            }
        )
        return context


class ProductListView(SerialListMixin):
    model = AssembledProduct
    permission_required = "assembly.view_assembledproduct"
    create_permission = "assembly.add_assembledproduct"
    title = "Productos"
    subtitle = "Modelos o familias fabricables."
    nav_key = "products"
    create_url_name = "assembly:product_create"
    create_label = "Nuevo producto"
    update_url_name = "assembly:product_update"
    search_placeholder = "Codigo o nombre"
    search_fields = ("code", "name")
    columns = ("Codigo", "Producto", "Estado")

    def get_base_queryset(self):
        return AssembledProduct.objects.order_by("code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name, "secondary": obj.description},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_assembledproduct") else "",
        }


class ProductCreateView(SerialFormViewMixin, CreateView):
    model = AssembledProduct
    form_class = AssembledProductForm
    permission_required = "assembly.add_assembledproduct"
    title = "Nuevo producto"
    subtitle = "Crea una familia o modelo fabricable."
    nav_key = "products"
    back_url_name = "assembly:product_list"
    success_message = "Producto creado."


class ProductUpdateView(SerialFormViewMixin, UpdateView):
    model = AssembledProduct
    form_class = AssembledProductForm
    permission_required = "assembly.change_assembledproduct"
    title = "Editar producto"
    subtitle = "Actualiza la informacion del producto ensamblado."
    nav_key = "products"
    back_url_name = "assembly:product_list"
    success_message = "Producto actualizado."


class ProductVersionListView(SerialListMixin):
    model = ProductVersion
    permission_required = "assembly.view_productversion"
    create_permission = "assembly.add_productversion"
    title = "Versiones"
    subtitle = "Configuraciones concretas de producto."
    nav_key = "versions"
    create_url_name = "assembly:version_create"
    create_label = "Nueva version"
    update_url_name = "assembly:version_update"
    search_placeholder = "Producto, version o nombre"
    search_fields = ("code", "name", "product__code", "product__name")
    columns = ("Version", "Producto", "Estado")

    def get_base_queryset(self):
        return ProductVersion.objects.select_related("product").order_by("product__code", "code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code, "secondary": obj.name},
                {"primary": obj.product.name, "secondary": obj.product.code},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_productversion") else "",
        }


class ProductVersionCreateView(SerialFormViewMixin, CreateView):
    model = ProductVersion
    form_class = ProductVersionForm
    permission_required = "assembly.add_productversion"
    title = "Nueva version"
    subtitle = "Define una configuracion fabricable."
    nav_key = "versions"
    back_url_name = "assembly:version_list"
    success_message = "Version creada."


class ProductVersionUpdateView(SerialFormViewMixin, UpdateView):
    model = ProductVersion
    form_class = ProductVersionForm
    permission_required = "assembly.change_productversion"
    title = "Editar version"
    subtitle = "Actualiza la configuracion de producto."
    nav_key = "versions"
    back_url_name = "assembly:version_list"
    success_message = "Version actualizada."


class AssemblyLineListView(SerialListMixin):
    model = AssemblyLine
    permission_required = "assembly.view_assemblyline"
    create_permission = "assembly.add_assemblyline"
    title = "Lineas"
    subtitle = "Lineas de ensamblaje y takt objetivo."
    nav_key = "lines"
    create_url_name = "assembly:line_create"
    create_label = "Nueva linea"
    update_url_name = "assembly:line_update"
    search_fields = ("code", "name")
    columns = ("Codigo", "Linea", "Takt", "Estado")

    def get_base_queryset(self):
        return AssemblyLine.objects.order_by("code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name, "secondary": obj.description},
                {"primary": f"{obj.takt_time_seconds} s" if obj.takt_time_seconds else "-"},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_assemblyline") else "",
        }


class AssemblyLineCreateView(SerialFormViewMixin, CreateView):
    model = AssemblyLine
    form_class = AssemblyLineForm
    permission_required = "assembly.add_assemblyline"
    title = "Nueva linea"
    subtitle = "Crea una linea de ensamblaje."
    nav_key = "lines"
    back_url_name = "assembly:line_list"
    success_message = "Linea creada."


class AssemblyLineUpdateView(SerialFormViewMixin, UpdateView):
    model = AssemblyLine
    form_class = AssemblyLineForm
    permission_required = "assembly.change_assemblyline"
    title = "Editar linea"
    subtitle = "Actualiza la linea de ensamblaje."
    nav_key = "lines"
    back_url_name = "assembly:line_list"
    success_message = "Linea actualizada."


class AssemblyStationListView(SerialListMixin):
    model = AssemblyStation
    permission_required = "assembly.view_assemblystation"
    create_permission = "assembly.add_assemblystation"
    title = "Estaciones"
    subtitle = "Puestos de trabajo, equipos y operarios habilitados."
    nav_key = "stations"
    create_url_name = "assembly:station_create"
    create_label = "Nueva estacion"
    update_url_name = "assembly:station_update"
    search_fields = ("code", "name", "line__code", "line__name")
    filter_specs = (
        {"param": "line", "field": "line_id", "label": "Linea", "choices_getter": "line_choices"},
    )
    columns = ("Secuencia", "Estacion", "Linea", "Equipos", "Calidad", "Estado")

    def get_base_queryset(self):
        return AssemblyStation.objects.select_related("line").prefetch_related("equipment").order_by("line__code", "sequence")

    def line_choices(self):
        return [(line.pk, f"{line.code} - {line.name}") for line in AssemblyLine.objects.order_by("code")]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for spec in context["filter_specs"]:
            if spec.get("choices_getter"):
                spec["choices"] = getattr(self, spec["choices_getter"])()
        return context

    def row_for(self, obj):
        equipment = ", ".join(eq.code for eq in obj.equipment.all()[:3])
        if obj.equipment.count() > 3:
            equipment += f" +{obj.equipment.count() - 3}"
        return {
            "cells": [
                {"primary": obj.sequence},
                {"primary": obj.name, "secondary": obj.code},
                {"primary": obj.line.name, "secondary": obj.line.code},
                {"primary": equipment or "-"},
                {"badge": _yes_no(obj.requires_quality_gate)},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_assemblystation") else "",
        }


class AssemblyStationCreateView(SerialFormViewMixin, CreateView):
    model = AssemblyStation
    form_class = AssemblyStationForm
    permission_required = "assembly.add_assemblystation"
    title = "Nueva estacion"
    subtitle = "Registra un puesto de trabajo de la linea."
    nav_key = "stations"
    back_url_name = "assembly:station_list"
    success_message = "Estacion creada."


class AssemblyStationUpdateView(SerialFormViewMixin, UpdateView):
    model = AssemblyStation
    form_class = AssemblyStationForm
    permission_required = "assembly.change_assemblystation"
    title = "Editar estacion"
    subtitle = "Actualiza equipos, secuencia y controles de la estacion."
    nav_key = "stations"
    back_url_name = "assembly:station_list"
    success_message = "Estacion actualizada."


class AssemblyRouteListView(SerialListMixin):
    model = AssemblyRoute
    permission_required = "assembly.view_assemblyroute"
    create_permission = "assembly.add_assemblyroute"
    title = "Rutas"
    subtitle = "Rutas productivas por version."
    nav_key = "routes"
    create_url_name = "assembly:route_create"
    create_label = "Nueva ruta"
    update_url_name = "assembly:route_update"
    search_fields = ("code", "revision", "name", "version__code", "version__product__code", "version__product__name")
    columns = ("Ruta", "Version", "Pasos", "Aprobacion", "Estado")

    def get_base_queryset(self):
        return AssemblyRoute.objects.select_related("version__product").prefetch_related("steps").order_by("version__product__code", "code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": f"{obj.code}-{obj.revision}", "secondary": obj.name},
                {"primary": obj.version.code, "secondary": obj.version.product.code},
                {"primary": obj.steps.count()},
                {"badge": _status_badge(obj.approval_status, obj.get_approval_status_display())},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_assemblyroute") else "",
        }


class AssemblyRouteCreateView(SerialFormViewMixin, CreateView):
    model = AssemblyRoute
    form_class = AssemblyRouteForm
    permission_required = "assembly.add_assemblyroute"
    title = "Nueva ruta"
    subtitle = "Crea una ruta por version de producto."
    nav_key = "routes"
    back_url_name = "assembly:route_list"
    success_message = "Ruta creada."


class AssemblyRouteUpdateView(SerialFormViewMixin, UpdateView):
    model = AssemblyRoute
    form_class = AssemblyRouteForm
    permission_required = "assembly.change_assemblyroute"
    title = "Editar ruta"
    subtitle = "Actualiza la ruta y su estado documental."
    nav_key = "routes"
    back_url_name = "assembly:route_list"
    success_message = "Ruta actualizada."


class AssemblyRouteStepListView(SerialListMixin):
    model = AssemblyRouteStep
    permission_required = "assembly.view_assemblyroutestep"
    create_permission = "assembly.add_assemblyroutestep"
    title = "Pasos de ruta"
    subtitle = "Secuencia operativa por estacion."
    nav_key = "steps"
    create_url_name = "assembly:step_create"
    create_label = "Nuevo paso"
    update_url_name = "assembly:step_update"
    search_fields = ("name", "route__code", "route__version__code", "station__code", "station__name")
    columns = ("Secuencia", "Paso", "Ruta", "Estacion", "Trazabilidad", "Calidad", "Estado")

    def get_base_queryset(self):
        return AssemblyRouteStep.objects.select_related("route__version__product", "station__line").order_by("route__code", "sequence")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.sequence},
                {"primary": obj.name, "secondary": f"{obj.expected_duration_seconds} s"},
                {"primary": obj.route.code, "secondary": obj.route.version.code},
                {"primary": obj.station.name, "secondary": obj.station.code},
                {"badge": _yes_no(obj.requires_component_trace)},
                {"badge": _yes_no(obj.requires_quality_gate)},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_assemblyroutestep") else "",
        }


class AssemblyRouteStepCreateView(SerialFormViewMixin, CreateView):
    model = AssemblyRouteStep
    form_class = AssemblyRouteStepForm
    permission_required = "assembly.add_assemblyroutestep"
    title = "Nuevo paso"
    subtitle = "Agrega una estacion a la ruta."
    nav_key = "steps"
    back_url_name = "assembly:step_list"
    success_message = "Paso creado."


class AssemblyRouteStepUpdateView(SerialFormViewMixin, UpdateView):
    model = AssemblyRouteStep
    form_class = AssemblyRouteStepForm
    permission_required = "assembly.change_assemblyroutestep"
    title = "Editar paso"
    subtitle = "Actualiza secuencia, estacion y controles."
    nav_key = "steps"
    back_url_name = "assembly:step_list"
    success_message = "Paso actualizado."


class RouteStepComponentRequirementListView(SerialListMixin):
    model = RouteStepComponentRequirement
    permission_required = "assembly.view_routestepcomponentrequirement"
    create_permission = "assembly.add_routestepcomponentrequirement"
    title = "Componentes requeridos"
    subtitle = "Receta de partes esperadas por paso de ruta."
    nav_key = "requirements"
    create_url_name = "assembly:requirement_create"
    create_label = "Nuevo requerimiento"
    update_url_name = "assembly:requirement_update"
    search_fields = ("part_code", "part_name", "route_step__name", "route_step__route__code", "route_step__station__code")
    filter_specs = (
        {"param": "traceability", "field": "traceability", "label": "Trazabilidad", "choices": ComponentTraceability.choices},
    )
    columns = ("Paso", "Ruta", "Parte", "Cantidad", "Trazabilidad", "Critico", "Estado")

    def get_base_queryset(self):
        return RouteStepComponentRequirement.objects.select_related(
            "route_step__route__version__product",
            "route_step__station",
        ).order_by("route_step__route__code", "route_step__sequence", "part_code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": f"#{obj.route_step.sequence} {obj.route_step.name}", "secondary": obj.route_step.station.code},
                {"primary": f"{obj.route_step.route.code}-{obj.route_step.route.revision}", "secondary": obj.route_step.route.version.code},
                {"primary": obj.part_code, "secondary": obj.part_name},
                {"primary": obj.quantity_required},
                {"primary": obj.get_traceability_display()},
                {"badge": _yes_no(obj.is_critical)},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk])
            if self.request.user.has_perm("assembly.change_routestepcomponentrequirement")
            else "",
        }


class RouteStepComponentRequirementCreateView(SerialFormViewMixin, CreateView):
    model = RouteStepComponentRequirement
    form_class = RouteStepComponentRequirementForm
    permission_required = "assembly.add_routestepcomponentrequirement"
    title = "Nuevo componente requerido"
    subtitle = "Define una parte esperada para un paso de ruta."
    nav_key = "requirements"
    back_url_name = "assembly:requirement_list"
    success_message = "Componente requerido creado."


class RouteStepComponentRequirementUpdateView(SerialFormViewMixin, UpdateView):
    model = RouteStepComponentRequirement
    form_class = RouteStepComponentRequirementForm
    permission_required = "assembly.change_routestepcomponentrequirement"
    title = "Editar componente requerido"
    subtitle = "Actualiza cantidad, trazabilidad y criticidad."
    nav_key = "requirements"
    back_url_name = "assembly:requirement_list"
    success_message = "Componente requerido actualizado."


class UnitStationEventListView(SerialListMixin):
    model = UnitStationEvent
    permission_required = "assembly.view_unitstationevent"
    create_permission = "assembly.add_unitstationevent"
    title = "Eventos"
    subtitle = "Bitacora por unidad, estacion y origen."
    nav_key = "events"
    create_url_name = "assembly:event_create"
    create_label = "Nuevo evento"
    update_url_name = "assembly:event_update"
    search_fields = ("unit__serial_number", "station__code", "station__name", "external_reference")
    filter_specs = (
        {"param": "event_type", "field": "event_type", "label": "Tipo", "choices": StationEventType.choices},
    )
    columns = ("Fecha", "Unidad", "Estacion", "Evento", "Origen", "Operario")

    def get_base_queryset(self):
        return UnitStationEvent.objects.select_related("unit", "station", "operator").order_by("-event_at", "-id")

    def row_for(self, obj):
        operator = obj.operator.get_username() if obj.operator_id else "-"
        return {
            "cells": [
                {"primary": _fmt_dt(obj.event_at)},
                {"primary": obj.unit.serial_number},
                {"primary": obj.station.name, "secondary": obj.station.code},
                {"badge": _status_badge(obj.event_type, obj.get_event_type_display())},
                {"primary": obj.get_source_display()},
                {"primary": operator},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_unitstationevent") else "",
        }


class UnitStationEventCreateView(SerialFormViewMixin, CreateView):
    model = UnitStationEvent
    form_class = UnitStationEventForm
    permission_required = "assembly.add_unitstationevent"
    title = "Nuevo evento"
    subtitle = "Registra un avance o excepcion de estacion."
    nav_key = "events"
    back_url_name = "assembly:event_list"
    success_message = "Evento registrado."


class UnitStationEventUpdateView(SerialFormViewMixin, UpdateView):
    model = UnitStationEvent
    form_class = UnitStationEventForm
    permission_required = "assembly.change_unitstationevent"
    title = "Editar evento"
    subtitle = "Corrige datos del evento operacional."
    nav_key = "events"
    back_url_name = "assembly:event_list"
    success_message = "Evento actualizado."


class InstalledComponentListView(SerialListMixin):
    model = InstalledComponent
    permission_required = "assembly.view_installedcomponent"
    create_permission = "assembly.add_installedcomponent"
    title = "Componentes"
    subtitle = "As-built por serial, lote o ambos."
    nav_key = "components"
    create_url_name = "assembly:component_create"
    create_label = "Nuevo componente"
    update_url_name = "assembly:component_update"
    search_fields = ("unit__serial_number", "part_code", "part_name", "serial_number", "lot_number")
    filter_specs = (
        {"param": "is_critical", "field": "", "label": "Critico", "choices": (("1", "Si"), ("0", "No"))},
    )
    columns = ("Unidad", "Parte", "Serial", "Lote", "Cantidad", "Estacion", "Critico")

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.GET.get("is_critical") == "1":
            queryset = queryset.filter(is_critical=True)
        if self.request.GET.get("is_critical") == "0":
            queryset = queryset.filter(is_critical=False)
        return queryset

    def get_base_queryset(self):
        return InstalledComponent.objects.select_related("unit", "station").order_by("-installed_at", "-id")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.unit.serial_number},
                {"primary": obj.part_code, "secondary": obj.part_name},
                {"primary": obj.serial_number or "-"},
                {"primary": obj.lot_number or "-"},
                {"primary": obj.quantity},
                {"primary": obj.station.code if obj.station_id else "-"},
                {"badge": _yes_no(obj.is_critical)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_installedcomponent") else "",
        }


class InstalledComponentCreateView(SerialFormViewMixin, CreateView):
    model = InstalledComponent
    form_class = InstalledComponentForm
    permission_required = "assembly.add_installedcomponent"
    title = "Nuevo componente"
    subtitle = "Registra una parte instalada en la unidad."
    nav_key = "components"
    back_url_name = "assembly:component_list"
    success_message = "Componente registrado."


class InstalledComponentUpdateView(SerialFormViewMixin, UpdateView):
    model = InstalledComponent
    form_class = InstalledComponentForm
    permission_required = "assembly.change_installedcomponent"
    title = "Editar componente"
    subtitle = "Actualiza trazabilidad del as-built."
    nav_key = "components"
    back_url_name = "assembly:component_list"
    success_message = "Componente actualizado."


class QualityGateListView(SerialListMixin):
    model = QualityGate
    permission_required = "assembly.view_qualitygate"
    create_permission = "assembly.add_qualitygate"
    title = "Calidad"
    subtitle = "Controles de calidad y bloqueos de liberacion."
    nav_key = "quality"
    create_url_name = "assembly:quality_create"
    create_label = "Nuevo control"
    update_url_name = "assembly:quality_update"
    search_fields = ("unit__serial_number", "station__code", "station__name", "evidence_reference")
    filter_specs = (
        {"param": "status", "field": "status", "label": "Estado", "choices": QualityGateStatus.choices},
    )
    columns = ("Unidad", "Estacion", "Estado", "Bloquea", "Inspeccion", "Evidencia")

    def get_base_queryset(self):
        return QualityGate.objects.select_related("unit", "station", "inspected_by").order_by("-created_at", "-id")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.unit.serial_number},
                {"primary": obj.station.code if obj.station_id else "General"},
                {"badge": _status_badge(obj.status, obj.get_status_display())},
                {"badge": _yes_no(obj.is_blocking)},
                {"primary": _fmt_dt(obj.inspected_at), "secondary": obj.inspected_by.get_username() if obj.inspected_by_id else ""},
                {"primary": obj.evidence_reference or "-"},
            ],
            "action_url": reverse("assembly:quality_review", args=[obj.pk])
            if self.request.user.has_perm("assembly.change_qualitygate")
            else "",
            "action_label": "Revisar",
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_qualitygate") else "",
        }


class QualityGateCreateView(SerialFormViewMixin, CreateView):
    model = QualityGate
    form_class = QualityGateForm
    permission_required = "assembly.add_qualitygate"
    title = "Nuevo control de calidad"
    subtitle = "Registra un punto de inspeccion de la unidad."
    nav_key = "quality"
    back_url_name = "assembly:quality_list"
    success_message = "Control de calidad creado."


class QualityGateUpdateView(SerialFormViewMixin, UpdateView):
    model = QualityGate
    form_class = QualityGateForm
    permission_required = "assembly.change_qualitygate"
    title = "Editar control de calidad"
    subtitle = "Actualiza resultado, bloqueo y evidencia."
    nav_key = "quality"
    back_url_name = "assembly:quality_list"
    success_message = "Control de calidad actualizado."


class QualityGateReviewView(LoginRequiredMixin, ModulePermissionMixin, UpdateView):
    model = QualityGate
    form_class = QualityGateDecisionForm
    template_name = "assembly/quality_review.html"
    permission_required = "assembly.change_qualitygate"
    success_message = "Revision de calidad registrada."

    def get_queryset(self):
        return QualityGate.objects.select_related("unit__version__product", "station", "route_step", "inspected_by")

    def get_success_url(self):
        return reverse("assembly:quality_list")

    def form_valid(self, form):
        form.instance.inspected_by = self.request.user
        form.instance.inspected_at = timezone.now()
        form.instance.updated_by = self.request.user
        if not form.instance.created_by_id:
            form.instance.created_by = self.request.user
        response = super().form_valid(form)
        self.object.apply_result_to_unit(self.request.user)
        messages.success(self.request, self.success_message)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "nav_key": "quality",
                "title": "Revision de calidad",
                "back_url": reverse("assembly:quality_list"),
                "unit_detail_url": reverse("assembly:unit_detail", args=[self.object.unit_id]),
            }
        )
        return context


class ReworkOrderListView(SerialListMixin):
    model = ReworkOrder
    permission_required = "assembly.view_reworkorder"
    create_permission = "assembly.add_reworkorder"
    title = "Retrabajos"
    subtitle = "Defectos, correcciones y revision de calidad."
    nav_key = "rework"
    create_url_name = "assembly:rework_create"
    create_label = "Nuevo retrabajo"
    update_url_name = "assembly:rework_update"
    search_fields = ("unit__serial_number", "defect_code", "description", "station_detected__code")
    filter_specs = (
        {"param": "status", "field": "status", "label": "Estado", "choices": ReworkStatus.choices},
    )
    columns = ("Unidad", "Defecto", "Estado", "Estacion", "Apertura", "Cierre")

    def get_base_queryset(self):
        return ReworkOrder.objects.select_related("unit", "station_detected", "opened_by", "closed_by").order_by("-opened_at", "-id")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.unit.serial_number},
                {"primary": obj.defect_code or "-", "secondary": obj.description[:120]},
                {"badge": _status_badge(obj.status, obj.get_status_display())},
                {"primary": obj.station_detected.code if obj.station_detected_id else "-"},
                {"primary": _fmt_dt(obj.opened_at), "secondary": obj.opened_by.get_username() if obj.opened_by_id else ""},
                {"primary": _fmt_dt(obj.closed_at), "secondary": obj.closed_by.get_username() if obj.closed_by_id else ""},
            ],
            "action_url": reverse("assembly:rework_control", args=[obj.pk])
            if self.request.user.has_perm("assembly.change_reworkorder")
            else "",
            "action_label": "Gestionar",
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_reworkorder") else "",
        }


class ReworkOrderCreateView(SerialFormViewMixin, CreateView):
    model = ReworkOrder
    form_class = ReworkOrderForm
    permission_required = "assembly.add_reworkorder"
    title = "Nuevo retrabajo"
    subtitle = "Abre una correccion contra la unidad."
    nav_key = "rework"
    back_url_name = "assembly:rework_list"
    success_message = "Retrabajo creado."

    def form_valid(self, form):
        if not form.instance.opened_by_id:
            form.instance.opened_by = self.request.user
        response = super().form_valid(form)
        if self.object.status in {ReworkStatus.OPEN, ReworkStatus.IN_PROGRESS}:
            self.object.unit.status = UnitStatus.REWORK
            self.object.unit.updated_by = self.request.user
            self.object.unit.save(update_fields=["status", "updated_by", "updated_at"])
        elif self.object.status == ReworkStatus.QA_REVIEW:
            self.object.unit.status = UnitStatus.QUALITY_HOLD
            self.object.unit.updated_by = self.request.user
            self.object.unit.save(update_fields=["status", "updated_by", "updated_at"])
        return response


class ReworkOrderUpdateView(SerialFormViewMixin, UpdateView):
    model = ReworkOrder
    form_class = ReworkOrderForm
    permission_required = "assembly.change_reworkorder"
    title = "Editar retrabajo"
    subtitle = "Actualiza estado y cierre de retrabajo."
    nav_key = "rework"
    back_url_name = "assembly:rework_list"
    success_message = "Retrabajo actualizado."


class ReworkOrderControlView(LoginRequiredMixin, ModulePermissionMixin, UpdateView):
    model = ReworkOrder
    form_class = ReworkActionForm
    template_name = "assembly/rework_control.html"
    permission_required = "assembly.change_reworkorder"

    def get_queryset(self):
        return ReworkOrder.objects.select_related(
            "unit__version__product",
            "station_detected",
            "route_step_detected",
            "opened_by",
            "closed_by",
            "reinspection_gate",
        )

    def get_success_url(self):
        return reverse("assembly:rework_control", args=[self.object.pk])

    def available_actions(self):
        if self.object.status == ReworkStatus.OPEN:
            return {ReworkActionForm.ACTION_START, ReworkActionForm.ACTION_SEND_QA, ReworkActionForm.ACTION_CLOSE, ReworkActionForm.ACTION_CANCEL}
        if self.object.status == ReworkStatus.IN_PROGRESS:
            return {ReworkActionForm.ACTION_SEND_QA, ReworkActionForm.ACTION_CLOSE, ReworkActionForm.ACTION_CANCEL}
        if self.object.status == ReworkStatus.QA_REVIEW:
            return {ReworkActionForm.ACTION_CLOSE, ReworkActionForm.ACTION_CANCEL}
        return set()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.pop("instance", None)
        if self.request.method == "GET":
            kwargs["data"] = None
        return kwargs

    def form_valid(self, form):
        action = form.cleaned_data["action"]
        if action not in self.available_actions():
            form.add_error(None, "La accion no corresponde al estado actual del retrabajo.")
            return self.form_invalid(form)

        notes = form.cleaned_data.get("notes", "").strip()
        evidence_reference = form.cleaned_data.get("closure_evidence_reference", "").strip()
        if action == ReworkActionForm.ACTION_START:
            self.object.start(self.request.user)
            messages.success(self.request, "Retrabajo iniciado.")
        elif action == ReworkActionForm.ACTION_SEND_QA:
            gate = self.object.send_to_quality_review(self.request.user, evidence_reference, notes)
            messages.success(self.request, f"Retrabajo enviado a reinspeccion: {gate.evidence_reference}.")
        elif action == ReworkActionForm.ACTION_CLOSE:
            self.object.close(self.request.user, notes, evidence_reference)
            messages.success(self.request, "Retrabajo cerrado.")
        elif action == ReworkActionForm.ACTION_CANCEL:
            self.object.cancel(self.request.user, notes)
            messages.warning(self.request, "Retrabajo cancelado.")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        available_actions = self.available_actions()
        events = self.object.unit.station_events.filter(
            event_type__in=[StationEventType.REWORK_OUT, StationEventType.REWORK_IN],
        ).select_related("station", "operator").order_by("-event_at", "-id")
        context.update(
            {
                "nav_key": "rework",
                "title": "Gestion de retrabajo",
                "back_url": reverse("assembly:rework_list"),
                "unit_detail_url": reverse("assembly:unit_detail", args=[self.object.unit_id]),
                "quality_review_url": reverse("assembly:quality_review", args=[self.object.reinspection_gate_id])
                if self.object.reinspection_gate_id
                else "",
                "available_actions": available_actions,
                "rework_events": events,
                "closed_statuses": {ReworkStatus.CLOSED, ReworkStatus.CANCELLED},
            }
        )
        return context


class ReleaseApprovalListView(SerialListMixin):
    model = ReleaseApproval
    permission_required = "assembly.view_releaseapproval"
    create_permission = "assembly.add_releaseapproval"
    title = "Liberacion"
    subtitle = "Decision formal antes del cierre de unidad."
    nav_key = "release"
    create_url_name = "assembly:release_create"
    create_label = "Nueva liberacion"
    update_url_name = "assembly:release_update"
    search_fields = ("unit__serial_number", "evidence_reference", "notes")
    filter_specs = (
        {"param": "decision", "field": "decision", "label": "Decision", "choices": ReleaseDecision.choices},
    )
    columns = ("Unidad", "Decision", "Fecha", "Responsable", "Evidencia", "Notas")

    def get_base_queryset(self):
        return ReleaseApproval.objects.select_related("unit", "decided_by").order_by("-created_at", "-id")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.unit.serial_number},
                {"badge": _status_badge(obj.decision, obj.get_decision_display())},
                {"primary": _fmt_dt(obj.decided_at)},
                {"primary": obj.decided_by.get_username() if obj.decided_by_id else "-"},
                {"primary": obj.evidence_reference or "-"},
                {"primary": obj.notes[:100] if obj.notes else "-"},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("assembly.change_releaseapproval") else "",
        }


class ReleaseApprovalCreateView(SerialFormViewMixin, CreateView):
    model = ReleaseApproval
    form_class = ReleaseApprovalForm
    permission_required = "assembly.add_releaseapproval"
    title = "Nueva liberacion"
    subtitle = "Aprueba o rechaza formalmente la unidad."
    nav_key = "release"
    back_url_name = "assembly:release_list"
    success_message = "Liberacion registrada."

    def form_valid(self, form):
        if form.instance.decision != ReleaseDecision.PENDING and not form.instance.decided_at:
            form.instance.decided_at = timezone.now()
        if form.instance.decision != ReleaseDecision.PENDING and not form.instance.decided_by_id:
            form.instance.decided_by = self.request.user
        response = super().form_valid(form)
        self.object.apply_decision_to_unit(self.request.user)
        return response


class ReleaseApprovalUpdateView(SerialFormViewMixin, UpdateView):
    model = ReleaseApproval
    form_class = ReleaseApprovalForm
    permission_required = "assembly.change_releaseapproval"
    title = "Editar liberacion"
    subtitle = "Actualiza decision y evidencia."
    nav_key = "release"
    back_url_name = "assembly:release_list"
    success_message = "Liberacion actualizada."

    def form_valid(self, form):
        if form.instance.decision != ReleaseDecision.PENDING and not form.instance.decided_at:
            form.instance.decided_at = timezone.now()
        if form.instance.decision != ReleaseDecision.PENDING and not form.instance.decided_by_id:
            form.instance.decided_by = self.request.user
        response = super().form_valid(form)
        self.object.apply_decision_to_unit(self.request.user)
        return response


class EquipmentListView(SerialListMixin):
    model = EquipmentIntegration
    permission_required = "core.view_equipmentintegration"
    create_permission = "core.add_equipmentintegration"
    title = "Equipos"
    subtitle = "Scanners, torquimetros, impresoras, PLC y bancos de prueba."
    nav_key = "equipment"
    create_url_name = "assembly:equipment_create"
    create_label = "Nuevo equipo"
    update_url_name = "assembly:equipment_update"
    search_fields = ("code", "name", "asset_code", "serial_number", "manufacturer", "model")
    columns = ("Codigo", "Equipo", "Tipo", "Conexion", "Calibracion", "Mantenimiento", "Estado")

    def get_base_queryset(self):
        return EquipmentIntegration.objects.order_by("code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code, "secondary": obj.asset_code},
                {"primary": obj.name, "secondary": obj.serial_number},
                {"primary": obj.get_equipment_type_display()},
                {"primary": obj.get_connection_protocol_display(), "secondary": obj.host or obj.serial_port},
                {"badge": _status_badge(obj.calibration_status, obj.calibration_status_label)},
                {"badge": _status_badge(obj.maintenance_status, obj.maintenance_status_label)},
                {"badge": _yes_no(obj.is_active)},
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]) if self.request.user.has_perm("core.change_equipmentintegration") else "",
        }


class EquipmentCreateView(SerialFormViewMixin, CreateView):
    model = EquipmentIntegration
    form_class = EquipmentIntegrationForm
    permission_required = "core.add_equipmentintegration"
    title = "Nuevo equipo"
    subtitle = "Registra un equipo disponible para planta."
    nav_key = "equipment"
    back_url_name = "assembly:equipment_list"
    success_message = "Equipo creado."


class EquipmentUpdateView(SerialFormViewMixin, UpdateView):
    model = EquipmentIntegration
    form_class = EquipmentIntegrationForm
    permission_required = "core.change_equipmentintegration"
    title = "Editar equipo"
    subtitle = "Actualiza integracion, calibracion y mantenimiento."
    nav_key = "equipment"
    back_url_name = "assembly:equipment_list"
    success_message = "Equipo actualizado."
