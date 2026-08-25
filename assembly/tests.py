from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from core.models import EquipmentIntegration, OperationalAuditEvent
from tenants.models import TenantMembership

from .models import (
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    ComponentTraceability,
    EquipmentInboundEvent,
    EquipmentInboundEventStatus,
    InstalledComponent,
    ProductVersion,
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
    SerializedUnit,
    StationEventType,
    UnitStationEvent,
    UnitStatus,
)


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

    def test_production_module_screens_render_with_permissions(self):
        unit = self.create_unit("SER-0500")
        station, _route, step = self.create_station_route_step()
        plan = ProductionPlan.objects.create(
            code="PLAN-SMOKE",
            version=self.version,
            line=station.line,
            planned_date=timezone.localdate(),
            shift="Turno A",
            target_quantity=2,
            status=ProductionPlanStatus.RELEASED,
            created_by=self.user,
            updated_by=self.user,
        )
        unit.production_plan = plan
        unit.save(update_fields=["production_plan", "updated_at"])
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
        self.grant_permissions(
            "view_assembledproduct",
            "view_productionplan",
            "add_productionplan",
            "change_productionplan",
            "view_productionqueueitem",
            "add_productionqueueitem",
            "change_productionqueueitem",
            "view_productversion",
            "view_assemblyline",
            "view_assemblystation",
            "view_assemblyroute",
            "view_assemblyroutestep",
            "view_routestepcomponentrequirement",
            "add_unitstationevent",
            "view_unitstationevent",
            "view_installedcomponent",
            "view_qualitygate",
            "change_qualitygate",
            "view_reworkorder",
            "change_reworkorder",
            "view_releaseapproval",
            "view_equipmentintegration",
        )
        for url in [
            "/produccion/",
            "/produccion/estacion/",
            f"/produccion/unidades/{unit.pk}/",
            "/produccion/planes/",
            f"/produccion/planes/{plan.pk}/gestionar/",
            "/produccion/secuencia/",
            "/produccion/secuencia/estaciones/",
            f"/produccion/secuencia/{queue_item.pk}/gestionar/",
            "/produccion/productos/",
            "/produccion/versiones/",
            "/produccion/lineas/",
            "/produccion/estaciones/",
            "/produccion/rutas/",
            "/produccion/pasos/",
            "/produccion/requerimientos/",
            "/produccion/eventos/",
            "/produccion/componentes/",
            "/produccion/calidad/",
            f"/produccion/calidad/{gate.pk}/revisar/",
            "/produccion/retrabajos/",
            f"/produccion/retrabajos/{rework.pk}/gestionar/",
            "/produccion/liberacion/",
            "/produccion/equipos/",
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_mes_phase_zero_navigation_separates_operation_from_configuration(self):
        self.grant_permissions(
            "view_productversion",
            "view_assemblyline",
            "view_routestepcomponentrequirement",
            "add_unitstationevent",
            "view_unitstationevent",
            "view_installedcomponent",
            "view_qualitygate",
            "view_reworkorder",
            "view_releaseapproval",
        )

        production = self.client.get("/produccion/")

        self.assertEqual(production.status_code, 200)
        self.assertContains(production, ">Estacion<", html=False)
        self.assertContains(production, ">Eventos<", html=False)
        self.assertContains(production, ">Componentes<", html=False)
        self.assertContains(production, ">Calidad<", html=False)
        self.assertContains(production, ">Retrabajos<", html=False)
        self.assertContains(production, ">Liberacion<", html=False)
        self.assertNotContains(production, ">Versiones<", html=False)
        self.assertNotContains(production, ">Lineas<", html=False)
        self.assertNotContains(production, ">Requerimientos<", html=False)

        versions = self.client.get("/produccion/versiones/")

        self.assertEqual(versions.status_code, 200)
        self.assertContains(versions, ">Versiones<", html=False)
        self.assertContains(versions, ">Requerimientos<", html=False)
        self.assertNotContains(versions, ">Empresa<", html=False)
        self.assertNotContains(versions, ">Sistema<", html=False)
