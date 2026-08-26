from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from core.models import Location, OperationalAuditEvent, Unit, UnitCategory, Warehouse, WarehouseType
from tenants.models import TenantMembership

from .models import (
    InboundReceipt,
    InboundReceiptLine,
    InventoryBalance,
    InventoryMovement,
    InventoryState,
    Material,
    MaterialSerial,
    MaterialTraceability,
    WmsLocationProfile,
)
from .services import change_inventory_state, receive_receipt_line, transfer_inventory


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
        response = self.client.get("/bodega/materiales/", {"q": material.code, "traceability": MaterialTraceability.NONE, "per_page": 50})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, material.code)
        self.assertContains(response, 'name="per_page" value="50"', html=False)

        anonymous = Client(HTTP_HOST=self.get_test_tenant_domain())
        denied = anonymous.get("/bodega/inventario/")
        self.assertEqual(denied.status_code, 302)
