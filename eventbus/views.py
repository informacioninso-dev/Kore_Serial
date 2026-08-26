from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from assembly.models import AssemblyLine
from core.mixins import ModulePermissionMixin
from core.views import AuditSaveMixin

from .forms import EventSubscriptionForm, EventTypeForm
from .models import (
    DeliveryStatus,
    DomainEvent,
    EventDelivery,
    EventSubscription,
    EventType,
    IndicatorSnapshot,
)
from .services import dispatch_pending, rebuild_all_indicators, retry_delivery, seed_event_catalog


PER_PAGE_CHOICES = (20, 50, 100)


def _per_page(request, default=20):
    try:
        value = int(request.GET.get("per_page", default))
    except (TypeError, ValueError):
        return default
    return value if value in PER_PAGE_CHOICES else default


def _badge(value, label):
    tones = {
        "DELIVERED": "success",
        "PUBLISHED": "success",
        "ACTIVE": "success",
        "PENDING": "warning",
        "FAILED": "danger",
        "DISCARDED": "danger",
        "SKIPPED": "neutral",
        "DISABLED": "neutral",
    }
    return {"label": label, "tone": tones.get(value, "neutral")}


class EventBusListMixin(LoginRequiredMixin, ModulePermissionMixin, ListView):
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
                "nav_template": "eventbus/_nav.html",
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


class EventBusFormMixin(LoginRequiredMixin, ModulePermissionMixin, AuditSaveMixin):
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
                "nav_template": "eventbus/_nav.html",
                "back_url": reverse(self.back_url_name),
            }
        )
        return context


class EventBusDashboardView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    template_name = "eventbus/dashboard.html"
    permission_required = "eventbus.view_domainevent"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        deliveries = EventDelivery.objects.all()
        context.update(
            {
                "event_types": EventType.objects.filter(is_active=True).count(),
                "subscriptions": EventSubscription.objects.filter(is_active=True).count(),
                "events_today": DomainEvent.objects.filter(occurred_at__date=today).count(),
                "events_total": DomainEvent.objects.count(),
                "pending_deliveries": deliveries.filter(status=DeliveryStatus.PENDING).count(),
                "failed_deliveries": deliveries.filter(status=DeliveryStatus.FAILED).count(),
                "today_snapshots": IndicatorSnapshot.objects.filter(date=today).select_related("line"),
                "recent_events": DomainEvent.objects.select_related("event_type", "line")[:10],
                "by_domain": (
                    DomainEvent.objects.values("event_type__domain")
                    .annotate(total=Count("id"))
                    .order_by("-total")
                ),
                "can_operate": self.request.user.has_perm("eventbus.change_eventdelivery"),
            }
        )
        return context


class EventTypeListView(EventBusListMixin):
    model = EventType
    permission_required = "eventbus.view_eventtype"
    create_permission = "eventbus.add_eventtype"
    create_url_name = "eventbus:type_create"
    update_url_name = "eventbus:type_update"
    title = "Catalogo de eventos"
    subtitle = "Contrato formal: si no esta aqui, el sistema no lo publica."
    nav_key = "types"
    create_label = "Nuevo tipo"
    columns = ("Codigo", "Nombre", "Dominio", "Claves", "Eventos", "Estado")
    search_fields = ("code", "name", "description")
    filter_specs = (
        {
            "param": "domain",
            "field": "domain",
            "label": "Dominio",
            "choices": EventType._meta.get_field("domain").choices,
        },
    )

    def get_base_queryset(self):
        return EventType.objects.annotate(total=Count("events")).order_by("domain", "code")

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name},
                {"primary": obj.get_domain_display()},
                {"primary": ", ".join(obj.payload_keys or []) or "sin contrato"},
                {"primary": obj.total},
                {
                    "badge": _badge(
                        "ACTIVE" if obj.is_active else "DISABLED",
                        "Activo" if obj.is_active else "Inactivo",
                    )
                },
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class EventTypeCreateView(EventBusFormMixin, CreateView):
    model = EventType
    form_class = EventTypeForm
    permission_required = "eventbus.add_eventtype"
    title = "Nuevo tipo de evento"
    subtitle = "Declara el contrato antes de emitirlo."
    nav_key = "types"
    back_url_name = "eventbus:type_list"


class EventTypeUpdateView(EventBusFormMixin, UpdateView):
    model = EventType
    form_class = EventTypeForm
    permission_required = "eventbus.change_eventtype"
    title = "Editar tipo de evento"
    subtitle = "Ajusta el contrato del evento."
    nav_key = "types"
    back_url_name = "eventbus:type_list"


class EventListView(EventBusListMixin):
    model = DomainEvent
    permission_required = "eventbus.view_domainevent"
    title = "Eventos"
    subtitle = "Historia de hechos publicados, con su clave de idempotencia."
    nav_key = "events"
    columns = ("Ocurrido", "Tipo", "Agregado", "Linea", "Entregas", "Origen")
    search_fields = ("idempotency_key", "aggregate_id", "event_type__code")
    search_placeholder = "Buscar por clave, agregado o tipo"

    def get_base_queryset(self):
        return DomainEvent.objects.select_related("event_type", "line").all()

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.occurred_at.strftime("%d/%m/%Y %H:%M:%S")},
                {"primary": obj.event_type.code, "secondary": obj.event_type.get_domain_display()},
                {"primary": obj.aggregate_id or "-", "secondary": obj.aggregate_type},
                {"primary": obj.line.code if obj.line_id else "-"},
                {"primary": obj.deliveries.count()},
                {"primary": obj.source_module or "-"},
            ],
            "action_url": reverse("eventbus:event_detail", args=[obj.pk]),
            "action_label": "Ver",
        }


class EventDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    model = DomainEvent
    template_name = "eventbus/event_detail.html"
    context_object_name = "event"
    permission_required = "eventbus.view_domainevent"

    def get_queryset(self):
        return DomainEvent.objects.select_related("event_type", "line", "actor")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "nav_key": "events",
                "deliveries": self.object.deliveries.select_related("subscription"),
                "missing_keys": self.object.event_type.missing_keys(self.object.payload),
                "can_retry": self.request.user.has_perm("eventbus.change_eventdelivery"),
            }
        )
        return context


class SubscriptionListView(EventBusListMixin):
    model = EventSubscription
    permission_required = "eventbus.view_eventsubscription"
    create_permission = "eventbus.add_eventsubscription"
    create_url_name = "eventbus:subscription_create"
    update_url_name = "eventbus:subscription_update"
    title = "Suscripciones"
    subtitle = "Quien se entera de que. Sin suscripcion no hay entrega."
    nav_key = "subscriptions"
    create_label = "Nueva suscripcion"
    columns = ("Codigo", "Nombre", "Escucha", "Manejador", "Intentos", "Estado")
    search_fields = ("code", "name")

    def get_base_queryset(self):
        return EventSubscription.objects.select_related("event_type").order_by("code")

    def row_for(self, obj):
        listens = obj.event_type.code if obj.event_type_id else f"dominio {obj.get_domain_display()}"
        return {
            "cells": [
                {"primary": obj.code},
                {"primary": obj.name},
                {"primary": listens},
                {"primary": obj.get_handler_display()},
                {"primary": obj.max_attempts},
                {
                    "badge": _badge(
                        "ACTIVE" if obj.is_active else "DISABLED",
                        "Activa" if obj.is_active else "Inactiva",
                    )
                },
            ],
            "edit_url": reverse(self.update_url_name, args=[obj.pk]),
        }


class SubscriptionCreateView(EventBusFormMixin, CreateView):
    model = EventSubscription
    form_class = EventSubscriptionForm
    permission_required = "eventbus.add_eventsubscription"
    title = "Nueva suscripcion"
    subtitle = "Conecta un consumidor al bus."
    nav_key = "subscriptions"
    back_url_name = "eventbus:subscription_list"


class SubscriptionUpdateView(EventBusFormMixin, UpdateView):
    model = EventSubscription
    form_class = EventSubscriptionForm
    permission_required = "eventbus.change_eventsubscription"
    title = "Editar suscripcion"
    subtitle = "Ajusta el filtro o el manejador."
    nav_key = "subscriptions"
    back_url_name = "eventbus:subscription_list"


class DeliveryListView(EventBusListMixin):
    model = EventDelivery
    permission_required = "eventbus.view_eventdelivery"
    title = "Entregas"
    subtitle = "Una por evento y suscriptor. Aqui se ve que quedo sin procesar."
    nav_key = "deliveries"
    columns = ("Evento", "Suscripcion", "Intentos", "Entregado", "Error", "Estado")
    search_fields = ("event__idempotency_key", "subscription__code", "last_error")
    filter_specs = (
        {
            "param": "status",
            "field": "status",
            "label": "Estado",
            "choices": EventDelivery._meta.get_field("status").choices,
        },
    )

    def get_base_queryset(self):
        return EventDelivery.objects.select_related("event__event_type", "subscription").all()

    def row_for(self, obj):
        return {
            "cells": [
                {"primary": obj.event.event_type.code, "secondary": obj.event.idempotency_key},
                {"primary": obj.subscription.code},
                {"primary": f"{obj.attempts}/{obj.subscription.max_attempts}"},
                {"primary": obj.delivered_at.strftime("%d/%m/%Y %H:%M") if obj.delivered_at else "-"},
                {"primary": (obj.last_error or "-")[:60]},
                {"badge": _badge(obj.status, obj.get_status_display())},
            ],
            "action_url": reverse("eventbus:event_detail", args=[obj.event_id]),
            "action_label": "Ver evento",
        }


class IndicatorListView(EventBusListMixin):
    model = IndicatorSnapshot
    permission_required = "eventbus.view_indicatorsnapshot"
    title = "Indicadores diarios"
    subtitle = "OEE, FPY, MTBF y MTTR reconstruidos desde los eventos."
    nav_key = "indicators"
    columns = ("Fecha", "Linea", "OEE", "Disponibilidad / Rendimiento / Calidad", "FPY", "MTBF / MTTR")
    search_fields = ("line__code",)

    def get_base_queryset(self):
        return IndicatorSnapshot.objects.select_related("line").all()

    def row_for(self, obj):
        def pct(value):
            return f"{value}%" if value is not None else "-"

        return {
            "cells": [
                {"primary": obj.date.strftime("%d/%m/%Y")},
                {"primary": obj.line_label, "secondary": f"{obj.event_count} eventos"},
                {"primary": pct(obj.oee_percent)},
                {
                    "primary": f"{pct(obj.availability_percent)} / {pct(obj.performance_percent)} / {pct(obj.quality_percent)}"
                },
                {"primary": pct(obj.fpy_percent)},
                {
                    "primary": f"{obj.mtbf_minutes or '-'} / {obj.mttr_minutes or '-'}",
                    "secondary": "minutos",
                },
            ],
        }


class DispatchPendingView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "eventbus.change_eventdelivery"

    def post(self, request, *args, **kwargs):
        delivered, failed = dispatch_pending(actor=request.user)
        if delivered or failed:
            messages.success(request, f"Entregas procesadas: {delivered} correctas, {failed} fallidas.")
        else:
            messages.info(request, "No habia entregas pendientes.")
        return redirect("eventbus:dashboard")


class RetryDeliveryView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "eventbus.change_eventdelivery"

    def post(self, request, *args, **kwargs):
        delivery = get_object_or_404(EventDelivery, pk=kwargs["pk"])
        try:
            retry_delivery(delivery, actor=request.user)
        except ValueError as error:
            messages.error(request, str(error))
        else:
            delivery.refresh_from_db()
            if delivery.status == DeliveryStatus.DELIVERED:
                messages.success(request, "Entrega procesada.")
            else:
                messages.warning(request, delivery.last_error or "La entrega volvio a fallar.")
        return redirect("eventbus:event_detail", pk=delivery.event_id)


class SeedCatalogView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "eventbus.add_eventtype"

    def post(self, request, *args, **kwargs):
        created = seed_event_catalog(actor=request.user)
        messages.success(request, f"Catalogo base verificado. Tipos nuevos: {created}.")
        return redirect("eventbus:type_list")


class RebuildIndicatorsView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "eventbus.change_indicatorsnapshot"

    def post(self, request, *args, **kwargs):
        date = timezone.localdate()
        snapshots = rebuild_all_indicators(date, actor=request.user)
        messages.success(
            request, f"Indicadores recalculados para {date:%d/%m/%Y}: {len(snapshots)} fotos."
        )
        return redirect("eventbus:indicator_list")
