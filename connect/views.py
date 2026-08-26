from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from core.mixins import ModulePermissionMixin
from core.views import AuditSaveMixin

from .forms import ConnectorContractForm, ConnectorForm, ReconciliationForm
from .models import (
    Connector,
    ConnectorContract,
    InboundMessage,
    InboundStatus,
    MessageStatus,
    OutboundMessage,
    ReconciliationRun,
)
from .services import flush_outbound, reconcile, requeue_missing, send_message


PER_PAGE_CHOICES = (20, 50, 100)


def _per_page(request, default=20):
    try:
        value = int(request.GET.get("per_page", default))
    except (TypeError, ValueError):
        return default
    return value if value in PER_PAGE_CHOICES else default


def _badge(value, label):
    tones = {
        "SENT": "success",
        "PROCESSED": "success",
        "ACTIVE": "success",
        "QUEUED": "warning",
        "RECEIVED": "warning",
        "FAILED": "danger",
        "REJECTED": "danger",
        "DISCARDED": "neutral",
        "DISABLED": "neutral",
    }
    return {"label": label, "tone": tones.get(value, "neutral")}


class ConnectListMixin(LoginRequiredMixin, ModulePermissionMixin, ListView):
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
                "nav_template": "connect/_nav.html",
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


class ConnectFormMixin(LoginRequiredMixin, ModulePermissionMixin, AuditSaveMixin):
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
                "nav_template": "connect/_nav.html",
                "back_url": reverse(self.back_url_name),
            }
        )
        return context


class ConnectDashboardView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    template_name = "connect/dashboard.html"
    permission_required = "connect.view_connector"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        outbound = OutboundMessage.objects.all()
        context.update(
            {
                "connectors": Connector.objects.filter(is_active=True).order_by("code"),
                "connector_count": Connector.objects.filter(is_active=True).count(),
                "contract_count": ConnectorContract.objects.filter(is_active=True).count(),
                "queued": outbound.filter(status=MessageStatus.QUEUED).count(),
                "failed": outbound.filter(status=MessageStatus.FAILED).count(),
                "discarded": outbound.filter(status=MessageStatus.DISCARDED).count(),
                "sent": outbound.filter(status=MessageStatus.SENT).count(),
                "inbound_pending": InboundMessage.objects.filter(
                    status=InboundStatus.RECEIVED
                ).count(),
                "recent_outbound": outbound.select_related("connector", "contract")[:8],
                "recent_runs": ReconciliationRun.objects.select_related("connector")[:5],
                "can_operate": self.request.user.has_perm("connect.change_outboundmessage"),
            }
        )
        return context


class ConnectorListView(ConnectListMixin):
    model = Connector
    permission_required = "connect.view_connector"
    create_permission = "connect.add_connector"
    create_url_name = "connect:connector_create"
    update_url_name = "connect:connector_update"
    title = "Conectores"
    subtitle = "Sistemas externos con los que Kore Line conversa."
    nav_key = "connectors"
    create_label = "Nuevo conector"
    columns = ("Codigo", "Conector", "Sistema", "Direccion", "Transporte", "Estado")
    search_fields = ("code", "name", "endpoint")

    def get_base_queryset(self):
        return Connector.objects.annotate(contract_total=Count("contracts")).order_by("code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name, "secondary": f"{obj.contract_total} contratos"},
                {"primary": obj.get_system_display()},
                {"primary": obj.get_direction_display()},
                {
                    "primary": obj.get_transport_display(),
                    "secondary": obj.endpoint or "sin endpoint",
                },
                {
                    "badge": _badge(
                        "ACTIVE" if obj.is_active else "DISABLED",
                        "Activo" if obj.is_active else "Inactivo",
                    )
                },
            ],
            "action_url": reverse("connect:connector_detail", args=[obj.pk]),
            "action_label": "Ver",
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class ConnectorCreateView(ConnectFormMixin, CreateView):
    model = Connector
    form_class = ConnectorForm
    permission_required = "connect.add_connector"
    title = "Nuevo conector"
    subtitle = "Nace sin enviar nada: el transporte arranca en LOG."
    nav_key = "connectors"
    back_url_name = "connect:connector_list"


class ConnectorUpdateView(ConnectFormMixin, UpdateView):
    model = Connector
    form_class = ConnectorForm
    permission_required = "connect.change_connector"
    title = "Editar conector"
    subtitle = "Ajusta destino, credenciales y politica de reintentos."
    nav_key = "connectors"
    back_url_name = "connect:connector_list"


class ConnectorDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = Connector
    template_name = "connect/connector_detail.html"
    context_object_name = "connector"
    permission_required = "connect.view_connector"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connector = self.object
        context.update(
            {
                "nav_key": "connectors",
                "contracts": connector.contracts.select_related("event_type").order_by("code"),
                "recent_outbound": connector.outbound.select_related("contract")[:10],
                "recent_inbound": connector.inbound.all()[:10],
                "runs": connector.reconciliations.all()[:5],
                "can_operate": self.request.user.has_perm("connect.change_outboundmessage"),
            }
        )
        return context


class ContractListView(ConnectListMixin):
    model = ConnectorContract
    permission_required = "connect.view_connectorcontract"
    create_permission = "connect.add_connectorcontract"
    create_url_name = "connect:contract_create"
    update_url_name = "connect:contract_update"
    title = "Contratos"
    subtitle = "Que se manda, con que nombres y disparado por que evento."
    nav_key = "contracts"
    create_label = "Nuevo contrato"
    columns = ("Codigo", "Contrato", "Conector", "Direccion", "Evento", "Estado")
    search_fields = ("code", "name")

    def get_base_queryset(self):
        return ConnectorContract.objects.select_related("connector", "event_type").order_by(
            "connector__code", "code"
        )

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name, "secondary": f"{len(obj.field_map or {})} campos mapeados"},
                {"primary": obj.connector.code},
                {"primary": obj.get_direction_display()},
                {"primary": obj.event_type.code if obj.event_type_id else "-"},
                {
                    "badge": _badge(
                        "ACTIVE" if obj.is_active else "DISABLED",
                        "Activo" if obj.is_active else "Inactivo",
                    )
                },
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class ContractCreateView(ConnectFormMixin, CreateView):
    model = ConnectorContract
    form_class = ConnectorContractForm
    permission_required = "connect.add_connectorcontract"
    title = "Nuevo contrato"
    subtitle = "Define el vocabulario del sistema externo."
    nav_key = "contracts"
    back_url_name = "connect:contract_list"


class ContractUpdateView(ConnectFormMixin, UpdateView):
    model = ConnectorContract
    form_class = ConnectorContractForm
    permission_required = "connect.change_connectorcontract"
    title = "Editar contrato"
    subtitle = "Ajusta el mapeo de campos."
    nav_key = "contracts"
    back_url_name = "connect:contract_list"


class OutboundListView(ConnectListMixin):
    model = OutboundMessage
    permission_required = "connect.view_outboundmessage"
    title = "Mensajes de salida"
    subtitle = "Cola, reintentos y descartes hacia sistemas externos."
    nav_key = "outbound"
    columns = ("Clave", "Conector", "Contrato", "Intentos", "Proximo intento", "Estado")
    search_fields = ("idempotency_key", "last_error")
    filter_specs = (
        {
            "param": "status",
            "field": "status",
            "label": "Estado",
            "choices": OutboundMessage._meta.get_field("status").choices,
        },
    )

    def get_base_queryset(self):
        return OutboundMessage.objects.select_related("connector", "contract").all()

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.idempotency_key[:60]},
                {"primary": obj.connector.code},
                {"primary": obj.contract.code},
                {"primary": f"{obj.attempts}/{obj.connector.max_attempts}"},
                {
                    "primary": obj.next_attempt_at.strftime("%d/%m/%Y %H:%M")
                    if obj.next_attempt_at
                    else "-"
                },
                {"badge": _badge(obj.status, obj.get_status_display())},
            ],
            "action_url": reverse("connect:outbound_detail", args=[obj.pk]),
            "action_label": "Ver",
        }


class OutboundDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = OutboundMessage
    template_name = "connect/outbound_detail.html"
    context_object_name = "message"
    permission_required = "connect.view_outboundmessage"

    def get_queryset(self):
        return OutboundMessage.objects.select_related("connector", "contract", "event")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "nav_key": "outbound",
                "can_operate": self.request.user.has_perm("connect.change_outboundmessage"),
            }
        )
        return context


class InboundListView(ConnectListMixin):
    model = InboundMessage
    permission_required = "connect.view_inboundmessage"
    title = "Mensajes de entrada"
    subtitle = "Lo que llega de afuera, guardado antes de interpretarlo."
    nav_key = "inbound"
    columns = ("Recibido", "Conector", "Identificador", "Contrato", "Detalle", "Estado")
    search_fields = ("external_id", "result_detail")

    def get_base_queryset(self):
        return InboundMessage.objects.select_related("connector", "contract").all()

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.received_at.strftime("%d/%m/%Y %H:%M:%S")},
                {"primary": obj.connector.code},
                {"primary": obj.external_id[:50]},
                {"primary": obj.contract.code if obj.contract_id else "-"},
                {"primary": (obj.result_detail or "-")[:60]},
                {"badge": _badge(obj.status, obj.get_status_display())},
            ],
        }


class ReconciliationListView(ConnectListMixin):
    model = ReconciliationRun
    permission_required = "connect.view_reconciliationrun"
    title = "Reconciliaciones"
    subtitle = "Lo que ocurrio adentro contra lo que realmente salio."
    nav_key = "reconciliation"
    columns = ("Ejecutado", "Conector", "Periodo", "Esperados", "Enviados", "Brecha")
    search_fields = ("connector__code",)

    def get_base_queryset(self):
        return ReconciliationRun.objects.select_related("connector").all()

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.ran_at.strftime("%d/%m/%Y %H:%M")},
                {"primary": obj.connector.code},
                {"primary": f"{obj.date_from:%d/%m} a {obj.date_to:%d/%m}"},
                {"primary": obj.expected_count},
                {"primary": obj.sent_count, "secondary": f"{obj.failed_count} fallidos"},
                {
                    "badge": _badge(
                        "SENT" if obj.is_clean else "FAILED",
                        "Sin brecha" if obj.is_clean else f"{obj.gap} sin enviar",
                    )
                },
            ],
            "action_url": reverse("connect:reconciliation_detail", args=[obj.pk]),
            "action_label": "Ver",
        }


class ReconciliationDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = ReconciliationRun
    template_name = "connect/reconciliation_detail.html"
    context_object_name = "run"
    permission_required = "connect.view_reconciliationrun"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "nav_key": "reconciliation",
                "can_operate": self.request.user.has_perm("connect.change_outboundmessage"),
            }
        )
        return context


class ReconciliationRunView(LoginRequiredMixin, ModulePermissionMixin, FormView):
    template_name = "connect/reconciliation_form.html"
    form_class = ReconciliationForm
    permission_required = "connect.add_reconciliationrun"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"nav_key": "reconciliation", "title": "Nueva reconciliacion"})
        return context

    def form_valid(self, form):
        run = reconcile(
            connector=form.cleaned_data["connector"],
            date_from=form.cleaned_data["date_from"],
            date_to=form.cleaned_data["date_to"],
            actor=self.request.user,
        )
        if run.is_clean:
            messages.success(self.request, "Reconciliacion sin brechas.")
        else:
            messages.warning(
                self.request, f"{run.gap} eventos sin enviar y {run.failed_count} mensajes fallidos."
            )
        return redirect("connect:reconciliation_detail", pk=run.pk)


class FlushOutboundView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "connect.change_outboundmessage"

    def post(self, request, *args, **kwargs):
        sent, failed = flush_outbound(actor=request.user)
        if sent or failed:
            messages.success(request, f"Envios procesados: {sent} correctos, {failed} fallidos.")
        else:
            messages.info(request, "No habia mensajes por enviar.")
        return redirect("connect:dashboard")


class SendMessageView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "connect.change_outboundmessage"

    def post(self, request, *args, **kwargs):
        message = get_object_or_404(OutboundMessage, pk=kwargs["pk"])
        try:
            send_message(message, actor=request.user)
        except ValueError as error:
            messages.error(request, str(error))
        else:
            if message.status == MessageStatus.SENT:
                messages.success(request, "Mensaje enviado.")
            else:
                messages.warning(request, message.last_error or "El envio volvio a fallar.")
        return redirect("connect:outbound_detail", pk=message.pk)


class RequeueMissingView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "connect.change_outboundmessage"

    def post(self, request, *args, **kwargs):
        run = get_object_or_404(ReconciliationRun, pk=kwargs["pk"])
        created = requeue_missing(run, actor=request.user)
        messages.success(request, f"Mensajes encolados nuevamente: {created}.")
        return redirect("connect:reconciliation_detail", pk=run.pk)
