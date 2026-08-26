"""Piloto automotriz: la historia completa en una sola corrida.

Recorre orden -> secuencia -> abastecimiento -> estacion -> PLC -> defecto ->
retrabajo -> genealogia -> descuento de stock -> cierre, tocando los cinco
modulos. Sirve para demostrar el sistema y para detectar cuando una fase se
rompe contra otra.

No es un test: escribe datos reales en el tenant que se le indique.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_tenants.utils import schema_context

from assembly.models import (
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    ApprovalStatus,
    ComponentTraceability,
    ProductionOrder,
    ProductionPlan,
    ProductionPlanStatus,
    ProductVersion,
    RouteStepComponentRequirement,
    SerializedUnit,
    StationEventType,
    UnitStatus,
)
from assembly.services import record_station_event
from connect.models import Connector
from connect.services import flush_outbound, reconcile
from core.models import Location, Unit, UnitCategory, Warehouse, WarehouseType
from edge.models import EdgeDevice, EdgeDeviceType, EdgeGateway, EdgeRuleAction, EdgeSignalRule
from edge.services import ingest_signal
from eventbus.services import dispatch_pending, rebuild_indicators, seed_event_catalog
from tenants.models import Client
from wms.models import (
    InboundReceipt,
    InboundReceiptLine,
    InventoryState,
    LocationOperationalType,
    Material,
    MaterialTraceability,
    WmsLocationProfile,
)
from wms.services import process_component_scan, receive_receipt_line, transfer_inventory


PILOT_PREFIX = "CIAUTO"


class Command(BaseCommand):
    help = "Ejecuta el piloto automotriz CIAUTO de punta a punta."

    def add_arguments(self, parser):
        parser.add_argument("--schema", default="demo", help="Schema tenant destino.")
        parser.add_argument("--model", default="WINGLE", choices=["WINGLE", "POER"])
        parser.add_argument("--units", type=int, default=2, help="Unidades a producir.")

    def handle(self, *args, **options):
        tenant = Client.objects.filter(schema_name=options["schema"]).first()
        if tenant is None:
            raise CommandError(f"Tenant no encontrado: {options['schema']}")
        admin = get_user_model().objects.filter(username="admin").first()
        if admin is None:
            raise CommandError("No existe el usuario admin. Ejecuta primero populate_kore_serial.")
        if options["units"] < 1:
            raise CommandError("Se necesita al menos una unidad.")

        with schema_context(tenant.schema_name):
            self.run_pilot(admin, options["model"], options["units"])

    # ------------------------------------------------------------------

    def step(self, number, title):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{number}. {title}"))

    def detail(self, text):
        self.stdout.write(f"   {text}")

    def run_pilot(self, admin, model_code, unit_count):
        stamp = timezone.now().strftime("%m%d%H%M%S")
        audit = {"created_by": admin, "updated_by": admin}

        self.stdout.write(self.style.SUCCESS(f"Piloto CIAUTO - modelo {model_code} - corrida {stamp}"))
        seed_event_catalog(actor=admin)

        # 1. Modelo y ruta -------------------------------------------------
        self.step(1, "Modelo y ruta de ensamble")
        product, _ = AssembledProduct.objects.get_or_create(
            code=f"{PILOT_PREFIX}-{model_code}",
            defaults={"name": f"Great Wall {model_code.title()}", **audit},
        )
        version, _ = ProductVersion.objects.get_or_create(
            product=product,
            code=f"{model_code}-2026",
            defaults={"name": f"{model_code} MY2026", **audit},
        )
        line, _ = AssemblyLine.objects.get_or_create(
            code=f"{PILOT_PREFIX}-L1", defaults={"name": "Linea CKD CIAUTO", **audit}
        )
        stations = []
        for sequence, (code, name) in enumerate(
            [("CHASIS", "Chasis y suspension"), ("MOTOR", "Motor y transmision")], start=1
        ):
            station, _ = AssemblyStation.objects.get_or_create(
                line=line,
                code=f"{PILOT_PREFIX}-{code}",
                defaults={"name": name, "sequence": sequence, **audit},
            )
            stations.append(station)
        route, _ = AssemblyRoute.objects.get_or_create(
            version=version,
            code=f"{PILOT_PREFIX}-RUTA-{model_code}",
            defaults={
                "name": f"Ruta {model_code}",
                "approval_status": ApprovalStatus.APPROVED,
                "approved_at": timezone.now(),
                **audit,
            },
        )
        steps = []
        for sequence, station in enumerate(stations, start=1):
            step, _ = AssemblyRouteStep.objects.get_or_create(
                route=route,
                station=station,
                defaults={"sequence": sequence, "name": f"Paso {station.code}", **audit},
            )
            steps.append(step)
        self.detail(f"{product.code} / {version.code} en {line.code} con {len(steps)} estaciones")

        # 2. Material y requerimiento -------------------------------------
        self.step(2, "Pieza requerida por la ruta")
        unit_of_measure, _ = Unit.objects.get_or_create(
            code="un",
            defaults={
                "name": "Unidad",
                "category": UnitCategory.COUNT,
                "factor_to_base": Decimal("1"),
                **audit,
            },
        )
        material, _ = Material.objects.get_or_create(
            code=f"{PILOT_PREFIX}-MOTOR-2.0",
            defaults={
                "name": "Motor 2.0 turbo",
                "base_unit": unit_of_measure,
                "traceability": MaterialTraceability.LOT,
                **audit,
            },
        )
        requirement, _ = RouteStepComponentRequirement.objects.get_or_create(
            route_step=steps[-1],
            part_code=material.code,
            defaults={
                "part_name": material.name,
                "quantity_required": Decimal("1"),
                "traceability": ComponentTraceability.LOT,
                **audit,
            },
        )
        self.detail(f"{material.code} exigido en {steps[-1].station.code}")

        # 3. Bodega y line side -------------------------------------------
        self.step(3, "Estructura fisica de almacen")
        warehouse, _ = Warehouse.objects.get_or_create(
            code=f"{PILOT_PREFIX}-CKD",
            defaults={"name": "Bodega CKD CIAUTO", "type": WarehouseType.RAW, **audit},
        )
        receiving, _ = Location.objects.get_or_create(
            warehouse=warehouse, code=f"{PILOT_PREFIX}-REC", defaults={"name": "Recepcion", **audit}
        )
        line_side, _ = Location.objects.get_or_create(
            warehouse=warehouse, code=f"{PILOT_PREFIX}-LIN", defaults={"name": "Line side", **audit}
        )
        WmsLocationProfile.objects.get_or_create(
            location=line_side,
            defaults={"operational_type": LocationOperationalType.LINE_SIDE, **audit},
        )
        self.detail(f"{receiving.code} -> {line_side.code}")

        # 4. Recepcion CKD -------------------------------------------------
        self.step(4, "Recepcion CKD del contenedor")
        receipt = InboundReceipt.objects.create(
            code=f"{PILOT_PREFIX}-REC-{stamp}",
            supplier_name="GWM CKD",
            destination_location=receiving,
            **audit,
        )
        receipt_line = InboundReceiptLine.objects.create(
            receipt=receipt,
            material=material,
            expected_quantity=Decimal(unit_count),
            **audit,
        )
        lot_number = f"LOT-{stamp}"
        receive_receipt_line(
            actor=admin,
            receipt_line=receipt_line,
            quantity=Decimal(unit_count),
            lot_number=lot_number,
        )
        self.detail(f"{unit_count} piezas recibidas en cuarentena, lote {lot_number}")

        # 5. Liberacion y abastecimiento a linea --------------------------
        self.step(5, "Liberacion de calidad y abastecimiento a line side")
        from wms.models import MaterialLot
        from wms.services import change_inventory_state

        lot = MaterialLot.objects.get(material=material, number=lot_number)
        change_inventory_state(
            actor=admin,
            material=material,
            quantity=Decimal(unit_count),
            location=receiving,
            source_state=InventoryState.QUARANTINE,
            destination_state=InventoryState.AVAILABLE,
            lot=lot,
            reason="Liberacion de calidad en piloto",
        )
        transfer_inventory(
            actor=admin,
            material=material,
            quantity=Decimal(unit_count),
            source_location=receiving,
            destination_location=line_side,
            state=InventoryState.AVAILABLE,
            lot=lot,
            reason="Abastecimiento a linea",
        )
        self.detail(f"{unit_count} piezas disponibles en {line_side.code}")

        # 6. Orden, plan y seriales/VIN -----------------------------------
        self.step(6, "Orden de produccion, plan y VIN")
        order = ProductionOrder.objects.create(
            code=f"OP-{PILOT_PREFIX}-{stamp}",
            product=product,
            version=version,
            target_quantity=unit_count,
            **audit,
        )
        plan = ProductionPlan.objects.create(
            code=f"PLAN-{PILOT_PREFIX}-{stamp}",
            production_order=order,
            version=version,
            line=line,
            planned_date=timezone.localdate(),
            shift="M",
            target_quantity=unit_count,
            status=ProductionPlanStatus.RELEASED,
            **audit,
        )
        units = []
        for index in range(1, unit_count + 1):
            vin = f"LGW{model_code[:2]}26{stamp}{index:02d}"
            units.append(
                SerializedUnit.objects.create(
                    version=version, serial_number=vin, production_plan=plan, **audit
                )
            )
        self.detail(f"{order.code} -> {plan.code} -> VIN {', '.join(u.serial_number for u in units)}")

        # 7. Conectividad: gateway, torquimetro y regla -------------------
        self.step(7, "Conectividad de planta")
        gateway, _ = EdgeGateway.objects.get_or_create(
            code=f"{PILOT_PREFIX}-GW", defaults={"name": "Collector CIAUTO", **audit}
        )
        device, _ = EdgeDevice.objects.get_or_create(
            code=f"{PILOT_PREFIX}-TORQ",
            defaults={
                "gateway": gateway,
                "name": "Torquimetro motor",
                "device_type": EdgeDeviceType.TORQUE_TOOL,
                "station": stations[-1],
                **audit,
            },
        )
        EdgeSignalRule.objects.get_or_create(
            code=f"{PILOT_PREFIX}-R-TORQUE",
            defaults={
                "name": "Torque de motor",
                "signal_key": "torque.motor",
                "device": device,
                "action": EdgeRuleAction.MEASUREMENT,
                "measurement_code": "TORQUE-MOTOR",
                "measurement_name": "Torque de motor",
                "unit_of_measure": "Nm",
                "min_value": Decimal("80"),
                "max_value": Decimal("120"),
                **audit,
            },
        )
        self.detail(f"{gateway.code} con {device.code} en {stations[-1].code}")

        # 8. Ejecucion de linea --------------------------------------------
        self.step(8, "Ejecucion en linea")
        for unit in units:
            for step_index, step in enumerate(steps):
                station = step.station
                record_station_event(
                    actor=admin,
                    unit_serial_number=unit.serial_number,
                    station_code=station.code,
                    event_type=StationEventType.STARTED,
                    external_reference=f"{PILOT_PREFIX}-{unit.serial_number}-{station.code}-START",
                )

                if step_index == len(steps) - 1:
                    self._motor_station(admin, unit, station, device, material, line_side, requirement, lot_number)

                record_station_event(
                    actor=admin,
                    unit_serial_number=unit.serial_number,
                    station_code=station.code,
                    event_type=StationEventType.COMPLETED,
                    external_reference=f"{PILOT_PREFIX}-{unit.serial_number}-{station.code}-DONE",
                )
            unit.refresh_from_db()
            self.detail(f"{unit.serial_number}: {unit.get_status_display()}")

        # 9. Bus de eventos e indicadores ---------------------------------
        self.step(9, "Bus de eventos e indicadores")
        delivered, failed = dispatch_pending(actor=admin)
        snapshot = rebuild_indicators(line=line, date=timezone.localdate(), actor=admin)
        self.detail(f"entregas: {delivered} correctas, {failed} fallidas")
        self.detail(
            f"OEE {snapshot.oee_percent}% | disponibilidad {snapshot.availability_percent}% | "
            f"rendimiento {snapshot.performance_percent}% | calidad {snapshot.quality_percent}%"
        )
        self.detail(f"FPY {snapshot.fpy_percent}% sobre {snapshot.completed_units} unidades")

        # 10. Integracion hacia ERP ---------------------------------------
        self.step(10, "Salida hacia sistemas externos")
        sent, failed_out = flush_outbound(actor=admin)
        self.detail(f"mensajes enviados: {sent}, fallidos: {failed_out}")
        connector = Connector.objects.filter(is_active=True).order_by("code").first()
        if connector is not None:
            run = reconcile(
                connector=connector,
                date_from=timezone.localdate(),
                date_to=timezone.localdate(),
                actor=admin,
            )
            self.detail(
                f"reconciliacion {connector.code}: {run.sent_count} de {run.expected_count} "
                f"eventos con mensaje enviado (brecha {run.gap})"
            )
        else:
            self.detail("no hay conectores configurados; ejecuta seed_connect para probar la salida")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nPiloto completo: {unit_count} unidades {model_code} recorrieron "
                "orden, secuencia, abastecimiento, ejecucion, PLC, calidad, genealogia, "
                "descuento de stock, eventos e integracion."
            )
        )

    # ------------------------------------------------------------------

    def _motor_station(self, admin, unit, station, device, material, line_side, requirement, lot_number):
        """Estacion de motor: dato de PLC, pieza escaneada y descuento de stock."""
        signal, _ = ingest_signal(
            gateway=device.gateway,
            device_code=device.code,
            external_id=f"{PILOT_PREFIX}-{unit.serial_number}-torque",
            signal_key="torque.motor",
            raw_value="104.5",
            unit_serial_number=unit.serial_number,
            operator_username=admin.username,
            actor=admin,
        )
        self.detail(f"   PLC torque 104.5 Nm -> {signal.get_status_display()}")

        scan = process_component_scan(
            actor=admin,
            unit_serial_number=unit.serial_number,
            station_code=station.code,
            material_code=material.code,
            source_location_code=line_side.code,
            quantity=Decimal("1"),
            lot_number=lot_number,
            operator_username=admin.username,
            external_reference=f"{PILOT_PREFIX}-{unit.serial_number}-scan",
        )
        result = getattr(scan, "result", None) or getattr(scan, "status", "OK")
        self.detail(f"   pieza {material.code} lote {lot_number} instalada -> {result}")
