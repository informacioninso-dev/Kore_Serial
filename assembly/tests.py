from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from datetime import timedelta
from decimal import Decimal
from django.test import Client
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from core.models import EquipmentIntegration, OperationalAuditEvent
from tenants.models import TenantMembership

from .models import (
    AndonSeverity,
    AndonSignal,
    AndonStatus,
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    ComponentTraceability,
    DowntimeCauseCategory,
    DowntimeStatus,
    EquipmentInboundEvent,
    EquipmentInboundEventStatus,
    ExternalMaterialKit,
    ExternalMaterialKitStatus,
    InstalledComponent,
    LineBalanceStatus,
    LineBalanceStudy,
    MeasurementResult,
    ModelMixPlan,
    ModelMixPlanItem,
    ModelMixPlanStatus,
    Plant,
    PlantArea,
    ProductVersion,
    ProductiveParameterOrigin,
    ProductiveParameterType,
    ProductionDowntime,
    ProductionMeasurement,
    ProductionOrder,
    ProductionOrderStatus,
    ProductionPlan,
    ProductionPlanPriority,
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
    RouteStepParameter,
    SerializedUnit,
    StationOfflineEvent,
    StationOfflineEventStatus,
    StationEventSource,
    StationEventType,
    UnitStationEvent,
    UnitStatus,
)
from .services import record_station_event


class SerializedUnitTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Empresa de prueba"

    @staticmethod
    def get_test_tenant_domain():
        return "serial.test.com"

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        self.user = get_user_model().objects.create_user(username="operator", password="StrongPass.2026")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        permission = Permission.objects.get(codename="view_serializedunit", content_type__app_label="assembly")
        self.user.user_permissions.add(permission)
        self.product = AssembledProduct.objects.create(code="MODEL-X", name="Modelo X", created_by=self.user, updated_by=self.user)
        self.version = ProductVersion.objects.create(product=self.product, code="BASE", name="Base", created_by=self.user, updated_by=self.user)
        self.client.force_login(self.user)

    def grant_permissions(self, *codenames):
        permissions = Permission.objects.filter(codename__in=codenames)
        self.user.user_permissions.add(*permissions)

    def create_unit(self, serial_number, status=UnitStatus.REGISTERED):
        return SerializedUnit.objects.create(
            version=self.version,
            serial_number=serial_number,
            status=status,
            created_by=self.user,
            updated_by=self.user,
        )

    def create_station_route_step(self):
        line = AssemblyLine.objects.create(
            code="LINE-1",
            name="Linea principal",
            created_by=self.user,
            updated_by=self.user,
        )
        station = AssemblyStation.objects.create(
            line=line,
            code="ST-01",
            name="Montaje inicial",
            sequence=1,
            created_by=self.user,
            updated_by=self.user,
        )
        route = AssemblyRoute.objects.create(
            version=self.version,
            code="MAIN",
            name="Ruta principal",
            created_by=self.user,
            updated_by=self.user,
        )
        step = AssemblyRouteStep.objects.create(
            route=route,
            station=station,
            sequence=1,
            name="Ingreso a linea",
            requires_component_trace=True,
            requires_quality_gate=True,
            created_by=self.user,
            updated_by=self.user,
        )
        return station, route, step

    def create_production_plan(self, code="PLAN-001", target_quantity=3, status=ProductionPlanStatus.DRAFT):
        station, _route, _step = self.create_station_route_step()
        return ProductionPlan.objects.create(
            code=code,
            version=self.version,
            line=station.line,
            planned_date=timezone.localdate(),
            shift="Turno A",
            target_quantity=target_quantity,
            status=status,
            priority=ProductionPlanPriority.NORMAL,
            created_by=self.user,
            updated_by=self.user,
        )

    def test_unit_is_individual_and_logs_its_registration(self):
        unit = self.create_unit("SER-0001")

        self.assertEqual(unit.serial_number, "SER-0001")
        self.assertEqual(unit.version.product, self.product)
        self.assertIsNotNone(unit.created_at)
        self.assertEqual(unit.created_by, self.user)
        event = OperationalAuditEvent.objects.get(document_code="SER-0001")
        self.assertEqual(event.action, "CREATE")
        self.assertEqual(event.actor, self.user)

    def test_list_requires_the_module_permission(self):
        self.create_unit("SER-0001")
        anonymous = Client()
        anonymous.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        response = anonymous.get("/ensamblaje/unidades/")
        self.assertEqual(response.status_code, 302)

        unprivileged = get_user_model().objects.create_user(username="viewer", password="StrongPass.2026")
        TenantMembership.objects.create(tenant=self.tenant, user=unprivileged, is_active=True)
        anonymous.force_login(unprivileged)
        response = anonymous.get("/ensamblaje/unidades/")
        self.assertEqual(response.status_code, 403)

    def test_list_filters_and_preserves_filters_in_pagination(self):
        self.create_unit("SER-0001", UnitStatus.COMPLETED)
        self.create_unit("SER-0002", UnitStatus.IN_PROCESS)

        response = self.client.get("/ensamblaje/unidades/", {"q": "0001", "status": UnitStatus.COMPLETED, "per_page": 50})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SER-0001")
        self.assertNotContains(response, "SER-0002")
        self.assertContains(response, 'name="q" value="0001"', html=False)
        self.assertContains(response, 'name="status" value="COMPLETED"', html=False)
        self.assertContains(response, 'value="50" selected', html=False)

    def test_pagination_preserves_all_list_filters(self):
        for index in range(21):
            self.create_unit(f"SER-{index:04}", UnitStatus.IN_PROCESS)

        response = self.client.get(
            "/ensamblaje/unidades/",
            {"q": "SER", "status": UnitStatus.IN_PROCESS, "per_page": 20},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pagina 1 de 2")
        self.assertContains(
            response,
            "?page=2&q=SER&status=IN_PROCESS&per_page=20",
            html=False,
        )

    def test_station_event_is_unit_based_and_audited(self):
        unit = self.create_unit("SER-0100")
        station, _route, step = self.create_station_route_step()

        event = UnitStationEvent.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            event_type=StationEventType.STARTED,
            operator=self.user,
            created_by=self.user,
            updated_by=self.user,
        )

        self.assertEqual(event.unit, unit)
        self.assertEqual(event.station, station)
        self.assertTrue(
            OperationalAuditEvent.objects.filter(
                document_type="Evento de estacion",
                document_code="SER-0100",
                related_code="ST-01",
            ).exists()
        )

    def test_station_event_rejects_step_from_other_unit_version(self):
        other_product = AssembledProduct.objects.create(
            code="MODEL-Y",
            name="Modelo Y",
            created_by=self.user,
            updated_by=self.user,
        )
        other_version = ProductVersion.objects.create(
            product=other_product,
            code="BASE",
            name="Base",
            created_by=self.user,
            updated_by=self.user,
        )
        unit = self.create_unit("SER-0101")
        station, _route, _step = self.create_station_route_step()
        other_route = AssemblyRoute.objects.create(
            version=other_version,
            code="MAIN",
            name="Ruta otra version",
            created_by=self.user,
            updated_by=self.user,
        )
        other_step = AssemblyRouteStep.objects.create(
            route=other_route,
            station=station,
            sequence=1,
            name="Paso incompatible",
            created_by=self.user,
            updated_by=self.user,
        )

        event = UnitStationEvent(
            unit=unit,
            station=station,
            route_step=other_step,
            event_type=StationEventType.STARTED,
            operator=self.user,
        )

        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_installed_component_supports_serial_and_lot_traceability(self):
        unit = self.create_unit("SER-0200")
        station, _route, step = self.create_station_route_step()

        component = InstalledComponent(
            unit=unit,
            station=station,
            route_step=step,
            part_code="PART-001",
            quantity=1,
        )
        with self.assertRaises(ValidationError):
            component.full_clean()

        traced = InstalledComponent(
            unit=unit,
            station=station,
            route_step=step,
            part_code="PART-001",
            serial_number="COMP-SER-001",
            lot_number="LOT-001",
            quantity=1,
            installed_by=self.user,
        )
        traced.full_clean()

    def test_component_requirement_enforces_traceability_and_part_match(self):
        unit = self.create_unit("SER-0201")
        station, _route, step = self.create_station_route_step()
        requirement = RouteStepComponentRequirement.objects.create(
            route_step=step,
            part_code="FRAME-001",
            part_name="Bastidor",
            traceability=ComponentTraceability.SERIAL,
            is_critical=True,
            created_by=self.user,
            updated_by=self.user,
        )

        missing_serial = InstalledComponent(
            unit=unit,
            station=station,
            route_step=step,
            requirement=requirement,
            part_code="FRAME-001",
            quantity=1,
        )
        with self.assertRaises(ValidationError):
            missing_serial.full_clean()

        wrong_part = InstalledComponent(
            unit=unit,
            station=station,
            route_step=step,
            requirement=requirement,
            part_code="OTHER-001",
            serial_number="FRAME-SER-001",
            quantity=1,
        )
        with self.assertRaises(ValidationError):
            wrong_part.full_clean()

        traced = InstalledComponent(
            unit=unit,
            station=station,
            route_step=step,
            requirement=requirement,
            part_code="FRAME-001",
            serial_number="FRAME-SER-001",
            quantity=1,
        )
        traced.full_clean()

    def test_release_is_blocked_by_missing_required_as_built(self):
        unit = self.create_unit("SER-0202")
        station, _route, step = self.create_station_route_step()
        requirement = RouteStepComponentRequirement.objects.create(
            route_step=step,
            part_code="PART-REQ",
            part_name="Parte requerida",
            traceability=ComponentTraceability.SERIAL,
            is_critical=True,
            created_by=self.user,
            updated_by=self.user,
        )
        QualityGate.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            status=QualityGateStatus.PASSED,
            is_blocking=True,
            inspected_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )

        release = ReleaseApproval(unit=unit, decision=ReleaseDecision.APPROVED, decided_by=self.user)
        with self.assertRaises(ValidationError):
            release.full_clean()

        InstalledComponent.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            requirement=requirement,
            part_code="PART-REQ",
            serial_number="REQ-SER-001",
            quantity=1,
            installed_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        release.full_clean()

    def test_release_is_blocked_by_quality_and_open_rework(self):
        unit = self.create_unit("SER-0300")
        station, _route, step = self.create_station_route_step()
        gate = QualityGate.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            status=QualityGateStatus.PENDING,
            is_blocking=True,
            created_by=self.user,
            updated_by=self.user,
        )

        release = ReleaseApproval(
            unit=unit,
            decision=ReleaseDecision.APPROVED,
            decided_by=self.user,
        )
        with self.assertRaises(ValidationError):
            release.full_clean()

        gate.status = QualityGateStatus.PASSED
        gate.inspected_by = self.user
        gate.inspected_at = gate.updated_at
        gate.save(update_fields=["status", "inspected_by", "inspected_at", "updated_at"])
        rework = ReworkOrder.objects.create(
            unit=unit,
            station_detected=station,
            route_step_detected=step,
            defect_code="DEF-001",
            description="Ajuste requerido antes de liberar.",
            opened_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        with self.assertRaises(ValidationError):
            release.full_clean()

        rework.close(self.user, "Retrabajo verificado.")
        release.full_clean()

    def test_production_plan_generates_serialized_units(self):
        plan = self.create_production_plan("PLAN-GEN", target_quantity=3)

        units = plan.generate_serialized_units(self.user, 2, "KS-P5")

        self.assertEqual(len(units), 2)
        self.assertEqual(plan.linked_quantity, 2)
        self.assertEqual(plan.remaining_quantity, 1)
        self.assertEqual([unit.serial_number for unit in units], ["KS-P5-0001", "KS-P5-0002"])
        self.assertEqual(
            SerializedUnit.objects.filter(
                production_plan=plan,
                version=self.version,
                status=UnitStatus.REGISTERED,
            ).count(),
            2,
        )

    def test_production_order_links_plan_and_generated_units(self):
        plant = Plant.objects.create(code="PLANT-1", name="Planta 1", created_by=self.user, updated_by=self.user)
        area = PlantArea.objects.create(
            plant=plant,
            code="ASM",
            name="Ensamble",
            created_by=self.user,
            updated_by=self.user,
        )
        station, _route, _step = self.create_station_route_step()
        station.line.area = area
        station.line.save(update_fields=["area", "updated_at"])
        order = ProductionOrder.objects.create(
            code="OP-001",
            product=self.product,
            version=self.version,
            plant=plant,
            target_quantity=3,
            status=ProductionOrderStatus.RELEASED,
            created_by=self.user,
            updated_by=self.user,
        )
        plan = ProductionPlan.objects.create(
            code="PLAN-OP",
            production_order=order,
            version=self.version,
            line=station.line,
            planned_date=timezone.localdate(),
            shift="Turno A",
            target_quantity=2,
            created_by=self.user,
            updated_by=self.user,
        )

        plan.full_clean()
        units = plan.generate_serialized_units(self.user, 2, "OP-UNIT")

        self.assertEqual(order.planned_quantity, 2)
        self.assertEqual(order.linked_unit_quantity, 2)
        self.assertEqual(order.progress_percent, 67)
        self.assertTrue(all(unit.production_order_id == order.pk for unit in units))

    def test_production_plan_generation_respects_target_quantity(self):
        plan = self.create_production_plan("PLAN-LIMIT", target_quantity=1)

        with self.assertRaises(ValidationError):
            plan.generate_serialized_units(self.user, 2, "KS-LIMIT")

    def test_production_plan_links_existing_unit(self):
        plan = self.create_production_plan("PLAN-LINK", target_quantity=2)
        unit = self.create_unit("SER-LINK-001")

        linked = plan.link_unit(unit, self.user)

        self.assertEqual(linked.production_plan, plan)
        self.assertEqual(plan.linked_quantity, 1)

    def test_required_measurement_blocks_release_until_passed(self):
        unit = self.create_unit("SER-MEAS-001", UnitStatus.COMPLETED)
        station, _route, step = self.create_station_route_step()
        parameter = RouteStepParameter.objects.create(
            route_step=step,
            code="TORQUE-REQ",
            name="Torque requerido",
            parameter_type=ProductiveParameterType.NUMERIC,
            unit="Nm",
            min_value=Decimal("10.0000"),
            max_value=Decimal("20.0000"),
            origin=ProductiveParameterOrigin.MANUAL,
            is_required=True,
            created_by=self.user,
            updated_by=self.user,
        )
        QualityGate.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            status=QualityGateStatus.PASSED,
            is_blocking=True,
            inspected_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        release = ReleaseApproval(unit=unit, decision=ReleaseDecision.APPROVED, decided_by=self.user)

        with self.assertRaises(ValidationError):
            release.full_clean()

        measurement = ProductionMeasurement.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            parameter=parameter,
            code=parameter.code,
            name=parameter.name,
            value=Decimal("8.0000"),
            measured_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        self.assertEqual(measurement.result, MeasurementResult.FAIL)
        with self.assertRaises(ValidationError):
            release.full_clean()

        measurement.value = Decimal("12.0000")
        measurement.save()

        measurement.refresh_from_db()
        self.assertEqual(measurement.result, MeasurementResult.PASS)
        release.full_clean()

    def test_production_plan_action_generates_units_from_screen(self):
        self.grant_permissions("view_productionplan", "change_productionplan", "add_serializedunit")
        plan = self.create_production_plan("PLAN-UI", target_quantity=2)

        response = self.client.post(
            f"/produccion/planes/{plan.pk}/gestionar/",
            {
                "action": "generate",
                "quantity": 2,
                "serial_prefix": "KS-UI",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(SerializedUnit.objects.filter(production_plan=plan).count(), 2)

    def test_production_plan_generates_queue_items(self):
        plan = self.create_production_plan("PLAN-SEQ", target_quantity=2, status=ProductionPlanStatus.RELEASED)
        plan.generate_serialized_units(self.user, 2, "KS-SEQ")

        items = plan.create_queue_items(self.user)

        self.assertEqual(len(items), 2)
        self.assertEqual([item.sequence for item in items], [1, 2])
        self.assertTrue(all(item.line == plan.line for item in items))
        self.assertTrue(all(item.status == ProductionQueueStatus.QUEUED for item in items))
        self.assertTrue(all(item.route.version == plan.version for item in items))

    def test_production_queue_resequence_logs_audit(self):
        plan = self.create_production_plan("PLAN-RESEQ", target_quantity=3, status=ProductionPlanStatus.RELEASED)
        plan.generate_serialized_units(self.user, 3, "KS-RESEQ")
        plan.create_queue_items(self.user)
        last_item = ProductionQueueItem.objects.get(unit__serial_number="KS-RESEQ-0003")

        last_item.resequence(1, self.user, "Prioridad de entrega.")

        ordered_serials = list(
            ProductionQueueItem.objects.filter(line=plan.line).order_by("sequence").values_list("unit__serial_number", flat=True)
        )
        self.assertEqual(ordered_serials, ["KS-RESEQ-0003", "KS-RESEQ-0001", "KS-RESEQ-0002"])
        self.assertTrue(
            OperationalAuditEvent.objects.filter(
                document_type="Secuencia de linea",
                document_code="KS-RESEQ-0003",
                action="UPDATE",
                from_status="3",
                to_status="1",
            ).exists()
        )

    def test_production_plan_action_generates_queue_from_screen(self):
        self.grant_permissions("view_productionplan", "change_productionplan", "add_productionqueueitem")
        plan = self.create_production_plan("PLAN-SEQ-UI", target_quantity=2, status=ProductionPlanStatus.RELEASED)
        plan.generate_serialized_units(self.user, 2, "KS-SEQUI")

        response = self.client.post(
            f"/produccion/planes/{plan.pk}/gestionar/",
            {
                "action": "sequence",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ProductionQueueItem.objects.filter(production_plan=plan).count(), 2)

    def test_station_queue_view_shows_next_station_work(self):
        self.grant_permissions("view_productionqueueitem")
        plan = self.create_production_plan("PLAN-STATION", target_quantity=1, status=ProductionPlanStatus.RELEASED)
        plan.generate_serialized_units(self.user, 1, "KS-STATION")
        item = plan.create_queue_items(self.user)[0]

        response = self.client.get("/produccion/secuencia/estaciones/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, item.unit.serial_number)
        self.assertContains(response, item.next_station.code)

    def test_quality_review_closes_gate_and_updates_unit_status(self):
        self.grant_permissions("change_qualitygate", "view_qualitygate")
        unit = self.create_unit("SER-0350", UnitStatus.QUALITY_HOLD)
        station, _route, step = self.create_station_route_step()
        gate = QualityGate.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            status=QualityGateStatus.PENDING,
            is_blocking=True,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(
            f"/produccion/calidad/{gate.pk}/revisar/",
            {
                "status": QualityGateStatus.PASSED,
                "evidence_reference": "QA-EVID-001",
                "notes": "Control conforme.",
            },
        )

        self.assertEqual(response.status_code, 302)
        gate.refresh_from_db()
        unit.refresh_from_db()
        self.assertEqual(gate.status, QualityGateStatus.PASSED)
        self.assertEqual(gate.inspected_by, self.user)
        self.assertIsNotNone(gate.inspected_at)
        self.assertEqual(gate.evidence_reference, "QA-EVID-001")
        self.assertEqual(unit.status, UnitStatus.COMPLETED)

    def test_quality_review_failure_keeps_unit_on_quality_hold(self):
        self.grant_permissions("change_qualitygate", "view_qualitygate")
        unit = self.create_unit("SER-0351", UnitStatus.QUALITY_HOLD)
        station, _route, step = self.create_station_route_step()
        gate = QualityGate.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            status=QualityGateStatus.PENDING,
            is_blocking=True,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(
            f"/produccion/calidad/{gate.pk}/revisar/",
            {
                "status": QualityGateStatus.FAILED,
                "evidence_reference": "QA-EVID-FAIL-001",
                "notes": "Torque fuera de rango.",
            },
        )

        self.assertEqual(response.status_code, 302)
        gate.refresh_from_db()
        unit.refresh_from_db()
        self.assertEqual(gate.status, QualityGateStatus.FAILED)
        self.assertEqual(unit.status, UnitStatus.QUALITY_HOLD)

    def test_rework_control_sends_unit_to_reinspection(self):
        self.grant_permissions("change_reworkorder", "view_reworkorder")
        unit = self.create_unit("SER-0353", UnitStatus.REWORK)
        station, _route, step = self.create_station_route_step()
        rework = ReworkOrder.objects.create(
            unit=unit,
            station_detected=station,
            route_step_detected=step,
            defect_code="DEF-RW-001",
            description="Correccion de ajuste mecanico.",
            status=ReworkStatus.IN_PROGRESS,
            opened_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(
            f"/produccion/retrabajos/{rework.pk}/gestionar/",
            {
                "action": "send_qa",
                "closure_evidence_reference": "RW-EVID-001",
                "notes": "Correccion completada y lista para reinspeccion.",
            },
        )

        self.assertEqual(response.status_code, 302)
        rework.refresh_from_db()
        unit.refresh_from_db()
        self.assertEqual(rework.status, ReworkStatus.QA_REVIEW)
        self.assertEqual(rework.closure_evidence_reference, "RW-EVID-001")
        self.assertIsNotNone(rework.reinspection_gate)
        self.assertEqual(rework.reinspection_gate.status, QualityGateStatus.PENDING)
        self.assertEqual(unit.status, UnitStatus.QUALITY_HOLD)
        self.assertTrue(
            UnitStationEvent.objects.filter(
                unit=unit,
                station=station,
                route_step=step,
                event_type=StationEventType.REWORK_IN,
            ).exists()
        )

    def test_reinspection_pass_closes_rework(self):
        self.grant_permissions("change_qualitygate", "view_qualitygate")
        unit = self.create_unit("SER-0354", UnitStatus.QUALITY_HOLD)
        station, _route, step = self.create_station_route_step()
        gate = QualityGate.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            status=QualityGateStatus.PENDING,
            is_blocking=True,
            created_by=self.user,
            updated_by=self.user,
        )
        rework = ReworkOrder.objects.create(
            unit=unit,
            station_detected=station,
            route_step_detected=step,
            defect_code="DEF-RW-002",
            description="Reinspeccion pendiente.",
            status=ReworkStatus.QA_REVIEW,
            closure_evidence_reference="RW-EVID-002",
            reinspection_gate=gate,
            opened_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(
            f"/produccion/calidad/{gate.pk}/revisar/",
            {
                "status": QualityGateStatus.PASSED,
                "evidence_reference": "QA-RW-OK-001",
                "notes": "Retrabajo conforme.",
            },
        )

        self.assertEqual(response.status_code, 302)
        rework.refresh_from_db()
        unit.refresh_from_db()
        self.assertEqual(rework.status, ReworkStatus.CLOSED)
        self.assertEqual(rework.closed_by, self.user)
        self.assertIsNotNone(rework.closed_at)
        self.assertEqual(unit.status, UnitStatus.COMPLETED)

    def test_reinspection_fail_returns_rework_to_process(self):
        self.grant_permissions("change_qualitygate", "view_qualitygate")
        unit = self.create_unit("SER-0355", UnitStatus.QUALITY_HOLD)
        station, _route, step = self.create_station_route_step()
        gate = QualityGate.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            status=QualityGateStatus.PENDING,
            is_blocking=True,
            created_by=self.user,
            updated_by=self.user,
        )
        rework = ReworkOrder.objects.create(
            unit=unit,
            station_detected=station,
            route_step_detected=step,
            defect_code="DEF-RW-003",
            description="Correccion requiere otra vuelta.",
            status=ReworkStatus.QA_REVIEW,
            closure_evidence_reference="RW-EVID-003",
            reinspection_gate=gate,
            opened_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(
            f"/produccion/calidad/{gate.pk}/revisar/",
            {
                "status": QualityGateStatus.FAILED,
                "evidence_reference": "QA-RW-NOK-001",
                "notes": "Aun fuera de tolerancia.",
            },
        )

        self.assertEqual(response.status_code, 302)
        rework.refresh_from_db()
        unit.refresh_from_db()
        self.assertEqual(rework.status, ReworkStatus.IN_PROGRESS)
        self.assertEqual(unit.status, UnitStatus.REWORK)

    def test_release_approval_marks_unit_as_released(self):
        self.grant_permissions("add_releaseapproval", "view_releaseapproval")
        unit = self.create_unit("SER-0352", UnitStatus.COMPLETED)

        response = self.client.post(
            "/produccion/liberacion/nueva/",
            {
                "unit": unit.pk,
                "decision": ReleaseDecision.APPROVED,
                "evidence_reference": "REL-EVID-001",
                "notes": "Expediente completo.",
            },
        )

        self.assertEqual(response.status_code, 302)
        unit.refresh_from_db()
        release = ReleaseApproval.objects.get(unit=unit)
        self.assertEqual(unit.status, UnitStatus.RELEASED)
        self.assertEqual(release.decided_by, self.user)
        self.assertIsNotNone(release.decided_at)

    def test_station_console_registers_step_events_and_quality_hold(self):
        self.grant_permissions("add_unitstationevent")
        unit = self.create_unit("SER-0400")
        station, _route, step = self.create_station_route_step()

        response = self.client.post(
            "/produccion/estacion/",
            {
                "station": station.pk,
                "serial_number": unit.serial_number,
                "action": StationEventType.STARTED,
                "notes": "Inicio desde consola.",
            },
        )

        self.assertEqual(response.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.status, UnitStatus.IN_PROCESS)
        self.assertTrue(
            UnitStationEvent.objects.filter(
                unit=unit,
                station=station,
                route_step=step,
                event_type=StationEventType.STARTED,
            ).exists()
        )

        response = self.client.post(
            "/produccion/estacion/",
            {
                "station": station.pk,
                "serial_number": unit.serial_number,
                "action": StationEventType.COMPLETED,
                "notes": "Paso terminado.",
            },
        )

        self.assertEqual(response.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.status, UnitStatus.QUALITY_HOLD)
        self.assertTrue(
            QualityGate.objects.filter(
                unit=unit,
                station=station,
                route_step=step,
                status=QualityGateStatus.PENDING,
                is_blocking=True,
            ).exists()
        )

    def test_station_console_blocks_unauthorized_operator(self):
        self.grant_permissions("add_unitstationevent")
        unit = self.create_unit("SER-0401")
        station, _route, _step = self.create_station_route_step()
        other_user = get_user_model().objects.create_user(username="authorized", password="StrongPass.2026")
        station.authorized_operators.add(other_user)

        response = self.client.post(
            "/produccion/estacion/",
            {
                "station": station.pk,
                "serial_number": unit.serial_number,
                "action": StationEventType.STARTED,
            },
        )

        self.assertEqual(response.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.status, UnitStatus.REGISTERED)
        self.assertFalse(UnitStationEvent.objects.filter(unit=unit, station=station).exists())

    def test_station_events_must_follow_the_route_sequence(self):
        unit = self.create_unit("SER-ROUTE-ORDER")
        first_station, route, first_step = self.create_station_route_step()
        second_station = AssemblyStation.objects.create(
            line=first_station.line,
            code="ST-02",
            name="Montaje final",
            sequence=2,
            created_by=self.user,
            updated_by=self.user,
        )
        AssemblyRouteStep.objects.create(
            route=route,
            station=second_station,
            sequence=2,
            name="Cierre final",
            created_by=self.user,
            updated_by=self.user,
        )

        with self.assertRaisesMessage(ValueError, "El paso actual de la unidad es #1"):
            record_station_event(
                actor=self.user,
                unit_serial_number=unit.serial_number,
                station_code=second_station.code,
                event_type=StationEventType.STARTED,
            )

        started, created = record_station_event(
            actor=self.user,
            unit_serial_number=unit.serial_number,
            station_code=first_station.code,
            event_type=StationEventType.STARTED,
        )
        self.assertTrue(created)
        self.assertEqual(started.route_step, first_step)

    def test_station_console_blocks_route_continuation_during_quality_hold(self):
        self.grant_permissions("add_unitstationevent")
        unit = self.create_unit("SER-QUALITY-HOLD")
        first_station, route, _first_step = self.create_station_route_step()
        second_station = AssemblyStation.objects.create(
            line=first_station.line,
            code="ST-02",
            name="Montaje final",
            sequence=2,
            created_by=self.user,
            updated_by=self.user,
        )
        AssemblyRouteStep.objects.create(
            route=route,
            station=second_station,
            sequence=2,
            name="Cierre final",
            created_by=self.user,
            updated_by=self.user,
        )

        self.client.post(
            "/produccion/estacion/",
            {
                "station": first_station.pk,
                "serial_number": unit.serial_number,
                "action": StationEventType.STARTED,
            },
        )
        self.client.post(
            "/produccion/estacion/",
            {
                "station": first_station.pk,
                "serial_number": unit.serial_number,
                "action": StationEventType.COMPLETED,
            },
        )

        response = self.client.post(
            "/produccion/estacion/",
            {
                "station": second_station.pk,
                "serial_number": unit.serial_number,
                "action": StationEventType.STARTED,
            },
            follow=True,
        )

        unit.refresh_from_db()
        self.assertEqual(unit.status, UnitStatus.QUALITY_HOLD)
        self.assertFalse(UnitStationEvent.objects.filter(unit=unit, station=second_station).exists())
        self.assertContains(response, "La unidad esta retenida por calidad")

    def test_equipment_api_processes_a_station_event_with_jwt(self):
        self.grant_permissions("add_equipmentinboundevent")
        unit = self.create_unit("SER-EQ-001")
        station, _route, step = self.create_station_route_step()
        equipment = EquipmentIntegration.objects.create(
            code="TORQUE-01",
            name="Atornilladora 01",
            created_by=self.user,
            updated_by=self.user,
        )
        station.equipment.add(equipment)
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")

        response = client.post(
            "/api/assembly/equipment-events/",
            {
                "external_id": "collector-001",
                "equipment_code": equipment.code,
                "unit_serial_number": unit.serial_number,
                "operator_username": self.user.username,
                "event_type": StationEventType.STARTED,
                "payload": {"result": "OK", "torque_nm": 120},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], EquipmentInboundEventStatus.PROCESSED)
        inbound_event = EquipmentInboundEvent.objects.get(external_id="collector-001")
        self.assertEqual(inbound_event.equipment, equipment)
        self.assertEqual(inbound_event.station, station)
        self.assertEqual(inbound_event.unit, unit)
        self.assertEqual(inbound_event.station_event.route_step, step)
        self.assertEqual(inbound_event.station_event.source, "EQUIPMENT")
        unit.refresh_from_db()
        self.assertEqual(unit.status, UnitStatus.IN_PROCESS)

    def test_equipment_api_is_idempotent_for_collector_retries(self):
        self.grant_permissions("add_equipmentinboundevent")
        unit = self.create_unit("SER-EQ-002")
        station, _route, _step = self.create_station_route_step()
        equipment = EquipmentIntegration.objects.create(
            code="SCANNER-01",
            name="Scanner 01",
            created_by=self.user,
            updated_by=self.user,
        )
        station.equipment.add(equipment)
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        payload = {
            "external_id": "collector-retry-001",
            "equipment_code": equipment.code,
            "unit_serial_number": unit.serial_number,
            "operator_username": self.user.username,
            "event_type": StationEventType.STARTED,
        }

        first = client.post("/api/assembly/equipment-events/", payload, format="json")
        second = client.post("/api/assembly/equipment-events/", payload, format="json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(UnitStationEvent.objects.filter(unit=unit, source="EQUIPMENT").count(), 1)

    def test_equipment_api_records_rejection_for_unavailable_equipment(self):
        self.grant_permissions("add_equipmentinboundevent")
        unit = self.create_unit("SER-EQ-003")
        station, _route, _step = self.create_station_route_step()
        equipment = EquipmentIntegration.objects.create(
            code="TEST-01",
            name="Banco de prueba 01",
            is_active=False,
            created_by=self.user,
            updated_by=self.user,
        )
        station.equipment.add(equipment)
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")

        response = client.post(
            "/api/assembly/equipment-events/",
            {
                "external_id": "collector-rejected-001",
                "equipment_code": equipment.code,
                "unit_serial_number": unit.serial_number,
                "operator_username": self.user.username,
                "event_type": StationEventType.STARTED,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 422)
        inbound_event = EquipmentInboundEvent.objects.get(external_id="collector-rejected-001")
        self.assertEqual(inbound_event.status, EquipmentInboundEventStatus.REJECTED)
        self.assertIn("no habilitado", inbound_event.result_detail)
        self.assertFalse(UnitStationEvent.objects.filter(unit=unit, source="EQUIPMENT").exists())

    def test_plant_dashboard_groups_station_state_and_andon_alerts(self):
        self.grant_permissions("view_productionqueueitem")
        station, route, step = self.create_station_route_step()
        plan = ProductionPlan.objects.create(
            code="PLAN-PANEL",
            version=self.version,
            line=station.line,
            planned_date=timezone.localdate(),
            shift="Turno A",
            target_quantity=1,
            status=ProductionPlanStatus.RELEASED,
            created_by=self.user,
            updated_by=self.user,
        )
        unit = self.create_unit("SER-PANEL-001", UnitStatus.IN_PROCESS)
        unit.production_plan = plan
        unit.save(update_fields=["production_plan", "updated_at"])
        ProductionQueueItem.objects.create(
            production_plan=plan,
            unit=unit,
            line=station.line,
            route=route,
            sequence=1,
            status=ProductionQueueStatus.HOLD,
            created_by=self.user,
            updated_by=self.user,
        )
        QualityGate.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            status=QualityGateStatus.PENDING,
            is_blocking=True,
            created_by=self.user,
            updated_by=self.user,
        )
        ReworkOrder.objects.create(
            unit=unit,
            station_detected=station,
            route_step_detected=step,
            defect_code="DEF-PANEL",
            description="Ajuste pendiente.",
            created_by=self.user,
            updated_by=self.user,
        )
        equipment = EquipmentIntegration.objects.create(
            code="PANEL-EQ-01",
            name="Equipo de panel",
            is_active=False,
            created_by=self.user,
            updated_by=self.user,
        )
        station.equipment.add(equipment)

        response = self.client.get("/produccion/", {"line": station.line_id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Panel de planta")
        self.assertContains(response, "Equipo no habilitado")
        self.assertContains(response, "SER-PANEL-001")
        self.assertContains(response, "PANEL-EQ-01")
        self.assertContains(response, 'hx-trigger="every 20s"', html=False)

    def test_plant_dashboard_status_fragment_filters_by_line(self):
        station, _route, _step = self.create_station_route_step()
        other_line = AssemblyLine.objects.create(
            code="LINE-2",
            name="Linea secundaria",
            created_by=self.user,
            updated_by=self.user,
        )
        AssemblyStation.objects.create(
            line=other_line,
            code="ST-02",
            name="Revision final",
            sequence=1,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get("/produccion/panel/estado/", {"line": station.line_id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LINE-1 - Linea principal")
        self.assertNotContains(response, "LINE-2 - Linea secundaria")
        self.assertContains(response, 'id="plant-dashboard"', html=False)

    def test_mes_api_reads_unit_and_current_step_with_jwt(self):
        unit = self.create_unit("SER-API-001")
        station, _route, _step = self.create_station_route_step()
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")

        detail = client.get(f"/api/assembly/v1/units/{unit.serial_number}/")
        current_step = client.get(f"/api/assembly/v1/units/{unit.serial_number}/current-step/")

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["product"]["code"], self.product.code)
        self.assertEqual(detail.data["current_step"]["station"]["code"], station.code)
        self.assertEqual(current_step.status_code, 200)
        self.assertEqual(current_step.data["current_step"]["name"], "Ingreso a linea")

    def test_mes_api_registers_station_event_idempotently_with_scope(self):
        self.grant_permissions("add_unitstationevent")
        unit = self.create_unit("SER-API-002")
        station, _route, _step = self.create_station_route_step()
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        payload = {
            "unit_serial_number": unit.serial_number,
            "station_code": station.code,
            "event_type": StationEventType.STARTED,
            "external_reference": "terminal-002",
        }

        first = client.post("/api/assembly/v1/station-events/", payload, format="json")
        second = client.post("/api/assembly/v1/station-events/", payload, format="json")

        self.assertEqual(first.status_code, 201)
        self.assertTrue(first.data["created"])
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.data["created"])
        self.assertEqual(UnitStationEvent.objects.filter(external_reference="terminal-002").count(), 1)

    def test_mes_api_installs_required_component(self):
        self.grant_permissions("add_installedcomponent")
        unit = self.create_unit("SER-API-003")
        _station, _route, step = self.create_station_route_step()
        requirement = RouteStepComponentRequirement.objects.create(
            route_step=step,
            part_code="API-PART-001",
            part_name="Componente API",
            traceability=ComponentTraceability.SERIAL,
            created_by=self.user,
            updated_by=self.user,
        )
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")

        response = client.post(
            "/api/assembly/v1/components/",
            {
                "unit_serial_number": unit.serial_number,
                "requirement_id": requirement.pk,
                "serial_number": "API-COMP-SER-001",
                "quantity": "1.0000",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["part_code"], requirement.part_code)
        self.assertTrue(InstalledComponent.objects.filter(unit=unit, requirement=requirement).exists())

    def test_mes_api_records_production_measurement(self):
        self.grant_permissions("add_productionmeasurement")
        unit = self.create_unit("SER-API-MEAS")
        _station, _route, step = self.create_station_route_step()
        parameter = RouteStepParameter.objects.create(
            route_step=step,
            code="API-TORQUE",
            name="Torque API",
            unit="Nm",
            min_value=Decimal("50.0000"),
            max_value=Decimal("60.0000"),
            origin=ProductiveParameterOrigin.API,
            created_by=self.user,
            updated_by=self.user,
        )
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")

        response = client.post(
            "/api/assembly/v1/measurements/",
            {
                "unit_serial_number": unit.serial_number,
                "parameter_id": parameter.pk,
                "value": "55.0000",
                "evidence_reference": "API-MEAS-001",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["result"], MeasurementResult.PASS)
        measurement = ProductionMeasurement.objects.get(unit=unit, parameter=parameter)
        self.assertEqual(measurement.station, step.station)
        self.assertEqual(measurement.code, parameter.code)

    def test_mes_api_reviews_quality_gate(self):
        self.grant_permissions("change_qualitygate")
        unit = self.create_unit("SER-API-004", UnitStatus.QUALITY_HOLD)
        station, _route, step = self.create_station_route_step()
        gate = QualityGate.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            status=QualityGateStatus.PENDING,
            is_blocking=True,
            created_by=self.user,
            updated_by=self.user,
        )
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")

        response = client.post(
            f"/api/assembly/v1/quality-gates/{gate.pk}/decision/",
            {"status": QualityGateStatus.PASSED, "evidence_reference": "API-QA-001"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        gate.refresh_from_db()
        self.assertEqual(gate.status, QualityGateStatus.PASSED)
        self.assertEqual(gate.inspected_by, self.user)

    def test_mes_api_exposes_integration_permissions(self):
        self.grant_permissions("add_unitstationevent", "add_installedcomponent")
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")

        response = client.get("/api/assembly/v1/integration/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["permissions"]["consult_units"])
        self.assertTrue(response.data["permissions"]["register_station_events"])
        self.assertTrue(response.data["permissions"]["install_components"])
        self.assertFalse(response.data["permissions"]["review_quality"])

    def test_production_metrics_calculate_cycle_takt_rework_and_productivity(self):
        self.grant_permissions("view_unitstationevent")
        station, route, step = self.create_station_route_step()
        station.takt_time_seconds = 60
        station.save(update_fields=["takt_time_seconds", "updated_at"])
        plan = ProductionPlan.objects.create(
            code="PLAN-METRICS",
            version=self.version,
            line=station.line,
            planned_date=timezone.localdate(),
            shift="Turno A",
            target_quantity=3,
            status=ProductionPlanStatus.RELEASED,
            created_by=self.user,
            updated_by=self.user,
        )
        first_unit = self.create_unit("SER-MET-001")
        second_unit = self.create_unit("SER-MET-002")
        base_time = timezone.now() - timedelta(minutes=5)
        for unit, started_at, completed_at in [
            (first_unit, base_time, base_time + timedelta(seconds=60)),
            (second_unit, base_time + timedelta(seconds=120), base_time + timedelta(seconds=180)),
        ]:
            UnitStationEvent.objects.create(
                unit=unit,
                station=station,
                route_step=step,
                event_type=StationEventType.STARTED,
                event_at=started_at,
                operator=self.user,
                created_by=self.user,
                updated_by=self.user,
            )
            UnitStationEvent.objects.create(
                unit=unit,
                station=station,
                route_step=step,
                event_type=StationEventType.COMPLETED,
                event_at=completed_at,
                operator=self.user,
                created_by=self.user,
                updated_by=self.user,
            )
        UnitStationEvent.objects.create(
            unit=second_unit,
            station=station,
            route_step=step,
            event_type=StationEventType.FAILED,
            event_at=base_time + timedelta(seconds=190),
            operator=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        ReworkOrder.objects.create(
            unit=second_unit,
            station_detected=station,
            route_step_detected=step,
            defect_code="MET-DEF-01",
            description="Falla para indicador.",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(
            "/produccion/indicadores/",
            {"date_from": timezone.localdate().isoformat(), "date_to": timezone.localdate().isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Indicadores MES")
        self.assertContains(response, "1 min 00 s")
        self.assertContains(response, "2 min 00 s")
        self.assertContains(response, "MET-DEF-01")
        self.assertContains(response, ">2<", html=False)
        self.assertContains(response, ">3<", html=False)

    def test_line_balance_calculation_detects_bottleneck_and_capacity(self):
        station, route, step = self.create_station_route_step()
        station.line.takt_time_seconds = 900
        station.line.save(update_fields=["takt_time_seconds", "updated_at"])
        station.takt_time_seconds = 900
        station.save(update_fields=["takt_time_seconds", "updated_at"])
        step.expected_duration_seconds = 1200
        step.requires_quality_gate = False
        step.save(update_fields=["expected_duration_seconds", "requires_quality_gate", "updated_at"])
        support_station = AssemblyStation.objects.create(
            line=station.line,
            code="ST-02",
            name="Apoyo operativo",
            sequence=2,
            takt_time_seconds=900,
            created_by=self.user,
            updated_by=self.user,
        )
        AssemblyRouteStep.objects.create(
            route=route,
            station=support_station,
            sequence=2,
            name="Apoyo de linea",
            expected_duration_seconds=500,
            created_by=self.user,
            updated_by=self.user,
        )
        unit = self.create_unit("SER-BAL-001", UnitStatus.IN_PROCESS)
        started_at = timezone.now() - timedelta(minutes=30)
        UnitStationEvent.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            event_type=StationEventType.STARTED,
            event_at=started_at,
            operator=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        UnitStationEvent.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            event_type=StationEventType.COMPLETED,
            event_at=started_at + timedelta(seconds=1300),
            operator=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        study = LineBalanceStudy.objects.create(
            code="BAL-001",
            line=station.line,
            version=self.version,
            route=route,
            planned_units=6,
            shift_duration_seconds=3600,
            target_takt_seconds=900,
            actual_start_date=timezone.localdate(),
            actual_end_date=timezone.localdate(),
            created_by=self.user,
            updated_by=self.user,
        )

        snapshot = study.calculate(self.user)
        study.refresh_from_db()

        self.assertEqual(study.status, LineBalanceStatus.CALCULATED)
        self.assertEqual(snapshot["summary"]["bottleneck_station_code"], "ST-01")
        self.assertEqual(snapshot["summary"]["capacity_units_per_shift"], 3)
        first_station = next(row for row in snapshot["stations"] if row["station_code"] == "ST-01")
        self.assertEqual(first_station["status"], "BOTTLENECK")
        self.assertEqual(first_station["actual_cycle_seconds"], 1300)
        self.assertTrue(study.recommendations)
        self.assertTrue(
            OperationalAuditEvent.objects.filter(
                document_type="Balanceo de linea",
                document_code="BAL-001",
                action="UPDATE",
            ).exists()
        )

    def test_line_balance_detail_recalculates_from_screen(self):
        self.grant_permissions("view_linebalancestudy", "change_linebalancestudy")
        station, route, step = self.create_station_route_step()
        station.line.takt_time_seconds = 900
        station.line.save(update_fields=["takt_time_seconds", "updated_at"])
        step.expected_duration_seconds = 950
        step.save(update_fields=["expected_duration_seconds", "updated_at"])
        study = LineBalanceStudy.objects.create(
            code="BAL-UI-001",
            line=station.line,
            version=self.version,
            route=route,
            planned_units=4,
            shift_duration_seconds=3600,
            target_takt_seconds=900,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(f"/produccion/balanceo/{study.pk}/", {"action": "calculate"})

        self.assertEqual(response.status_code, 302)
        study.refresh_from_db()
        self.assertEqual(study.status, LineBalanceStatus.CALCULATED)
        self.assertEqual(study.snapshot["summary"]["bottleneck_station_code"], "ST-01")

    def test_andon_signal_can_be_acknowledged_and_resolved_from_screen(self):
        self.grant_permissions("view_andonsignal", "change_andonsignal")
        station, _route, _step = self.create_station_route_step()
        signal = AndonSignal.objects.create(
            code="ANDON-001",
            line=station.line,
            station=station,
            severity=AndonSeverity.CRITICAL,
            status=AndonStatus.OPEN,
            title="Material faltante",
            description="Falta kit en estacion.",
            opened_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )

        acknowledge = self.client.post(
            f"/produccion/andon/{signal.pk}/gestionar/",
            {"action": "acknowledge", "notes": "Supervisor avisado."},
        )
        signal.refresh_from_db()

        self.assertEqual(acknowledge.status_code, 302)
        self.assertEqual(signal.status, AndonStatus.ACKNOWLEDGED)
        self.assertEqual(signal.acknowledged_by, self.user)

        resolve = self.client.post(
            f"/produccion/andon/{signal.pk}/gestionar/",
            {"action": "resolve", "notes": "Kit entregado a estacion."},
        )
        signal.refresh_from_db()

        self.assertEqual(resolve.status_code, 302)
        self.assertEqual(signal.status, AndonStatus.RESOLVED)
        self.assertEqual(signal.resolved_by, self.user)
        self.assertTrue(
            OperationalAuditEvent.objects.filter(
                document_type="Andon",
                document_code="ANDON-001",
                action="STATUS_CHANGE",
                to_status=AndonStatus.RESOLVED,
            ).exists()
        )

    def test_downtime_can_be_closed_with_duration_and_audit(self):
        self.grant_permissions("view_productiondowntime", "change_productiondowntime")
        station, _route, _step = self.create_station_route_step()
        started_at = timezone.now() - timedelta(minutes=15)
        downtime = ProductionDowntime.objects.create(
            code="STOP-001",
            line=station.line,
            station=station,
            status=DowntimeStatus.OPEN,
            cause_category=DowntimeCauseCategory.EQUIPMENT,
            cause_code="EQ-STOP",
            cause_description="Equipo detenido.",
            started_at=started_at,
            opened_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        ended_at = timezone.now()

        response = self.client.post(
            f"/produccion/paros/{downtime.pk}/gestionar/",
            {
                "action": "close",
                "ended_at": ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                "evidence_reference": "STOP-EVID-001",
                "notes": "Equipo reiniciado.",
            },
        )
        downtime.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(downtime.status, DowntimeStatus.CLOSED)
        self.assertEqual(downtime.closed_by, self.user)
        self.assertGreaterEqual(downtime.duration_seconds, 14 * 60)
        self.assertTrue(
            OperationalAuditEvent.objects.filter(
                document_type="Paro de produccion",
                document_code="STOP-001",
                to_status=DowntimeStatus.CLOSED,
            ).exists()
        )

    def test_offline_event_sync_creates_station_event_with_offline_source(self):
        self.grant_permissions("view_stationofflineevent", "change_stationofflineevent", "add_unitstationevent")
        unit = self.create_unit("SER-OFF-001")
        station, _route, _step = self.create_station_route_step()
        offline_event = StationOfflineEvent.objects.create(
            external_id="OFF-001",
            station=station,
            unit_serial_number=unit.serial_number,
            operator_username=self.user.username,
            event_type=StationEventType.STARTED,
            captured_at=timezone.now() - timedelta(minutes=3),
            payload={"terminal": "tablet-01"},
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(f"/produccion/offline/{offline_event.pk}/gestionar/", {"action": "sync"})
        offline_event.refresh_from_db()
        unit.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(offline_event.status, StationOfflineEventStatus.SYNCED)
        self.assertIsNotNone(offline_event.station_event)
        self.assertEqual(offline_event.station_event.source, StationEventSource.OFFLINE)
        self.assertEqual(unit.status, UnitStatus.IN_PROCESS)

    def test_mes_api_accepts_and_syncs_offline_station_event(self):
        self.grant_permissions("add_stationofflineevent", "add_unitstationevent")
        unit = self.create_unit("SER-OFF-API-001")
        station, _route, _step = self.create_station_route_step()
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")

        response = client.post(
            "/api/assembly/v1/offline-events/",
            {
                "external_id": "OFF-API-001",
                "station_code": station.code,
                "unit_serial_number": unit.serial_number,
                "operator_username": self.user.username,
                "event_type": StationEventType.STARTED,
                "payload": {"queued_locally": True},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], StationOfflineEventStatus.SYNCED)
        self.assertTrue(
            UnitStationEvent.objects.filter(
                unit=unit,
                station=station,
                external_reference="OFF-API-001",
                source=StationEventSource.OFFLINE,
            ).exists()
        )

    def test_model_mix_generates_related_production_plans(self):
        station, _route, _step = self.create_station_route_step()
        other_version = ProductVersion.objects.create(
            product=self.product,
            code="SPORT",
            name="Sport",
            created_by=self.user,
            updated_by=self.user,
        )
        mix_plan = ModelMixPlan.objects.create(
            code="MIX-001",
            line=station.line,
            planned_date=timezone.localdate(),
            shift="Turno A",
            created_by=self.user,
            updated_by=self.user,
        )
        ModelMixPlanItem.objects.create(
            mix_plan=mix_plan,
            version=self.version,
            planned_quantity=2,
            sequence_bias=1,
            priority=ProductionPlanPriority.HIGH,
            created_by=self.user,
            updated_by=self.user,
        )
        ModelMixPlanItem.objects.create(
            mix_plan=mix_plan,
            version=other_version,
            planned_quantity=1,
            sequence_bias=2,
            created_by=self.user,
            updated_by=self.user,
        )

        mix_plan.activate(self.user)
        plans = mix_plan.generate_production_plans(self.user)
        mix_plan.refresh_from_db()

        self.assertEqual(mix_plan.status, ModelMixPlanStatus.ACTIVE)
        self.assertEqual(len(plans), 2)
        self.assertEqual(ProductionPlan.objects.filter(code__startswith="MIX-001").count(), 2)
        self.assertEqual(mix_plan.items.filter(production_plan__isnull=False).count(), 2)

    def test_external_material_kit_tracks_receipt_and_consumption(self):
        plan = self.create_production_plan("PLAN-KIT", target_quantity=2, status=ProductionPlanStatus.RELEASED)
        kit = ExternalMaterialKit.objects.create(
            code="KIT-001",
            external_system="B22",
            external_reference="B22-001",
            version=self.version,
            production_plan=plan,
            line=plan.line,
            expected_quantity=Decimal("2.0000"),
            received_quantity=Decimal("0.0000"),
            status=ExternalMaterialKitStatus.PLANNED,
            created_by=self.user,
            updated_by=self.user,
        )

        kit.receive(self.user)
        kit.refresh_from_db()
        self.assertEqual(kit.status, ExternalMaterialKitStatus.RECEIVED)
        self.assertEqual(kit.receipt_percent, 100)

        kit.consume(self.user)
        kit.refresh_from_db()
        self.assertEqual(kit.status, ExternalMaterialKitStatus.CONSUMED)
        self.assertTrue(
            OperationalAuditEvent.objects.filter(
                document_type="Kit externo",
                document_code="KIT-001",
                to_status=ExternalMaterialKitStatus.CONSUMED,
            ).exists()
        )

    def test_global_dashboard_is_home_not_production_redirect(self):
        station, _route, step = self.create_station_route_step()
        plan = ProductionPlan.objects.create(
            code="PLAN-HOME",
            version=self.version,
            line=station.line,
            planned_date=timezone.localdate(),
            shift="Turno A",
            target_quantity=1,
            status=ProductionPlanStatus.IN_EXECUTION,
            created_by=self.user,
            updated_by=self.user,
        )
        unit = self.create_unit("SER-HOME-001", UnitStatus.IN_PROCESS)
        unit.production_plan = plan
        unit.save(update_fields=["production_plan", "updated_at"])
        UnitStationEvent.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            event_type=StationEventType.COMPLETED,
            event_at=timezone.now(),
            operator=self.user,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard.html")
        self.assertContains(response, ">Inicio<", html=False)
        self.assertContains(response, "Pendientes de trabajo")
        self.assertContains(response, "Estado operativo")
        self.assertContains(response, "Tendencia 7 dias")
        self.assertContains(response, "Dispersion de planta")
        self.assertContains(response, "Distribucion de unidades")
        self.assertNotContains(response, 'href="/produccion/indicadores/"', html=False)
        self.assertNotContains(response, 'href="/configuracion/"', html=False)

        self.grant_permissions("view_unitstationevent")
        metrics_response = self.client.get("/")
        self.assertEqual(metrics_response.status_code, 200)
        self.assertContains(metrics_response, 'href="/produccion/indicadores/" class="home-action"', html=False)

        membership = TenantMembership.objects.get(tenant=self.tenant, user=self.user)
        membership.is_admin = True
        membership.save(update_fields=["is_admin"])
        admin_response = self.client.get("/")
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, 'href="/configuracion/" class="home-action"', html=False)

    def test_genealogy_search_finds_units_by_component_lot(self):
        self.grant_permissions("view_installedcomponent")
        unit = self.create_unit("SER-GEN-001")
        station, _route, step = self.create_station_route_step()
        InstalledComponent.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            part_code="HARNESS-001",
            part_name="Arnes principal",
            lot_number="LOT-GEN-001",
            quantity=1,
            installed_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get("/produccion/genealogia/", {"q": "LOT-GEN"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SER-GEN-001")
        self.assertContains(response, "HARNESS-001")

    def test_production_module_screens_render_with_permissions(self):
        unit = self.create_unit("SER-0500")
        station, _route, step = self.create_station_route_step()
        plant = Plant.objects.create(
            code="PLANT-SMOKE",
            name="Planta smoke",
            created_by=self.user,
            updated_by=self.user,
        )
        area = PlantArea.objects.create(
            plant=plant,
            code="ASM-SMOKE",
            name="Area smoke",
            created_by=self.user,
            updated_by=self.user,
        )
        station.line.area = area
        station.line.save(update_fields=["area", "updated_at"])
        production_order = ProductionOrder.objects.create(
            code="OP-SMOKE",
            product=self.product,
            version=self.version,
            plant=plant,
            target_quantity=2,
            status=ProductionOrderStatus.RELEASED,
            created_by=self.user,
            updated_by=self.user,
        )
        plan = ProductionPlan.objects.create(
            code="PLAN-SMOKE",
            production_order=production_order,
            version=self.version,
            line=station.line,
            planned_date=timezone.localdate(),
            shift="Turno A",
            target_quantity=2,
            status=ProductionPlanStatus.RELEASED,
            created_by=self.user,
            updated_by=self.user,
        )
        parameter = RouteStepParameter.objects.create(
            route_step=step,
            code="PARAM-SMOKE",
            name="Parametro smoke",
            unit="Nm",
            min_value=Decimal("1.0000"),
            max_value=Decimal("5.0000"),
            origin=ProductiveParameterOrigin.MANUAL,
            created_by=self.user,
            updated_by=self.user,
        )
        ProductionMeasurement.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            parameter=parameter,
            code=parameter.code,
            name=parameter.name,
            value=Decimal("3.0000"),
            measured_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        unit.production_order = production_order
        unit.production_plan = plan
        unit.save(update_fields=["production_order", "production_plan", "updated_at"])
        queue_item = plan.create_queue_items(self.user)[0]
        gate = QualityGate.objects.create(
            unit=unit,
            station=station,
            route_step=step,
            status=QualityGateStatus.PENDING,
            created_by=self.user,
            updated_by=self.user,
        )
        rework = ReworkOrder.objects.create(
            unit=unit,
            station_detected=station,
            route_step_detected=step,
            defect_code="DEF-SMOKE",
            description="Retrabajo para validar pantalla.",
            opened_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        balance_study = LineBalanceStudy.objects.create(
            code="BAL-SMOKE",
            line=station.line,
            version=self.version,
            route=queue_item.route,
            planned_units=2,
            shift_duration_seconds=3600,
            target_takt_seconds=900,
            created_by=self.user,
            updated_by=self.user,
        )
        andon_signal = AndonSignal.objects.create(
            code="ANDON-SMOKE",
            line=station.line,
            station=station,
            unit=unit,
            production_plan=plan,
            severity=AndonSeverity.WARNING,
            status=AndonStatus.OPEN,
            title="Alerta de humo",
            description="Alerta para validar pantalla MES avanzado.",
            opened_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        downtime = ProductionDowntime.objects.create(
            code="STOP-SMOKE",
            line=station.line,
            station=station,
            unit=unit,
            production_plan=plan,
            andon_signal=andon_signal,
            status=DowntimeStatus.OPEN,
            cause_category=DowntimeCauseCategory.EQUIPMENT,
            cause_code="EQ-SMOKE",
            cause_description="Paro para validar pantalla.",
            started_at=timezone.now() - timedelta(minutes=10),
            opened_by=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        offline_event = StationOfflineEvent.objects.create(
            external_id="OFF-SMOKE",
            station=station,
            unit_serial_number=unit.serial_number,
            operator_username=self.user.username,
            event_type=StationEventType.STARTED,
            captured_at=timezone.now() - timedelta(minutes=5),
            payload={"terminal": "smoke"},
            created_by=self.user,
            updated_by=self.user,
        )
        mix_plan = ModelMixPlan.objects.create(
            code="MIX-SMOKE",
            line=station.line,
            planned_date=timezone.localdate(),
            shift="Turno A",
            status=ModelMixPlanStatus.ACTIVE,
            created_by=self.user,
            updated_by=self.user,
        )
        ModelMixPlanItem.objects.create(
            mix_plan=mix_plan,
            version=self.version,
            planned_quantity=2,
            sequence_bias=1,
            production_plan=plan,
            created_by=self.user,
            updated_by=self.user,
        )
        ExternalMaterialKit.objects.create(
            code="KIT-SMOKE",
            external_system="B22",
            external_reference="B22-SMOKE",
            version=self.version,
            production_plan=plan,
            line=station.line,
            expected_quantity=2,
            received_quantity=1,
            status=ExternalMaterialKitStatus.RECEIVED,
            created_by=self.user,
            updated_by=self.user,
        )
        self.grant_permissions(
            "view_assembledproduct",
            "view_plant",
            "add_plant",
            "change_plant",
            "view_plantarea",
            "add_plantarea",
            "change_plantarea",
            "view_productionorder",
            "add_productionorder",
            "change_productionorder",
            "view_productionplan",
            "add_productionplan",
            "change_productionplan",
            "view_productionqueueitem",
            "add_productionqueueitem",
            "change_productionqueueitem",
            "view_linebalancestudy",
            "add_linebalancestudy",
            "change_linebalancestudy",
            "view_productversion",
            "view_assemblyline",
            "view_assemblystation",
            "view_assemblyroute",
            "view_assemblyroutestep",
            "view_routestepcomponentrequirement",
            "view_routestepparameter",
            "add_routestepparameter",
            "change_routestepparameter",
            "add_unitstationevent",
            "view_unitstationevent",
            "view_productionmeasurement",
            "add_productionmeasurement",
            "change_productionmeasurement",
            "view_installedcomponent",
            "view_qualitygate",
            "change_qualitygate",
            "view_reworkorder",
            "change_reworkorder",
            "view_releaseapproval",
            "view_equipmentintegration",
            "view_andonsignal",
            "add_andonsignal",
            "change_andonsignal",
            "view_productiondowntime",
            "add_productiondowntime",
            "change_productiondowntime",
            "view_stationofflineevent",
            "add_stationofflineevent",
            "change_stationofflineevent",
            "view_modelmixplan",
            "add_modelmixplan",
            "change_modelmixplan",
            "view_modelmixplanitem",
            "add_modelmixplanitem",
            "change_modelmixplanitem",
            "view_externalmaterialkit",
            "add_externalmaterialkit",
            "change_externalmaterialkit",
        )
        for url in [
            "/produccion/",
            "/produccion/avanzado/",
            "/produccion/estacion/",
            f"/produccion/unidades/{unit.pk}/",
            "/produccion/ordenes/",
            "/produccion/ordenes/nueva/",
            f"/produccion/ordenes/{production_order.pk}/",
            f"/produccion/ordenes/{production_order.pk}/editar/",
            "/produccion/planes/",
            f"/produccion/planes/{plan.pk}/gestionar/",
            "/produccion/secuencia/",
            "/produccion/secuencia/estaciones/",
            f"/produccion/secuencia/{queue_item.pk}/gestionar/",
            "/produccion/balanceo/",
            f"/produccion/balanceo/{balance_study.pk}/",
            "/produccion/productos/",
            "/produccion/versiones/",
            "/produccion/plantas/",
            "/produccion/plantas/nueva/",
            f"/produccion/plantas/{plant.pk}/editar/",
            "/produccion/areas/",
            "/produccion/areas/nueva/",
            f"/produccion/areas/{area.pk}/editar/",
            "/produccion/lineas/",
            "/produccion/estaciones/",
            "/produccion/rutas/",
            "/produccion/pasos/",
            "/produccion/parametros/",
            "/produccion/parametros/nuevo/",
            f"/produccion/parametros/{parameter.pk}/editar/",
            "/produccion/requerimientos/",
            "/produccion/eventos/",
            "/produccion/mediciones/",
            "/produccion/mediciones/nueva/",
            f"/produccion/mediciones/{unit.measurements.first().pk}/editar/",
            "/produccion/indicadores/",
            "/produccion/componentes/",
            "/produccion/genealogia/",
            "/produccion/calidad/",
            f"/produccion/calidad/{gate.pk}/revisar/",
            "/produccion/retrabajos/",
            f"/produccion/retrabajos/{rework.pk}/gestionar/",
            "/produccion/liberacion/",
            "/produccion/equipos/",
            "/produccion/andon/",
            "/produccion/andon/nueva/",
            f"/produccion/andon/{andon_signal.pk}/gestionar/",
            f"/produccion/andon/{andon_signal.pk}/editar/",
            "/produccion/paros/",
            "/produccion/paros/nuevo/",
            f"/produccion/paros/{downtime.pk}/gestionar/",
            f"/produccion/paros/{downtime.pk}/editar/",
            "/produccion/offline/",
            "/produccion/offline/nuevo/",
            f"/produccion/offline/{offline_event.pk}/gestionar/",
            "/produccion/mix/",
            "/produccion/mix/nuevo/",
            f"/produccion/mix/{mix_plan.pk}/",
            f"/produccion/mix/{mix_plan.pk}/editar/",
            f"/produccion/mix-items/nuevo/?mix_plan={mix_plan.pk}",
            "/produccion/kits/",
            "/produccion/kits/nuevo/",
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_mes_phase_zero_navigation_separates_operation_from_configuration(self):
        self.grant_permissions(
            "view_plant",
            "view_plantarea",
            "view_productionorder",
            "view_productversion",
            "view_assemblyline",
            "view_routestepparameter",
            "view_routestepcomponentrequirement",
            "add_unitstationevent",
            "view_unitstationevent",
            "view_productionmeasurement",
            "view_installedcomponent",
            "view_qualitygate",
            "view_reworkorder",
            "view_releaseapproval",
        )

        production = self.client.get("/produccion/")

        self.assertEqual(production.status_code, 200)

        # La barra agrupa por etapa del flujo. Los numerales que antes daban el
        # orden ("1. OP", "5. Calidad") sobran cuando el grupo ya lo dice.
        for grupo in ("Ejecucion", "Trazabilidad", "Calidad", "Analisis"):
            self.assertContains(production, grupo, html=False)

        self.assertContains(production, ">Ordenes de produccion<", html=False)
        self.assertContains(production, ">Consola de estacion<", html=False)
        self.assertContains(production, ">Eventos de estacion<", html=False)
        self.assertContains(production, ">Componentes instalados<", html=False)
        self.assertContains(production, ">Genealogia<", html=False)
        self.assertContains(production, ">Mediciones<", html=False)
        self.assertContains(production, ">Controles de calidad<", html=False)
        self.assertContains(production, ">Retrabajos<", html=False)
        self.assertContains(production, ">Liberacion<", html=False)
        self.assertContains(production, ">Indicadores MES<", html=False)

        # Y ya no quedan numerales sueltos delante de las etiquetas.
        for numeral in ("1. OP", "4. Estacion", "5. Calidad", "7. Indicadores"):
            self.assertNotContains(production, numeral, html=False)
        self.assertNotContains(production, ">Versiones<", html=False)
        self.assertNotContains(production, ">Lineas<", html=False)
        self.assertNotContains(production, ">Plantas<", html=False)
        self.assertNotContains(production, ">Parametros<", html=False)
        self.assertNotContains(production, ">Requerimientos<", html=False)

        versions = self.client.get("/produccion/versiones/")

        self.assertEqual(versions.status_code, 200)
        self.assertContains(versions, ">Versiones<", html=False)
        self.assertContains(versions, ">Plantas<", html=False)
        self.assertContains(versions, ">Areas<", html=False)
        self.assertContains(versions, ">Parametros<", html=False)
        self.assertContains(versions, ">Requerimientos<", html=False)
        self.assertNotContains(versions, ">Empresa<", html=False)
        self.assertNotContains(versions, ">Sistema<", html=False)
