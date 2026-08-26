from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from core.mixins import ModulePermissionMixin
from core.views import AuditSaveMixin

from .forms import EdgeCommandForm, EdgeDeviceForm, EdgeGatewayForm, EdgeSignalRuleForm
from .models import (
    EdgeCommand,
    EdgeCommandStatus,
    EdgeDevice,
    EdgeGateway,
    EdgeGatewayStatus,
    EdgeHealthCheck,
    EdgeSignal,
    EdgeSignalRule,
    EdgeSignalStatus,
)
from .services import expire_commands, queue_command, retry_signal


PER_PAGE_CHOICES = (20, 50, 100)


def _per_page(request, default=20):
    try:
        value = int(request.GET.get("per_page", default))
    except (TypeError, ValueError):
        return default
    return value if value in PER_PAGE_CHOICES else default


def _badge(value, label):
    tones = {
        "ONLINE": "success",
        "NORMALIZED": "success",
        "ACKED": "success",
        "ACTIVE": "success",
        "DEGRADED": "warning",
        "PENDING": "warning",
        "QUEUED": "warning",
        "SENT": "warning",
        "OFFLINE": "danger",
        "REJECTED": "danger",
        "FAILED": "danger",
        "DISABLED": "neutral",
        "IGNORED": "neutral",
        "EXPIRED": "neutral",
    }
    return {"label": label, "tone": tones.get(value, "neutral")}


class EdgeListMixin(LoginRequiredMixin, ModulePermissionMixin, ListView):
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
                "nav_template": "edge/_nav.html",
                "columns": self.columns,
                "rows": [self.row_for(obj) for obj in context["object_list"]],
                "create_url": reverse(self.create_url_name) if self.create_url_name else "",
                "create_label": self.create_label,
                "can_create": bool(
                    self.create_permission and self.request.user.has_perm(self.create_permission)
                ),
                "search_placeholder": self.search_placeholder,
                "filter_specs": self.filter_specs,
                "per_page": self.get_paginate_by(None),
            }
        )
        return context


class EdgeFormMixin(LoginRequiredMixin, ModulePermissionMixin, AuditSaveMixin):
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
            {
                "title": self.title,
                "subtitle": self.subtitle,
                "nav_key": self.nav_key,
                "nav_template": "edge/_nav.html",
                "back_url": reverse(self.back_url_name),
            }
        )
        return context


class EdgeDashboardView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    template_name = "edge/dashboard.html"
    permission_required = "edge.view_edgegateway"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        expire_commands()
        gateways = list(EdgeGateway.objects.select_related("plant").order_by("code"))
        health = {status.value: 0 for status in EdgeGatewayStatus}
        for gateway in gateways:
            health[gateway.health_status] += 1
        today = timezone.localdate()
        context.update(
            {
                "gateways": gateways,
                "gateway_count": len(gateways),
                "online_count": health[EdgeGatewayStatus.ONLINE],
                "degraded_count": health[EdgeGatewayStatus.DEGRADED],
                "offline_count": health[EdgeGatewayStatus.OFFLINE],
                "device_count": EdgeDevice.objects.filter(is_active=True).count(),
                "rule_count": EdgeSignalRule.objects.filter(is_active=True).count(),
                "buffered_total": sum(gateway.buffered_signal_count for gateway in gateways),
                "signals_today": EdgeSignal.objects.filter(captured_at__date=today).count(),
                "pending_signals": EdgeSignal.objects.filter(status=EdgeSignalStatus.PENDING).count(),
                "rejected_signals": EdgeSignal.objects.filter(status=EdgeSignalStatus.REJECTED).count(),
                "open_commands": EdgeCommand.objects.filter(
                    status__in=[EdgeCommandStatus.QUEUED, EdgeCommandStatus.SENT]
                ).count(),
                "recent_signals": EdgeSignal.objects.select_related("device", "gateway", "rule").all()[:8],
            }
        )
        return context


class GatewayListView(EdgeListMixin):
    model = EdgeGateway
    permission_required = "edge.view_edgegateway"
    create_permission = "edge.add_edgegateway"
    create_url_name = "edge:gateway_create"
    update_url_name = "edge:gateway_update"
    title = "Gateways"
    subtitle = "Collectores de planta que traducen senales de equipos."
    nav_key = "gateways"
    create_label = "Nuevo gateway"
    columns = ("Codigo", "Gateway", "Planta", "Dispositivos", "Ultimo contacto", "Estado")
    search_fields = ("code", "name", "host")

    def get_base_queryset(self):
        return (
            EdgeGateway.objects.select_related("plant")
            .annotate(device_total=Count("devices"))
            .order_by("code")
        )

    def row_for(self, obj):
        seconds = obj.seconds_since_last_seen
        last_seen = "Sin contacto" if seconds is None else f"hace {seconds}s"
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name, "secondary": obj.host or "Sin host"},
                {"primary": obj.plant.name if obj.plant_id else "Sin planta"},
                {"primary": obj.device_total},
                {"primary": last_seen, "secondary": f"buffer {obj.buffered_signal_count}"},
                {"badge": _badge(obj.health_status, obj.health_status_label)},
            ],
            "action_url": reverse("edge:gateway_detail", args=[obj.pk]),
            "action_label": "Ver",
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class GatewayCreateView(EdgeFormMixin, CreateView):
    model = EdgeGateway
    form_class = EdgeGatewayForm
    permission_required = "edge.add_edgegateway"
    title = "Nuevo gateway"
    subtitle = "Registra un collector de planta."
    nav_key = "gateways"
    back_url_name = "edge:gateway_list"


class GatewayUpdateView(EdgeFormMixin, UpdateView):
    model = EdgeGateway
    form_class = EdgeGatewayForm
    permission_required = "edge.change_edgegateway"
    title = "Editar gateway"
    subtitle = "Actualiza los parametros del collector."
    nav_key = "gateways"
    back_url_name = "edge:gateway_list"


class GatewayDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = EdgeGateway
    template_name = "edge/gateway_detail.html"
    context_object_name = "gateway"
    permission_required = "edge.view_edgegateway"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        gateway = self.object
        context.update(
            {
                "nav_key": "gateways",
                "devices": gateway.devices.select_related("equipment", "station").order_by("code"),
                "recent_health": gateway.health_checks.all()[:10],
                "recent_signals": gateway.signals.select_related("device", "rule")[:10],
                "commands": gateway.commands.select_related("device")[:10],
                "can_command": self.request.user.has_perm("edge.add_edgecommand"),
                "can_rotate": self.request.user.has_perm("edge.change_edgegateway"),
            }
        )
        return context


class GatewayRotateTokenView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "edge.change_edgegateway"

    def post(self, request, *args, **kwargs):
        gateway = get_object_or_404(EdgeGateway, pk=kwargs["pk"])
        gateway.rotate_token()
        gateway.updated_by = request.user
        gateway.save(update_fields=["auth_token", "updated_by", "updated_at"])
        messages.success(
            request,
            "Token regenerado. El collector debe actualizarse o dejara de reportar.",
        )
        return redirect("edge:gateway_detail", pk=gateway.pk)


class GatewayPingView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "edge.add_edgecommand"

    def post(self, request, *args, **kwargs):
        gateway = get_object_or_404(EdgeGateway, pk=kwargs["pk"])
        queue_command(gateway=gateway, command_type="PING", actor=request.user)
        messages.success(request, "Ping encolado. El gateway lo tomara en su proxima consulta.")
        return redirect("edge:gateway_detail", pk=gateway.pk)


class DeviceListView(EdgeListMixin):
    model = EdgeDevice
    permission_required = "edge.view_edgedevice"
    create_permission = "edge.add_edgedevice"
    create_url_name = "edge:device_create"
    update_url_name = "edge:device_update"
    title = "Dispositivos"
    subtitle = "Lectores, torquimetros, PLC y sensores conectados a un gateway."
    nav_key = "devices"
    create_label = "Nuevo dispositivo"
    columns = ("Codigo", "Dispositivo", "Gateway", "Equipo", "Estacion", "Estado")
    search_fields = ("code", "name", "address")
    filter_specs = (
        {
            "param": "device_type",
            "field": "device_type",
            "label": "Tipo",
            "choices": EdgeDevice._meta.get_field("device_type").choices,
        },
    )

    def get_base_queryset(self):
        return EdgeDevice.objects.select_related("gateway", "equipment", "station").order_by(
            "gateway__code", "code"
        )

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name, "secondary": obj.get_device_type_display()},
                {"primary": obj.gateway.code},
                {"primary": obj.equipment.code if obj.equipment_id else "Sin equipo"},
                {"primary": obj.station.code if obj.station_id else "Sin estacion"},
                {
                    "badge": _badge(
                        "ACTIVE" if obj.is_active else "DISABLED",
                        "Activo" if obj.is_active else "Inactivo",
                    )
                },
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class DeviceCreateView(EdgeFormMixin, CreateView):
    model = EdgeDevice
    form_class = EdgeDeviceForm
    permission_required = "edge.add_edgedevice"
    title = "Nuevo dispositivo"
    subtitle = "Conecta un equipo fisico a un gateway."
    nav_key = "devices"
    back_url_name = "edge:device_list"


class DeviceUpdateView(EdgeFormMixin, UpdateView):
    model = EdgeDevice
    form_class = EdgeDeviceForm
    permission_required = "edge.change_edgedevice"
    title = "Editar dispositivo"
    subtitle = "Actualiza el canal y su enlace con el maestro de equipos."
    nav_key = "devices"
    back_url_name = "edge:device_list"


class SignalRuleListView(EdgeListMixin):
    model = EdgeSignalRule
    permission_required = "edge.view_edgesignalrule"
    create_permission = "edge.add_edgesignalrule"
    create_url_name = "edge:rule_create"
    update_url_name = "edge:rule_update"
    title = "Reglas de normalizacion"
    subtitle = "Traducen una senal tecnica cruda en un hecho de negocio del MES."
    nav_key = "rules"
    create_label = "Nueva regla"
    columns = ("Codigo", "Regla", "Senal", "Accion", "Rango", "Estado")
    search_fields = ("code", "name", "signal_key")
    filter_specs = (
        {
            "param": "action",
            "field": "action",
            "label": "Accion",
            "choices": EdgeSignalRule._meta.get_field("action").choices,
        },
    )

    def get_base_queryset(self):
        return EdgeSignalRule.objects.select_related("device").order_by("priority", "code")

    def row_for(self, obj):
        if obj.min_value is None and obj.max_value is None:
            rango = "Sin rango"
        else:
            rango = f"{obj.min_value if obj.min_value is not None else '-'} a {obj.max_value if obj.max_value is not None else '-'}"
        target = obj.get_station_event_type_display() if obj.station_event_type else obj.measurement_code
        return {
            "cells": [
                {"primary": obj.code, "secondary": f"prioridad {obj.priority}"},
                {"primary": obj.name},
                {
                    "primary": obj.signal_key,
                    "secondary": obj.device.code if obj.device_id else "Cualquier dispositivo",
                },
                {"primary": obj.get_action_display(), "secondary": target or ""},
                {"primary": rango, "secondary": obj.unit_of_measure},
                {
                    "badge": _badge(
                        "ACTIVE" if obj.is_active else "DISABLED",
                        "Activa" if obj.is_active else "Inactiva",
                    )
                },
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class SignalRuleCreateView(EdgeFormMixin, CreateView):
    model = EdgeSignalRule
    form_class = EdgeSignalRuleForm
    permission_required = "edge.add_edgesignalrule"
    title = "Nueva regla"
    subtitle = "Define como se interpreta una senal del piso."
    nav_key = "rules"
    back_url_name = "edge:rule_list"


class SignalRuleUpdateView(EdgeFormMixin, UpdateView):
    model = EdgeSignalRule
    form_class = EdgeSignalRuleForm
    permission_required = "edge.change_edgesignalrule"
    title = "Editar regla"
    subtitle = "Ajusta la traduccion de la senal."
    nav_key = "rules"
    back_url_name = "edge:rule_list"


class SignalListView(EdgeListMixin):
    model = EdgeSignal
    permission_required = "edge.view_edgesignal"
    title = "Senales"
    subtitle = "Trafico crudo recibido del piso, con su resultado de normalizacion."
    nav_key = "signals"
    columns = ("Capturada", "Senal", "Dispositivo", "Valor", "Unidad", "Estado")
    search_fields = ("external_id", "signal_key", "raw_value", "unit_serial_number")
    search_placeholder = "Buscar por senal, serie o identificador"
    filter_specs = (
        {
            "param": "status",
            "field": "status",
            "label": "Estado",
            "choices": EdgeSignal._meta.get_field("status").choices,
        },
    )

    def get_base_queryset(self):
        return EdgeSignal.objects.select_related("device", "gateway", "rule").all()

    def row_for(self, obj):
        return {
            "cells": [
                {
                    "primary": obj.captured_at.strftime("%d/%m/%Y %H:%M:%S"),
                    "secondary": "desde buffer" if obj.from_buffer else "en linea",
                },
                {
                    "primary": obj.signal_key,
                    "secondary": obj.rule.code if obj.rule_id else "Sin regla",
                },
                {"primary": obj.device.code, "secondary": obj.gateway.code},
                {"primary": obj.raw_value or "-"},
                {"primary": obj.unit_serial_number or "-"},
                {"badge": _badge(obj.status, obj.get_status_display())},
            ],
            "action_url": reverse("edge:signal_detail", args=[obj.pk]),
            "action_label": "Ver",
        }


class SignalDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = EdgeSignal
    template_name = "edge/signal_detail.html"
    context_object_name = "signal"
    permission_required = "edge.view_edgesignal"

    def get_queryset(self):
        return EdgeSignal.objects.select_related(
            "device", "gateway", "rule", "inbound_event", "measurement"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "nav_key": "signals",
                "can_retry": self.request.user.has_perm("edge.change_edgesignal")
                and self.object.status != EdgeSignalStatus.NORMALIZED,
            }
        )
        return context


class SignalRetryView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "edge.change_edgesignal"

    def post(self, request, *args, **kwargs):
        signal = get_object_or_404(EdgeSignal, pk=kwargs["pk"])
        try:
            retry_signal(signal, actor=request.user)
        except ValueError as error:
            messages.error(request, str(error))
        else:
            if signal.status == EdgeSignalStatus.NORMALIZED:
                messages.success(request, "Senal normalizada.")
            else:
                messages.warning(request, signal.result_detail or "La senal sigue sin resolverse.")
        return redirect("edge:signal_detail", pk=signal.pk)


class HealthCheckListView(EdgeListMixin):
    model = EdgeHealthCheck
    permission_required = "edge.view_edgehealthcheck"
    title = "Salud de gateways"
    subtitle = "Latidos recibidos, buffer offline y latencia por collector."
    nav_key = "health"
    columns = ("Reportado", "Gateway", "Cola", "Buffer", "Latencia", "Estado")
    search_fields = ("gateway__code", "agent_version", "detail")

    def get_base_queryset(self):
        return EdgeHealthCheck.objects.select_related("gateway").all()

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.reported_at.strftime("%d/%m/%Y %H:%M:%S")},
                {"primary": obj.gateway.code, "secondary": obj.agent_version or "sin version"},
                {"primary": obj.queue_depth},
                {"primary": obj.buffered_count},
                {"primary": f"{obj.latency_ms} ms" if obj.latency_ms is not None else "-"},
                {"badge": _badge(obj.status, obj.get_status_display())},
            ],
        }


class CommandListView(EdgeListMixin):
    model = EdgeCommand
    permission_required = "edge.view_edgecommand"
    create_permission = "edge.add_edgecommand"
    create_url_name = "edge:command_create"
    title = "Comandos"
    subtitle = "Handshake selectivo: el gateway recoge y confirma."
    nav_key = "commands"
    create_label = "Nuevo comando"
    columns = ("Emitido", "Comando", "Gateway", "Dispositivo", "Confirmado", "Estado")
    search_fields = ("gateway__code", "detail")
    filter_specs = (
        {
            "param": "status",
            "field": "status",
            "label": "Estado",
            "choices": EdgeCommand._meta.get_field("status").choices,
        },
    )

    def get_base_queryset(self):
        expire_commands()
        return EdgeCommand.objects.select_related("gateway", "device").all()

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.issued_at.strftime("%d/%m/%Y %H:%M")},
                {"primary": obj.get_command_type_display()},
                {"primary": obj.gateway.code},
                {"primary": obj.device.code if obj.device_id else "Gateway"},
                {"primary": obj.acked_at.strftime("%d/%m/%Y %H:%M") if obj.acked_at else "-"},
                {"badge": _badge(obj.status, obj.get_status_display())},
            ],
        }


class CommandCreateView(EdgeFormMixin, CreateView):
    model = EdgeCommand
    form_class = EdgeCommandForm
    permission_required = "edge.add_edgecommand"
    title = "Nuevo comando"
    subtitle = "Encola una orden para que el gateway la recoja."
    nav_key = "commands"
    back_url_name = "edge:command_list"

    def form_valid(self, form):
        command = queue_command(
            gateway=form.cleaned_data["gateway"],
            command_type=form.cleaned_data["command_type"],
            actor=self.request.user,
            device=form.cleaned_data.get("device"),
            payload=form.cleaned_data.get("payload") or {},
        )
        self.object = command
        messages.success(self.request, "Comando encolado.")
        return redirect(self.get_success_url())
