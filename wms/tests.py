from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import Client
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from core.models import Location, OperationalAuditEvent, Unit, UnitCategory, Warehouse, WarehouseType
from tenants.models import TenantMembership

from assembly.models import (
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    ComponentTraceability,
    ProductVersion,
    RouteStepComponentRequirement,
    SerializedUnit,
    StationEventType,
)
from assembly.services import record_station_event

from .models import (
    InboundReceipt,
    InboundReceiptLine,
    InventoryBalance,
    InventoryMovement,
    InventoryState,
    Material,
    MaterialLot,
    MaterialSerial,
    MaterialTraceability,
    AssemblyKit,
    AssemblyKitLine,
    AssemblyKitStatus,
    KanbanSignalStatus,
    LocationOperationalType,
    PickMissionStatus,
    PickTask,
    PokaYokeAttempt,
    PokaYokeAttemptResult,
    ReplenishmentRule,
    AssemblyMaterialConsumption,
    WmsLocationProfile,
)
from .services import (
    adjust_inventory,
    change_inventory_state,
    complete_pick_task,
    create_kanban_pick_mission,
    create_kanban_signal,
    create_pick_mission,
    fulfill_kanban_signal,
    receive_receipt_line,
    release_kit,
    release_pick_mission,
    transfer_inventory,
    process_component_scan,
)


class WMSTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Empresa WMS de prueba"

    @staticmethod
    def get_test_tenant_domain():
        return "wms.test.com"

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        self.user = get_user_model().objects.create_user(username="wms-operator", password="StrongPass.2026")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        permissions = Permission.objects.filter(content_type__app_label="wms")
        self.user.user_permissions.add(*permissions)
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(
            code="un",
            name="Unidad",
            category=UnitCategory.COUNT,
            factor_to_base=Decimal("1"),
            created_by=self.user,
            updated_by=self.user,
        )
        self.warehouse = Warehouse.objects.create(
            code="CKD",
            name="Bodega CKD",
            type=WarehouseType.RAW,
            created_by=self.user,
            updated_by=self.user,
        )
        self.receiving_location = Location.objects.create(
            warehouse=self.warehouse,
            code="REC-01",
            name="Recepcion",
            created_by=self.user,
            updated_by=self.user,
        )
        self.storage_location = Location.objects.create(
            warehouse=self.warehouse,
            code="ALM-01",
            name="Almacenamiento",
            created_by=self.user,
            updated_by=self.user,
        )
        self.line_side_location = Location.objects.create(
            warehouse=self.warehouse,
            code="LIN-01",
            name="Line side",
            created_by=self.user,
            updated_by=self.user,
        )
        WmsLocationProfile.objects.create(
            location=self.line_side_location,
            operational_type=LocationOperationalType.LINE_SIDE,
            created_by=self.user,
            updated_by=self.user,
        )

    def create_material(self, code="CKD-001", traceability=MaterialTraceability.LOT):
        return Material.objects.create(
            code=code,
            name=f"Material {code}",
            base_unit=self.unit,
            traceability=traceability,
            created_by=self.user,
            updated_by=self.user,
        )

    def create_receipt_line(self, material, code="REC-CKD-001"):
        receipt = InboundReceipt.objects.create(
            code=code,
            supplier_name="Proveedor CKD",
            container_number="CONT-001",
            destination_location=self.receiving_location,
            created_by=self.user,
            updated_by=self.user,
        )
        return InboundReceiptLine.objects.create(
            receipt=receipt,
            material=material,
            expected_quantity=Decimal("10"),
            created_by=self.user,
            updated_by=self.user,
        )

    def create_serialized_unit(self, serial_number="UNIT-001"):
        product = AssembledProduct.objects.create(code="PRODUCT-001", name="Producto", created_by=self.user, updated_by=self.user)
        version = ProductVersion.objects.create(product=product, code="V1", name="Version 1", created_by=self.user, updated_by=self.user)
        return SerializedUnit.objects.create(version=version, serial_number=serial_number, created_by=self.user, updated_by=self.user)

    def create_scan_context(self, material_code="PART-001"):
        product = AssembledProduct.objects.create(code="SCAN-PRODUCT", name="Producto scan", created_by=self.user, updated_by=self.user)
        version = ProductVersion.objects.create(product=product, code="SCAN-V1", name="Version scan", created_by=self.user, updated_by=self.user)
        unit = SerializedUnit.objects.create(version=version, serial_number="SCAN-UNIT-001", created_by=self.user, updated_by=self.user)
        line = AssemblyLine.objects.create(code="SCAN-LINE", name="Linea scan", created_by=self.user, updated_by=self.user)
        station = AssemblyStation.objects.create(line=line, code="SCAN-ST", name="Estacion scan", sequence=1, created_by=self.user, updated_by=self.user)
        route = AssemblyRoute.objects.create(version=version, code="SCAN-ROUTE", name="Ruta scan", created_by=self.user, updated_by=self.user)
        step = AssemblyRouteStep.objects.create(route=route, station=station, sequence=1, name="Instalacion", requires_component_trace=True, created_by=self.user, updated_by=self.user)
        requirement = RouteStepComponentRequirement.objects.create(
            route_step=step,
            part_code=material_code,
            part_name="Parte de prueba",
            quantity_required=Decimal("1"),
            traceability=ComponentTraceability.LOT,
            created_by=self.user,
            updated_by=self.user,
        )
        record_station_event(
            actor=self.user,
            unit_serial_number=unit.serial_number,
            station_code=station.code,
            event_type=StationEventType.STARTED,
            external_reference="START-SCAN-001",
        )
        return unit, station, requirement

    def test_receipt_by_lot_creates_quarantine_balance_and_audit_event(self):
        material = self.create_material()
        line = self.create_receipt_line(material)

        movements = receive_receipt_line(
            actor=self.user,
            receipt_line=line,
            quantity=Decimal("4"),
            lot_number="LOT-CKD-001",
        )

        self.assertEqual(len(movements), 1)
        balance = InventoryBalance.objects.get(material=material, location=self.receiving_location, state=InventoryState.QUARANTINE)
        self.assertEqual(balance.quantity, Decimal("4"))
        self.assertEqual(balance.lot.number, "LOT-CKD-001")
        self.assertEqual(InventoryMovement.objects.filter(receipt_line=line).count(), 1)
        self.assertTrue(OperationalAuditEvent.objects.filter(module="WMS", document_type="Movimiento de inventario").exists())

    def test_transfer_and_state_change_keep_a_single_source_of_truth(self):
        material = self.create_material()
        line = self.create_receipt_line(material)
        receive_receipt_line(actor=self.user, receipt_line=line, quantity=Decimal("5"), lot_number="LOT-002")
        balance = InventoryBalance.objects.get(material=material, location=self.receiving_location)

        change_inventory_state(
            actor=self.user,
            material=material,
            quantity=Decimal("5"),
            location=self.receiving_location,
            source_state=InventoryState.QUARANTINE,
            destination_state=InventoryState.AVAILABLE,
            lot=balance.lot,
            reason="Calidad aprobada",
        )
        transfer_inventory(
            actor=self.user,
            material=material,
            quantity=Decimal("5"),
            source_location=self.receiving_location,
            destination_location=self.storage_location,
            state=InventoryState.AVAILABLE,
            lot=balance.lot,
            reason="Ubicacion inicial",
        )

        self.assertFalse(InventoryBalance.objects.filter(location=self.receiving_location).exists())
        stored = InventoryBalance.objects.get(material=material, location=self.storage_location, state=InventoryState.AVAILABLE)
        self.assertEqual(stored.quantity, Decimal("5"))
        self.assertEqual(InventoryMovement.objects.count(), 3)

    def test_transfer_rejects_quantity_above_available_balance(self):
        material = self.create_material()
        line = self.create_receipt_line(material)
        receive_receipt_line(actor=self.user, receipt_line=line, quantity=Decimal("1"), lot_number="LOT-003")
        balance = InventoryBalance.objects.get(material=material)

        with self.assertRaises(ValidationError):
            transfer_inventory(
                actor=self.user,
                material=material,
                quantity=Decimal("2"),
                source_location=self.receiving_location,
                destination_location=self.storage_location,
                state=InventoryState.QUARANTINE,
                lot=balance.lot,
                reason="Intento sin saldo",
            )

        self.assertEqual(InventoryBalance.objects.get(pk=balance.pk).quantity, Decimal("1"))

    def test_receipt_cannot_exceed_expected_quantity_or_mix_restricted_location(self):
        material = self.create_material()
        line = self.create_receipt_line(material)
        line.expected_quantity = Decimal("1")
        line.save(update_fields=["expected_quantity", "updated_at"])
        receive_receipt_line(actor=self.user, receipt_line=line, quantity=Decimal("1"), lot_number="LOT-004")

        with self.assertRaises(ValidationError):
            receive_receipt_line(actor=self.user, receipt_line=line, quantity=Decimal("1"), lot_number="LOT-004")

        WmsLocationProfile.objects.create(
            location=self.receiving_location,
            allows_mixed_materials=False,
            created_by=self.user,
            updated_by=self.user,
        )
        second_material = self.create_material(code="CKD-SECOND")
        second_line = self.create_receipt_line(second_material, code="REC-CKD-002")
        with self.assertRaises(ValidationError):
            receive_receipt_line(actor=self.user, receipt_line=second_line, quantity=Decimal("1"), lot_number="LOT-005")

    def test_serialized_material_requires_one_series_per_received_unit(self):
        material = self.create_material(code="SER-001", traceability=MaterialTraceability.SERIAL)
        line = self.create_receipt_line(material)

        with self.assertRaises(ValidationError):
            receive_receipt_line(actor=self.user, receipt_line=line, quantity=Decimal("2"), serial_numbers=["PART-001"])

        movements = receive_receipt_line(
            actor=self.user,
            receipt_line=line,
            quantity=Decimal("2"),
            serial_numbers=["PART-001", "PART-002"],
        )

        self.assertEqual(len(movements), 2)
        self.assertEqual(MaterialSerial.objects.filter(material=material).count(), 2)
        self.assertEqual(InventoryBalance.objects.filter(material=material, quantity=Decimal("1")).count(), 2)

    def test_receipt_api_registers_inventory_with_jwt(self):
        material = self.create_material()
        line = self.create_receipt_line(material)
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")

        response = client.post(
            "/api/wms/v1/receipts/receive/",
            {"receipt_line_id": line.pk, "quantity": "3.0000", "lot_number": "LOT-API-001"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["movement_ids"]), 1)
        self.assertTrue(InventoryBalance.objects.filter(material=material, quantity=Decimal("3")).exists())

    def test_wms_lists_preserve_filters_and_permission_boundary(self):
        material = self.create_material(code="FILTER-001", traceability=MaterialTraceability.NONE)
        response = self.client.get("/almacen/materiales/", {"q": material.code, "traceability": MaterialTraceability.NONE, "per_page": 50})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, material.code)
        self.assertContains(response, 'name="per_page" value="50"', html=False)

        anonymous = Client(HTTP_HOST=self.get_test_tenant_domain())
        denied = anonymous.get("/almacen/inventario/")
        self.assertEqual(denied.status_code, 302)

    def test_kit_picking_moves_material_to_line_without_consuming_it(self):
        material = self.create_material(code="KIT-001", traceability=MaterialTraceability.NONE)
        adjust_inventory(
            actor=self.user,
            material=material,
            quantity=Decimal("2"),
            location=self.storage_location,
            state=InventoryState.AVAILABLE,
            direction="IN",
            reason="Saldo inicial de prueba",
        )
        kit = AssemblyKit.objects.create(
            code="KIT-UNIT-001",
            serialized_unit=self.create_serialized_unit(),
            destination_location=self.line_side_location,
            created_by=self.user,
            updated_by=self.user,
        )
        line = AssemblyKitLine.objects.create(
            kit=kit,
            material=material,
            required_quantity=Decimal("2"),
            created_by=self.user,
            updated_by=self.user,
        )
        release_kit(actor=self.user, kit=kit)
        mission = create_pick_mission(
            actor=self.user,
            code="PICK-KIT-001",
            kit=kit,
            source_location=self.storage_location,
            destination_location=self.line_side_location,
        )
        task = PickTask.objects.create(
            mission=mission,
            kit_line=line,
            material=material,
            quantity=Decimal("2"),
            created_by=self.user,
            updated_by=self.user,
        )
        release_pick_mission(actor=self.user, mission=mission)
        complete_pick_task(actor=self.user, task=task)

        kit.refresh_from_db()
        mission.refresh_from_db()
        self.assertEqual(kit.status, AssemblyKitStatus.READY)
        self.assertEqual(mission.status, PickMissionStatus.COMPLETED)
        self.assertFalse(InventoryBalance.objects.filter(location=self.storage_location, material=material).exists())
        balance = InventoryBalance.objects.get(location=self.line_side_location, material=material, state=InventoryState.AVAILABLE)
        self.assertEqual(balance.quantity, Decimal("2"))
        self.assertEqual(InventoryBalance.objects.filter(material=material).aggregate(total=Sum("quantity"))["total"], Decimal("2"))

    def test_kanban_creates_replenishment_mission_and_keeps_inventory_traceable(self):
        material = self.create_material(code="KAN-001", traceability=MaterialTraceability.NONE)
        adjust_inventory(
            actor=self.user,
            material=material,
            quantity=Decimal("10"),
            location=self.storage_location,
            state=InventoryState.AVAILABLE,
            direction="IN",
            reason="Saldo para Kanban",
        )
        rule = ReplenishmentRule.objects.create(
            code="RULE-KAN-001",
            material=material,
            source_location=self.storage_location,
            destination_location=self.line_side_location,
            minimum_quantity=Decimal("3"),
            maximum_quantity=Decimal("6"),
            created_by=self.user,
            updated_by=self.user,
        )
        signal = create_kanban_signal(actor=self.user, rule=rule)
        self.assertEqual(signal.requested_quantity, Decimal("6"))
        mission = create_kanban_pick_mission(actor=self.user, signal=signal)
        task = mission.tasks.get()
        release_pick_mission(actor=self.user, mission=mission)
        complete_pick_task(actor=self.user, task=task)
        signal.refresh_from_db()
        fulfill_kanban_signal(actor=self.user, signal=signal)
        signal.refresh_from_db()

        self.assertEqual(signal.status, KanbanSignalStatus.FULFILLED)
        self.assertEqual(InventoryBalance.objects.get(location=self.line_side_location, material=material).quantity, Decimal("6"))
        self.assertEqual(InventoryBalance.objects.get(location=self.storage_location, material=material).quantity, Decimal("4"))

    def test_pick_task_api_confirms_available_transfer_with_jwt(self):
        material = self.create_material(code="API-PICK-001", traceability=MaterialTraceability.NONE)
        adjust_inventory(
            actor=self.user,
            material=material,
            quantity=Decimal("1"),
            location=self.storage_location,
            state=InventoryState.AVAILABLE,
            direction="IN",
            reason="Saldo API",
        )
        mission = create_pick_mission(
            actor=self.user,
            code="PICK-API-001",
            source_location=self.storage_location,
            destination_location=self.line_side_location,
        )
        task = PickTask.objects.create(mission=mission, material=material, quantity=Decimal("1"), created_by=self.user, updated_by=self.user)
        release_pick_mission(actor=self.user, mission=mission)
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        response = client.post("/api/wms/v1/picking/tasks/complete/", {"task_id": task.pk}, format="json")

        self.assertEqual(response.status_code, 201)
        task.refresh_from_db()
        self.assertEqual(task.status, "PICKED")
        self.assertTrue(InventoryBalance.objects.filter(location=self.line_side_location, material=material, quantity=Decimal("1")).exists())

    def test_component_scan_creates_as_built_consumption_and_inventory_movement(self):
        material = self.create_material(code="PART-001", traceability=MaterialTraceability.LOT)
        lot = MaterialLot.objects.create(material=material, number="LOT-SCAN-001", created_by=self.user, updated_by=self.user)
        adjust_inventory(
            actor=self.user,
            material=material,
            quantity=Decimal("1"),
            location=self.line_side_location,
            state=InventoryState.AVAILABLE,
            direction="IN",
            lot=lot,
            reason="Abastecimiento linea",
        )
        unit, station, requirement = self.create_scan_context(material.code)

        consumption, created = process_component_scan(
            actor=self.user,
            unit_serial_number=unit.serial_number,
            station_code=station.code,
            material_code=material.code,
            source_location_code=self.line_side_location.code,
            lot_number=lot.number,
            external_reference="SCAN-ACCEPT-001",
        )

        self.assertTrue(created)
        self.assertEqual(consumption.installed_component.requirement, requirement)
        self.assertEqual(consumption.inventory_movement.movement_type, "CONSUMPTION")
        self.assertFalse(InventoryBalance.objects.filter(material=material, location=self.line_side_location).exists())
        attempt = PokaYokeAttempt.objects.get(external_reference="SCAN-ACCEPT-001")
        self.assertEqual(attempt.result, PokaYokeAttemptResult.ACCEPTED)
        self.assertEqual(attempt.consumption, consumption)
        self.assertTrue(OperationalAuditEvent.objects.filter(module="WMS", action="CONSUME", document_code=consumption.event_code).exists())

    def test_component_scan_rejects_wrong_material_without_consuming_stock(self):
        expected = self.create_material(code="PART-EXPECTED", traceability=MaterialTraceability.LOT)
        wrong = self.create_material(code="PART-WRONG", traceability=MaterialTraceability.LOT)
        lot = MaterialLot.objects.create(material=wrong, number="LOT-WRONG", created_by=self.user, updated_by=self.user)
        adjust_inventory(
            actor=self.user,
            material=wrong,
            quantity=Decimal("1"),
            location=self.line_side_location,
            state=InventoryState.AVAILABLE,
            direction="IN",
            lot=lot,
            reason="Abastecimiento linea",
        )
        unit, station, _requirement = self.create_scan_context(expected.code)

        with self.assertRaises(ValidationError):
            process_component_scan(
                actor=self.user,
                unit_serial_number=unit.serial_number,
                station_code=station.code,
                material_code=wrong.code,
                source_location_code=self.line_side_location.code,
                lot_number=lot.number,
                external_reference="SCAN-REJECT-001",
            )

        self.assertEqual(InventoryBalance.objects.get(material=wrong, location=self.line_side_location).quantity, Decimal("1"))
        self.assertFalse(AssemblyMaterialConsumption.objects.exists())
        attempt = PokaYokeAttempt.objects.get(external_reference="SCAN-REJECT-001")
        self.assertEqual(attempt.result, PokaYokeAttemptResult.REJECTED)
        self.assertIn("no esta configurado", attempt.reason)

    def test_component_scan_api_is_idempotent_with_terminal_reference(self):
        self.user.user_permissions.add(Permission.objects.get(codename="add_installedcomponent", content_type__app_label="assembly"))
        material = self.create_material(code="PART-API", traceability=MaterialTraceability.LOT)
        lot = MaterialLot.objects.create(material=material, number="LOT-API", created_by=self.user, updated_by=self.user)
        adjust_inventory(actor=self.user, material=material, quantity=Decimal("1"), location=self.line_side_location, state=InventoryState.AVAILABLE, direction="IN", lot=lot, reason="Abastecimiento API")
        unit, station, _requirement = self.create_scan_context(material.code)
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        payload = {
            "unit_serial_number": unit.serial_number,
            "station_code": station.code,
            "material_code": material.code,
            "source_location_code": self.line_side_location.code,
            "lot_number": lot.number,
            "external_reference": "SCAN-API-001",
        }

        created = client.post("/api/wms/v1/line-installations/", payload, format="json")
        repeated = client.post("/api/wms/v1/line-installations/", payload, format="json")

        self.assertEqual(created.status_code, 201)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(AssemblyMaterialConsumption.objects.count(), 1)
        self.assertEqual(PokaYokeAttempt.objects.count(), 1)
