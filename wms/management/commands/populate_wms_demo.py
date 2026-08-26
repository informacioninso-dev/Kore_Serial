from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context

from core.models import Location, Unit, UnitCategory, Warehouse, WarehouseType
from tenants.models import Client
from wms.models import InboundReceipt, InboundReceiptLine, InventoryMovement, InventoryState, Material, MaterialCategory, MaterialTraceability
from wms.services import change_inventory_state, receive_receipt_line, transfer_inventory


class Command(BaseCommand):
    help = "Carga datos WMS idempotentes para un tenant demo."

    def add_arguments(self, parser):
        parser.add_argument("--schema", default="demo", help="Schema tenant destino.")

    def handle(self, *args, **options):
        tenant = Client.objects.filter(schema_name=options["schema"]).first()
        if tenant is None:
            raise CommandError(f"Tenant no encontrado: {options['schema']}")
        admin = get_user_model().objects.filter(username="admin").first()
        if admin is None:
            raise CommandError("No existe el usuario admin. Ejecuta primero populate_kore_serial.")
        with schema_context(tenant.schema_name):
            self._populate(admin)
        self.stdout.write(self.style.SUCCESS(f"Populate WMS listo en schema {tenant.schema_name}."))

    def _populate(self, admin):
        unit, _ = Unit.objects.get_or_create(
            code="un",
            defaults={"name": "Unidad", "category": UnitCategory.COUNT, "factor_to_base": Decimal("1"), "created_by": admin, "updated_by": admin},
        )
        warehouse, _ = Warehouse.objects.get_or_create(
            code="BOD-CKD",
            defaults={"name": "Bodega CKD", "type": WarehouseType.RAW, "is_default_for_raw": True, "created_by": admin, "updated_by": admin},
        )
        receiving, _ = Location.objects.get_or_create(
            warehouse=warehouse,
            code="REC-01",
            defaults={"name": "Recepcion CKD", "created_by": admin, "updated_by": admin},
        )
        storage, _ = Location.objects.get_or_create(
            warehouse=warehouse,
            code="ALM-01",
            defaults={"name": "Almacen CKD", "created_by": admin, "updated_by": admin},
        )
        category, _ = MaterialCategory.objects.get_or_create(
            code="CKD",
            defaults={"name": "Componentes CKD", "created_by": admin, "updated_by": admin},
        )
        frame, _ = Material.objects.get_or_create(
            code="CKD-FRAME-01",
            defaults={
                "name": "Bastidor CKD",
                "category": category,
                "base_unit": unit,
                "traceability": MaterialTraceability.LOT,
                "created_by": admin,
                "updated_by": admin,
            },
        )
        harness, _ = Material.objects.get_or_create(
            code="CKD-HARNESS-01",
            defaults={
                "name": "Arnes electrico CKD",
                "category": category,
                "base_unit": unit,
                "traceability": MaterialTraceability.SERIAL,
                "created_by": admin,
                "updated_by": admin,
            },
        )
        receipt, _ = InboundReceipt.objects.get_or_create(
            code="REC-CKD-DEMO-001",
            defaults={
                "supplier_name": "Proveedor CKD Demo",
                "container_number": "CONT-DEMO-001",
                "asn_reference": "ASN-DEMO-001",
                "destination_location": receiving,
                "created_by": admin,
                "updated_by": admin,
            },
        )
        frame_line, _ = InboundReceiptLine.objects.get_or_create(
            receipt=receipt,
            material=frame,
            defaults={"expected_quantity": Decimal("4"), "lot_number": "LOT-FRAME-DEMO", "created_by": admin, "updated_by": admin},
        )
        harness_line, _ = InboundReceiptLine.objects.get_or_create(
            receipt=receipt,
            material=harness,
            defaults={"expected_quantity": Decimal("2"), "created_by": admin, "updated_by": admin},
        )
        if not InventoryMovement.objects.filter(receipt_line=frame_line).exists():
            receive_receipt_line(actor=admin, receipt_line=frame_line, quantity=Decimal("4"), lot_number="LOT-FRAME-DEMO")
        if not InventoryMovement.objects.filter(receipt_line=harness_line).exists():
            receive_receipt_line(actor=admin, receipt_line=harness_line, quantity=Decimal("2"), serial_numbers=["HARNESS-DEMO-001", "HARNESS-DEMO-002"])
        frame_balance = frame.balances.filter(location=receiving, state=InventoryState.QUARANTINE).first()
        if frame_balance and not InventoryMovement.objects.filter(material=frame, movement_type="TRANSFER").exists():
            change_inventory_state(
                actor=admin,
                material=frame,
                quantity=frame_balance.quantity,
                location=receiving,
                source_state=InventoryState.QUARANTINE,
                destination_state=InventoryState.AVAILABLE,
                lot=frame_balance.lot,
                reason="Liberacion demo de calidad",
            )
            transfer_inventory(
                actor=admin,
                material=frame,
                quantity=frame_balance.quantity,
                source_location=receiving,
                destination_location=storage,
                state=InventoryState.AVAILABLE,
                lot=frame_balance.lot,
                reason="Ubicacion demo inicial",
            )
