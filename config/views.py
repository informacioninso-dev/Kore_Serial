from collections import defaultdict
from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from assembly.metrics import build_production_metrics, format_seconds
from assembly.models import (
    AndonSignal,
    AndonStatus,
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    DowntimeStatus,
    ExternalMaterialKit,
    ExternalMaterialKitStatus,
    ModelMixPlan,
    ModelMixPlanStatus,
    ProductionDowntime,
    ProductionPlan,
    ProductionPlanStatus,
    ProductionQueueItem,
    ProductionQueueStatus,
    ProductVersion,
    QualityGate,
    QualityGateStatus,
    ReleaseApproval,
    ReleaseDecision,
    ReworkOrder,
    ReworkStatus,
    SerializedUnit,
    StationOfflineEvent,
    StationOfflineEventStatus,
    UnitStatus,
)
from core.models import EquipmentIntegration
from tenants.models import TenantMembership


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def _can_view_production(self):
        user = self.request.user
        return user.is_superuser or user.has_perm("assembly.view_serializedunit")

    def _can_view_metrics(self):
        user = self.request.user
        return user.is_superuser or user.has_perm("assembly.view_unitstationevent")

    def _has_perm(self, permission):
        user = self.request.user
        return user.is_superuser or user.has_perm(permission)

    def _is_tenant_admin(self):
        user = self.request.user
        if user.is_superuser or user.groups.filter(name="admin").exists():
            return True
        tenant = getattr(self.request, "tenant", None)
        if tenant is None:
            return False
        return TenantMembership.objects.filter(
            tenant=tenant,
            user=user,
            is_admin=True,
            is_active=True,
        ).exists()

    def _sum_target_quantity(self, day):
        return (
            ProductionPlan.objects.filter(planned_date=day)
            .exclude(status=ProductionPlanStatus.CANCELLED)
            .aggregate(total=Sum("target_quantity"))["total"]
            or 0
        )

    def _daily_snapshot(self, day):
        metrics = build_production_metrics(day, day)
        planned = self._sum_target_quantity(day)
        completed = metrics["summary"]["completed_units"]
        failures = metrics["summary"]["failure_count"]
        reworks = ReworkOrder.objects.filter(opened_at__date=day).count()
        downtime_seconds = sum(
            downtime.duration_seconds
            for downtime in ProductionDowntime.objects.filter(started_at__date=day).exclude(
                status=DowntimeStatus.CANCELLED,
            )
        )
        return {
            "date": day,
            "label": day.strftime("%d/%m"),
            "planned": planned,
            "completed": completed,
            "failures": failures,
            "reworks": reworks,
            "downtime_seconds": downtime_seconds,
            "downtime_label": format_seconds(downtime_seconds),
            "fulfillment_percent": round((completed / planned) * 100, 1) if planned else None,
            "quality_percent": metrics["summary"]["quality_percent"],
        }

    def _delta(self, current, previous, unit="", precision=0, lower_is_better=False):
        if current is None or previous is None:
            return {
                "label": "Sin dato",
                "value": "-",
                "tone": "neutral",
                "caption": "contra ayer",
            }
        delta = current - previous
        if round(abs(delta), precision) == 0:
            return {
                "label": "Sin cambio",
                "value": f"0{unit}",
                "tone": "neutral",
                "caption": "contra ayer",
            }
        direction = "Sube" if delta > 0 else "Baja"
        if lower_is_better:
            tone = "success" if delta < 0 else "danger"
        else:
            tone = "success" if delta > 0 else "warning"
        number = f"{delta:+.{precision}f}" if precision else f"{delta:+.0f}"
        return {
            "label": direction,
            "value": f"{number}{unit}",
            "tone": tone,
            "caption": "contra ayer",
        }

    def _percent_display(self, value):
        return "-" if value is None else f"{value:.1f}%"

    def _current_status_distribution(self):
        raw_counts = {
            item["status"]: item["count"]
            for item in SerializedUnit.objects.values("status").annotate(count=Count("id"))
        }
        total = sum(raw_counts.values())
        labels = dict(UnitStatus.choices)
        rows = []
        for status, label in UnitStatus.choices:
            count = raw_counts.get(status, 0)
            if not count:
                continue
            rows.append(
                {
                    "status": status,
                    "label": label,
                    "count": count,
                    "percent": round((count / total) * 100, 1) if total else 0,
                    "bar": round((count / total) * 100, 1) if total else 0,
                }
            )
        if not rows:
            rows.append({"status": "EMPTY", "label": "Sin unidades", "count": 0, "percent": 0, "bar": 0})
        return rows

    def _plan_status_distribution(self):
        raw_counts = {
            item["status"]: item["count"]
            for item in ProductionPlan.objects.values("status").annotate(count=Count("id"))
        }
        total = sum(raw_counts.values())
        rows = []
        for status, label in ProductionPlanStatus.choices:
            count = raw_counts.get(status, 0)
            if not count:
                continue
            rows.append(
                {
                    "status": status,
                    "label": label,
                    "count": count,
                    "bar": round((count / total) * 100, 1) if total else 0,
                }
            )
        if not rows:
            rows.append({"status": "EMPTY", "label": "Sin planes", "count": 0, "bar": 0})
        return rows

    def _station_dispersion(self):
        stations = list(
            AssemblyStation.objects.filter(is_active=True).select_related("line").order_by(
                "line__code",
                "sequence",
                "code",
            )
        )
        station_load = defaultdict(int)
        station_head_serials = defaultdict(str)
        active_queue_statuses = [
            ProductionQueueStatus.QUEUED,
            ProductionQueueStatus.READY,
            ProductionQueueStatus.IN_PROGRESS,
            ProductionQueueStatus.HOLD,
        ]
        for item in (
            ProductionQueueItem.objects.filter(status__in=active_queue_statuses)
            .select_related("unit", "route", "line")
            .order_by("line__code", "sequence", "id")
        ):
            next_step = item.next_route_step()
            if next_step and next_step.station_id:
                station_load[next_step.station_id] += 1
                station_head_serials.setdefault(next_step.station_id, item.unit.serial_number)

        station_pressure = defaultdict(int)
        station_quality = defaultdict(int)
        station_rework = defaultdict(int)
        station_andon = defaultdict(int)
        station_downtime = defaultdict(int)
        for row in QualityGate.objects.filter(is_blocking=True).exclude(
            status__in=[QualityGateStatus.PASSED, QualityGateStatus.WAIVED],
        ).values("station_id").annotate(count=Count("id")):
            if row["station_id"]:
                station_quality[row["station_id"]] = row["count"]
        for row in ReworkOrder.objects.exclude(
            status__in=[ReworkStatus.CLOSED, ReworkStatus.CANCELLED],
        ).values("station_detected_id").annotate(count=Count("id")):
            if row["station_detected_id"]:
                station_rework[row["station_detected_id"]] = row["count"]
        for row in AndonSignal.objects.filter(status__in=[AndonStatus.OPEN, AndonStatus.ACKNOWLEDGED]).values(
            "station_id"
        ).annotate(count=Count("id")):
            if row["station_id"]:
                station_andon[row["station_id"]] = row["count"]
        for row in ProductionDowntime.objects.filter(status=DowntimeStatus.OPEN).values("station_id").annotate(
            count=Count("id")
        ):
            if row["station_id"]:
                station_downtime[row["station_id"]] = row["count"]
        for station_id in {station.pk for station in stations}:
            station_pressure[station_id] = (
                station_quality[station_id]
                + station_rework[station_id]
                + station_andon[station_id]
                + station_downtime[station_id]
            )

        max_load = max(station_load.values() or [1])
        max_pressure = max(station_pressure.values() or [1])
        can_view_queue = self._has_perm("assembly.view_productionqueueitem")
        can_use_console = self._has_perm("assembly.add_unitstationevent")
        points = []
        for station in stations:
            load = station_load[station.pk]
            pressure = station_pressure[station.pk]
            x = 8 + round((load / max_load) * 84) if max_load else 8
            y = 8 + round((pressure / max_pressure) * 84) if max_pressure else 8
            tone = "danger" if pressure else "warning" if load else "neutral"
            queue_href = f"{reverse('assembly:queue_list')}?station={station.pk}"
            console_href = f"{reverse('assembly:station_console')}?station={station.pk}"
            href = queue_href if can_view_queue else console_href if can_use_console else ""
            cta = "Ver cola" if can_view_queue else "Abrir estacion" if can_use_console else ""
            points.append(
                {
                    "code": station.code,
                    "short_code": station.code[3:] if station.code.startswith("ST-") else station.code[:4],
                    "name": station.name,
                    "line": station.line.code,
                    "load": load,
                    "pressure": pressure,
                    "quality": station_quality[station.pk],
                    "rework": station_rework[station.pk],
                    "andon": station_andon[station.pk],
                    "downtime": station_downtime[station.pk],
                    "head_serial": station_head_serials[station.pk],
                    "x": x,
                    "y": y,
                    "tone": tone,
                    "href": href,
                    "queue_href": queue_href,
                    "console_href": console_href,
                    "cta": cta,
                }
            )
        return points

    def _open_issue_rows(self):
        rows = [
            {
                "label": "Andon activos",
                "value": AndonSignal.objects.filter(status__in=[AndonStatus.OPEN, AndonStatus.ACKNOWLEDGED]).count(),
                "href": reverse("assembly:andon_list"),
                "enabled": self._has_perm("assembly.view_andonsignal"),
            },
            {
                "label": "Paros abiertos",
                "value": ProductionDowntime.objects.filter(status=DowntimeStatus.OPEN).count(),
                "href": reverse("assembly:downtime_list"),
                "enabled": self._has_perm("assembly.view_productiondowntime"),
            },
            {
                "label": "Calidad pendiente",
                "value": QualityGate.objects.filter(is_blocking=True)
                .exclude(status__in=[QualityGateStatus.PASSED, QualityGateStatus.WAIVED])
                .count(),
                "href": reverse("assembly:quality_list"),
                "enabled": self._has_perm("assembly.view_qualitygate"),
            },
            {
                "label": "Retrabajos abiertos",
                "value": ReworkOrder.objects.exclude(status__in=[ReworkStatus.CLOSED, ReworkStatus.CANCELLED]).count(),
                "href": reverse("assembly:rework_list"),
                "enabled": self._has_perm("assembly.view_reworkorder"),
            },
            {
                "label": "Eventos offline pendientes",
                "value": StationOfflineEvent.objects.filter(status=StationOfflineEventStatus.PENDING).count(),
                "href": reverse("assembly:offline_list"),
                "enabled": self._has_perm("assembly.view_stationofflineevent"),
            },
            {
                "label": "Kits externos abiertos",
                "value": ExternalMaterialKit.objects.filter(
                    status__in=[ExternalMaterialKitStatus.PLANNED, ExternalMaterialKitStatus.HOLD],
                ).count(),
                "href": reverse("assembly:kit_list"),
                "enabled": self._has_perm("assembly.view_externalmaterialkit"),
            },
        ]
        rows = [row for row in rows if row["enabled"]]
        max_value = max([row["value"] for row in rows] or [1])
        for row in rows:
            row["bar"] = round((row["value"] / max_value) * 100, 1) if max_value else 0
        return rows

    def _workflow_steps(self, counts, is_tenant_admin, can_view_metrics):
        return [
            {
                "number": "01",
                "phase": "Preparar",
                "title": "Base de planta",
                "summary": "Empresa, usuarios, productos, versiones, lineas, estaciones, rutas, pasos y equipos.",
                "status": f"{counts['products']} productos / {counts['stations']} estaciones",
                "href": reverse("core:settings") if is_tenant_admin else "",
                "cta": "Abrir configuracion",
                "enabled": is_tenant_admin,
            },
            {
                "number": "02",
                "phase": "Planear",
                "title": "Plan y mix",
                "summary": "Define que versiones se fabrican, cantidades, turno, prioridad y mezcla de modelos.",
                "status": f"{counts['active_plans']} planes activos / {counts['active_mixes']} mix activos",
                "href": reverse("assembly:plan_list"),
                "cta": "Ver planes",
                "enabled": self._has_perm("assembly.view_productionplan"),
            },
            {
                "number": "03",
                "phase": "Secuenciar",
                "title": "Orden de linea",
                "summary": "Ordena unidades por linea, prioridad y siguiente estacion de trabajo.",
                "status": f"{counts['queue_items']} unidades en secuencia",
                "href": reverse("assembly:queue_list"),
                "cta": "Ver secuencia",
                "enabled": self._has_perm("assembly.view_productionqueueitem"),
            },
            {
                "number": "04",
                "phase": "Ejecutar",
                "title": "Consola de estacion",
                "summary": "Registra inicio, pausa, completado, fallas, componentes y trazabilidad por serial.",
                "status": f"{counts['wip_units']} unidades en proceso",
                "href": reverse("assembly:station_console"),
                "cta": "Abrir estacion",
                "enabled": self._has_perm("assembly.add_unitstationevent"),
            },
            {
                "number": "05",
                "phase": "Controlar",
                "title": "Calidad y Andon",
                "summary": "Gestiona controles bloqueantes, retrabajos, paros, alertas Andon y eventos offline.",
                "status": f"{counts['open_alerts']} focos abiertos",
                "href": reverse("assembly:advanced"),
                "cta": "Ver focos",
                "enabled": self._has_perm("assembly.view_andonsignal")
                or self._has_perm("assembly.view_productiondowntime")
                or self._has_perm("assembly.view_qualitygate"),
            },
            {
                "number": "06",
                "phase": "Liberar",
                "title": "Cierre del serial",
                "summary": "Valida as-built, calidad, retrabajos cerrados y aprobacion final de liberacion.",
                "status": f"{counts['released_today']} liberadas hoy",
                "href": reverse("assembly:release_list"),
                "cta": "Ver liberacion",
                "enabled": self._has_perm("assembly.view_releaseapproval"),
            },
            {
                "number": "07",
                "phase": "Analizar",
                "title": "Indicadores MES",
                "summary": "Revisa cumplimiento, takt, productividad, calidad, paros y tendencia por dia.",
                "status": f"{counts['completed_today']} terminadas hoy",
                "href": reverse("assembly:metrics") if can_view_metrics else "",
                "cta": "Ver indicadores",
                "enabled": can_view_metrics,
            },
        ]

    def _setup_checklist(self, counts, is_tenant_admin):
        checks = [
            ("Empresa y usuarios", counts["active_users"] > 0, f"{counts['active_users']} usuarios activos"),
            ("Producto y version", counts["products"] > 0 and counts["versions"] > 0, f"{counts['products']} productos / {counts['versions']} versiones"),
            ("Linea y estaciones", counts["lines"] > 0 and counts["stations"] > 0, f"{counts['lines']} lineas / {counts['stations']} estaciones"),
            ("Ruta y pasos", counts["routes"] > 0 and counts["steps"] > 0, f"{counts['routes']} rutas / {counts['steps']} pasos"),
            ("Equipos e integraciones", counts["equipment"] > 0, f"{counts['equipment_ready']} de {counts['equipment']} habilitados"),
            ("Plan activo", counts["active_plans"] > 0, f"{counts['active_plans']} planes activos"),
        ]
        href = reverse("core:settings") if is_tenant_admin else ""
        return [
            {
                "label": label,
                "complete": complete,
                "detail": detail,
                "href": href,
                "enabled": bool(href),
            }
            for label, complete, detail in checks
        ]

    def _next_actions(self, counts, can_view_metrics):
        candidates = [
            (
                counts["pending_offline"] > 0,
                "Sincronizar eventos offline",
                f"{counts['pending_offline']} pendientes desde piso de planta",
                reverse("assembly:offline_list"),
                self._has_perm("assembly.view_stationofflineevent"),
            ),
            (
                counts["open_downtime"] > 0,
                "Cerrar o explicar paros abiertos",
                f"{counts['open_downtime']} paros afectan disponibilidad",
                reverse("assembly:downtime_list"),
                self._has_perm("assembly.view_productiondowntime"),
            ),
            (
                counts["pending_quality"] > 0,
                "Resolver calidad pendiente",
                f"{counts['pending_quality']} controles bloqueantes",
                reverse("assembly:quality_list"),
                self._has_perm("assembly.view_qualitygate"),
            ),
            (
                counts["open_rework"] > 0,
                "Atender retrabajos",
                f"{counts['open_rework']} correcciones abiertas",
                reverse("assembly:rework_list"),
                self._has_perm("assembly.view_reworkorder"),
            ),
            (
                counts["open_kits"] > 0,
                "Revisar kits externos B22",
                f"{counts['open_kits']} kits planificados o retenidos",
                reverse("assembly:kit_list"),
                self._has_perm("assembly.view_externalmaterialkit"),
            ),
            (
                counts["active_plans"] == 0,
                "Crear o liberar plan de produccion",
                "No hay plan activo para ejecutar",
                reverse("assembly:plan_list"),
                self._has_perm("assembly.view_productionplan"),
            ),
            (
                counts["active_plans"] > 0,
                "Abrir consola de estacion",
                f"{counts['queue_items']} unidades disponibles en secuencia",
                reverse("assembly:station_console"),
                self._has_perm("assembly.add_unitstationevent"),
            ),
            (
                can_view_metrics,
                "Ver indicadores detallados",
                "Takt, calidad, cumplimiento y tendencia",
                reverse("assembly:metrics"),
                can_view_metrics,
            ),
        ]
        actions = [
            {"label": label, "detail": detail, "href": href}
            for condition, label, detail, href, enabled in candidates
            if condition and enabled
        ]
        return actions[:5]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        can_view_production = self._can_view_production()
        is_tenant_admin = self._is_tenant_admin()
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        trend_days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]

        if not can_view_production:
            context.update(
                {
                    "can_view_production": False,
                    "is_tenant_admin": is_tenant_admin,
                    "tenant_name": getattr(getattr(self.request, "tenant", None), "name", "Kore Serial"),
                    "module_cards": self._admin_module_cards(is_tenant_admin),
                }
            )
            return context

        can_view_metrics = self._can_view_metrics()
        metrics_href = reverse("assembly:metrics") if can_view_metrics else ""
        can_view_plans = self._has_perm("assembly.view_productionplan")
        can_view_quality = self._has_perm("assembly.view_qualitygate")
        can_view_downtime = self._has_perm("assembly.view_productiondowntime")
        can_view_release = self._has_perm("assembly.view_releaseapproval")
        can_view_advanced = (
            self._has_perm("assembly.view_andonsignal")
            or self._has_perm("assembly.view_productiondowntime")
            or self._has_perm("assembly.view_stationofflineevent")
            or self._has_perm("assembly.view_modelmixplan")
            or self._has_perm("assembly.view_externalmaterialkit")
        )
        today_snapshot = self._daily_snapshot(today)
        yesterday_snapshot = self._daily_snapshot(yesterday)
        trend_rows = [self._daily_snapshot(day) for day in trend_days]
        max_daily = max([row["planned"] for row in trend_rows] + [row["completed"] for row in trend_rows] + [1])
        for row in trend_rows:
            row["planned_bar"] = round((row["planned"] / max_daily) * 100, 1)
            row["completed_bar"] = round((row["completed"] / max_daily) * 100, 1)

        open_andon = AndonSignal.objects.filter(status__in=[AndonStatus.OPEN, AndonStatus.ACKNOWLEDGED]).count()
        open_downtime = ProductionDowntime.objects.filter(status=DowntimeStatus.OPEN).count()
        pending_quality = (
            QualityGate.objects.filter(is_blocking=True)
            .exclude(status__in=[QualityGateStatus.PASSED, QualityGateStatus.WAIVED])
            .count()
        )
        open_rework = ReworkOrder.objects.exclude(status__in=[ReworkStatus.CLOSED, ReworkStatus.CANCELLED]).count()
        current_alerts = open_andon + open_downtime + pending_quality + open_rework
        alerts_today = (
            AndonSignal.objects.filter(opened_at__date=today).count()
            + ProductionDowntime.objects.filter(started_at__date=today).count()
            + ReworkOrder.objects.filter(opened_at__date=today).count()
            + QualityGate.objects.filter(status=QualityGateStatus.FAILED, inspected_at__date=today).count()
        )
        alerts_yesterday = (
            AndonSignal.objects.filter(opened_at__date=yesterday).count()
            + ProductionDowntime.objects.filter(started_at__date=yesterday).count()
            + ReworkOrder.objects.filter(opened_at__date=yesterday).count()
            + QualityGate.objects.filter(status=QualityGateStatus.FAILED, inspected_at__date=yesterday).count()
        )
        released_today = ReleaseApproval.objects.filter(
            decision=ReleaseDecision.APPROVED,
            decided_at__date=today,
        ).count()
        released_yesterday = ReleaseApproval.objects.filter(
            decision=ReleaseDecision.APPROVED,
            decided_at__date=yesterday,
        ).count()
        active_lines = AssemblyLine.objects.filter(is_active=True).count()
        shift_seconds = max(active_lines, 1) * 8 * 3600
        availability_today = (
            max(0, round((1 - (today_snapshot["downtime_seconds"] / shift_seconds)) * 100, 1))
            if active_lines
            else None
        )
        availability_yesterday = (
            max(0, round((1 - (yesterday_snapshot["downtime_seconds"] / shift_seconds)) * 100, 1))
            if active_lines
            else None
        )

        active_plans = ProductionPlan.objects.filter(
            status__in=[ProductionPlanStatus.RELEASED, ProductionPlanStatus.IN_EXECUTION],
        ).count()
        active_mixes = ModelMixPlan.objects.filter(status=ModelMixPlanStatus.ACTIVE).count()
        queue_items = ProductionQueueItem.objects.filter(
            status__in=[
                ProductionQueueStatus.QUEUED,
                ProductionQueueStatus.READY,
                ProductionQueueStatus.IN_PROGRESS,
                ProductionQueueStatus.HOLD,
            ],
        ).count()
        wip_units = SerializedUnit.objects.filter(
            status__in=[UnitStatus.IN_PROCESS, UnitStatus.QUALITY_HOLD, UnitStatus.REWORK],
        ).count()
        pending_offline = StationOfflineEvent.objects.filter(status=StationOfflineEventStatus.PENDING).count()
        open_kits = ExternalMaterialKit.objects.filter(
            status__in=[ExternalMaterialKitStatus.PLANNED, ExternalMaterialKitStatus.HOLD],
        ).count()
        equipment_count = EquipmentIntegration.objects.count()
        unavailable_equipment = sum(1 for equipment in EquipmentIntegration.objects.all() if not equipment.can_be_used)
        equipment_ready = equipment_count - unavailable_equipment
        active_users = TenantMembership.objects.filter(is_active=True).count()
        counts = {
            "products": AssembledProduct.objects.count(),
            "versions": ProductVersion.objects.count(),
            "lines": AssemblyLine.objects.count(),
            "stations": AssemblyStation.objects.count(),
            "routes": AssemblyRoute.objects.count(),
            "steps": AssemblyRouteStep.objects.count(),
            "active_plans": active_plans,
            "active_mixes": active_mixes,
            "queue_items": queue_items,
            "wip_units": wip_units,
            "open_alerts": current_alerts,
            "open_downtime": open_downtime,
            "pending_quality": pending_quality,
            "open_rework": open_rework,
            "pending_offline": pending_offline,
            "open_kits": open_kits,
            "released_today": released_today,
            "completed_today": today_snapshot["completed"],
            "active_users": active_users,
            "equipment": equipment_count,
            "equipment_ready": equipment_ready,
        }

        context.update(
            {
                "can_view_production": True,
                "can_view_metrics": can_view_metrics,
                "is_tenant_admin": is_tenant_admin,
                "tenant_name": getattr(getattr(self.request, "tenant", None), "name", "Kore Serial"),
                "today_label": today.strftime("%d/%m/%Y"),
                "kpi_cards": [
                    {
                        "label": "Terminadas hoy",
                        "value": today_snapshot["completed"],
                        "detail": f"{today_snapshot['planned']} planificadas",
                        "trend": self._delta(today_snapshot["completed"], yesterday_snapshot["completed"]),
                        "href": metrics_href,
                        "enabled": bool(metrics_href),
                    },
                    {
                        "label": "Cumplimiento del plan",
                        "value": self._percent_display(today_snapshot["fulfillment_percent"]),
                        "detail": "produccion real contra plan del dia",
                        "trend": self._delta(
                            today_snapshot["fulfillment_percent"],
                            yesterday_snapshot["fulfillment_percent"],
                            unit=" pp",
                            precision=1,
                        ),
                        "href": reverse("assembly:plan_list") if can_view_plans else "",
                        "enabled": can_view_plans,
                    },
                    {
                        "label": "Calidad base MES",
                        "value": self._percent_display(today_snapshot["quality_percent"]),
                        "detail": f"{today_snapshot['failures']} fallas registradas hoy",
                        "trend": self._delta(
                            today_snapshot["quality_percent"],
                            yesterday_snapshot["quality_percent"],
                            unit=" pp",
                            precision=1,
                        ),
                        "href": reverse("assembly:quality_list") if can_view_quality else "",
                        "enabled": can_view_quality,
                    },
                    {
                        "label": "Disponibilidad estimada",
                        "value": self._percent_display(availability_today),
                        "detail": f"{today_snapshot['downtime_label']} en paros hoy",
                        "trend": self._delta(
                            availability_today,
                            availability_yesterday,
                            unit=" pp",
                            precision=1,
                        ),
                        "href": reverse("assembly:downtime_list") if can_view_downtime else "",
                        "enabled": can_view_downtime,
                    },
                    {
                        "label": "Alertas abiertas",
                        "value": current_alerts,
                        "detail": f"{open_andon} Andon / {open_downtime} paros",
                        "trend": self._delta(alerts_today, alerts_yesterday, lower_is_better=True),
                        "href": reverse("assembly:advanced") if can_view_advanced else "",
                        "enabled": can_view_advanced,
                    },
                    {
                        "label": "Liberadas hoy",
                        "value": released_today,
                        "detail": f"{wip_units} unidades en WIP",
                        "trend": self._delta(released_today, released_yesterday),
                        "href": reverse("assembly:release_list") if can_view_release else "",
                        "enabled": can_view_release,
                    },
                ],
                "trend_rows": trend_rows,
                "workflow_steps": self._workflow_steps(counts, is_tenant_admin, can_view_metrics),
                "setup_checklist": self._setup_checklist(counts, is_tenant_admin),
                "next_actions": self._next_actions(counts, can_view_metrics),
                "unit_status_rows": self._current_status_distribution(),
                "plan_status_rows": self._plan_status_distribution(),
                "station_points": self._station_dispersion(),
                "open_issue_rows": self._open_issue_rows(),
                "recent_alerts": list(
                    AndonSignal.objects.filter(status__in=[AndonStatus.OPEN, AndonStatus.ACKNOWLEDGED])
                    .select_related("line", "station")
                    .order_by("-opened_at")[:5]
                ),
                "module_cards": [
                    {
                        "label": "Produccion",
                        "metric": "planes activos",
                        "value": active_plans,
                        "href": reverse("assembly:index"),
                        "enabled": True,
                    },
                    {
                        "label": "MES avanzado",
                        "metric": "mix, Andon, paros, offline",
                        "value": active_mixes,
                        "href": reverse("assembly:advanced"),
                        "enabled": True,
                    },
                    {
                        "label": "Calidad",
                        "metric": "pendientes bloqueantes",
                        "value": pending_quality,
                        "href": reverse("assembly:quality_list"),
                        "enabled": True,
                    },
                    {
                        "label": "Integraciones",
                        "metric": f"{pending_offline} offline / {open_kits} kits abiertos",
                        "value": equipment_ready,
                        "href": reverse("assembly:equipment_list"),
                        "enabled": True,
                    },
                ]
                + self._admin_module_cards(is_tenant_admin, active_users),
            }
        )
        return context

    def _admin_module_cards(self, is_tenant_admin, active_users=None):
        if not is_tenant_admin:
            return []
        return [
            {
                "label": "Usuarios",
                "metric": "usuarios activos",
                "value": active_users if active_users is not None else TenantMembership.objects.filter(is_active=True).count(),
                "href": reverse("tenant_users"),
                "enabled": True,
            },
            {
                "label": "Configuracion",
                "metric": "maestros y parametros",
                "value": "OK",
                "href": reverse("core:settings"),
                "enabled": True,
            },
        ]


class PublicDashboardView(TemplateView):
    template_name = "public_dashboard.html"
