from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone
from django_tenants.utils import schema_context

from tenants.models import Client, TenantMembership


ADMIN_PASSWORD = "admin12345"
DEMO_PASSWORD = "KoreSerial2026!"


class Command(BaseCommand):
    help = "Carga datos demo idempotentes para Kore Serial."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            default="",
            help="Schema tenant destino. Si se omite usa demo o el primer tenant disponible.",
        )
        parser.add_argument(
            "--reset-demo-passwords",
            action="store_true",
            help="Resetea claves de usuarios demo creados por este comando.",
        )

    def handle(self, *args, **options):
        tenant = self._tenant(options["schema"])
        admin, operator, quality = self._users(tenant, options["reset_demo_passwords"])

        with schema_context(tenant.schema_name):
            summary = self._populate_tenant(tenant, admin, operator, quality)

        self.stdout.write(self.style.SUCCESS(f"Populate Kore Serial listo en schema {tenant.schema_name}."))
        for label, count in summary.items():
            self.stdout.write(f"- {label}: {count}")
        self.stdout.write(f"- usuario demo: operador.linea / {DEMO_PASSWORD}")
        self.stdout.write(f"- usuario demo: calidad.linea / {DEMO_PASSWORD}")

    def _tenant(self, schema_name):
        if schema_name:
            tenant = Client.objects.filter(schema_name=schema_name).first()
            if tenant is None:
                raise CommandError(f"Tenant no encontrado: {schema_name}")
            return tenant

        tenant = Client.objects.filter(schema_name="demo").first()
        if tenant:
            return tenant

        tenant = Client.objects.exclude(schema_name="public").order_by("schema_name").first()
        if tenant is None:
            raise CommandError("No hay tenants. Crea uno antes de correr el populate.")
        return tenant

    def _users(self, tenant, reset_passwords):
        User = get_user_model()

        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@kore-serial.local",
                "first_name": "Admin",
                "last_name": "Kore Serial",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        admin.is_staff = True
        admin.is_superuser = True
        if created:
            admin.set_password(ADMIN_PASSWORD)
        admin.save()

        admin_group, _ = Group.objects.get_or_create(name="admin")
        admin.groups.add(admin_group)
        TenantMembership.objects.update_or_create(
            tenant=tenant,
            user=admin,
            defaults={"is_admin": True, "is_active": True},
        )

        operator = self._demo_user(
            tenant,
            username="operador.linea",
            first_name="Operador",
            last_name="Linea",
            group_name="operaciones",
            reset_passwords=reset_passwords,
        )
        quality = self._demo_user(
            tenant,
            username="calidad.linea",
            first_name="Calidad",
            last_name="Linea",
            group_name="calidad",
            reset_passwords=reset_passwords,
        )
        self._sync_demo_group_permissions()
        return admin, operator, quality

    def _demo_user(self, tenant, *, username, first_name, last_name, group_name, reset_passwords):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": f"{username}@kore-serial.local",
                "first_name": first_name,
                "last_name": last_name,
                "is_staff": False,
            },
        )
        if created or reset_passwords:
            user.set_password(DEMO_PASSWORD)
        user.first_name = first_name
        user.last_name = last_name
        user.is_active = True
        user.save()

        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
        TenantMembership.objects.update_or_create(
            tenant=tenant,
            user=user,
            defaults={"is_admin": False, "is_active": True},
        )
        return user

    def _sync_demo_group_permissions(self):
        operations_group, _ = Group.objects.get_or_create(name="operaciones")
        quality_group, _ = Group.objects.get_or_create(name="calidad")

        operations_permissions = Permission.objects.filter(
            Q(content_type__app_label="assembly", codename__startswith="view_")
            | Q(content_type__app_label="assembly", codename__startswith="add_")
            | Q(content_type__app_label="assembly", codename__startswith="change_")
            | Q(content_type__app_label="core", codename="view_equipmentintegration")
        )
        quality_permissions = Permission.objects.filter(
            Q(content_type__app_label="assembly", codename__startswith="view_")
            | Q(content_type__app_label="assembly", codename__in=[
                "change_qualitygate",
                "add_qualitygate",
                "change_reworkorder",
                "add_reworkorder",
                "change_releaseapproval",
                "add_releaseapproval",
            ])
            | Q(content_type__app_label="core", codename="view_equipmentintegration")
        )

        operations_group.permissions.set(operations_permissions)
        quality_group.permissions.set(quality_permissions)

    def _populate_tenant(self, tenant, admin, operator, quality):
        from assembly.models import (
            AssembledProduct,
            AssemblyLine,
            AssemblyRoute,
            AssemblyRouteStep,
            AssemblyStation,
            ComponentTraceability,
            InstalledComponent,
            ProductVersion,
            ProductionPlan,
            ProductionPlanPriority,
            ProductionPlanStatus,
            ProductionQueueItem,
            QualityGate,
            QualityGateStatus,
            ReleaseApproval,
            ReleaseDecision,
            ReworkOrder,
            ReworkStatus,
            RouteStepComponentRequirement,
            SerializedUnit,
            StationEventSource,
            StationEventType,
            UnitStationEvent,
            UnitStatus,
        )
        from core.models import (
            ApprovalStatus,
            CompanyConfig,
            ConnectionProtocol,
            EquipmentIntegration,
            EquipmentType,
            Location,
            OperatorQualification,
            Unit,
            UnitCategory,
            Warehouse,
            WarehouseType,
        )

        today = timezone.localdate()
        now = timezone.now()

        config = CompanyConfig.objects.first()
        if config is None:
            config = CompanyConfig.objects.create(
                ruc="0999999999001",
                legal_name=tenant.name,
                trade_name="Kore Serial Demo",
                address="Planta de ensamblaje demo",
                created_by=admin,
                updated_by=admin,
            )
        else:
            config.legal_name = config.legal_name or tenant.name
            config.trade_name = config.trade_name or "Kore Serial Demo"
            config.address = config.address or "Planta de ensamblaje demo"
            config.updated_by = admin
            config.save()

        units = [
            ("un", "Unidad", UnitCategory.COUNT, "1.0000"),
            ("set", "Set", UnitCategory.COUNT, "1.0000"),
            ("kg", "Kilogramo", UnitCategory.MASS, "1.0000"),
            ("m", "Metro", UnitCategory.LENGTH, "1.0000"),
        ]
        for code, name, category, factor in units:
            Unit.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "factor_to_base": Decimal(factor),
                    "is_active": True,
                    "updated_by": admin,
                },
            )

        warehouses = {}
        warehouse_specs = [
            ("BOD-MP", "Materia prima CKD", WarehouseType.RAW, {"is_default_for_raw": True}),
            ("BOD-WIP", "WIP linea de ensamblaje", WarehouseType.WIP, {}),
            ("BOD-PT", "Producto terminado liberado", WarehouseType.FINISHED, {"is_default_fg_released": True}),
            ("BOD-CUA", "Cuarentena calidad", WarehouseType.QUARANTINE, {"is_default_quarantine": True}),
        ]
        for code, name, warehouse_type, flags in warehouse_specs:
            warehouse, _ = Warehouse.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "type": warehouse_type,
                    "is_active": True,
                    "updated_by": admin,
                    **flags,
                },
            )
            warehouses[code] = warehouse

        location_specs = [
            ("BOD-MP", "MP-A1", "Rack CKD A1", "A", "1", "1", "120"),
            ("BOD-WIP", "LIN-01", "Buffer linea 01", "L1", "B", "1", "12"),
            ("BOD-PT", "PT-A1", "Patio producto terminado", "PT", "A", "1", "24"),
            ("BOD-CUA", "QA-HOLD", "Retencion calidad", "QA", "H", "1", "8"),
        ]
        locations = {}
        for warehouse_code, code, name, row, rack, level, capacity in location_specs:
            location, _ = Location.objects.update_or_create(
                warehouse=warehouses[warehouse_code],
                code=code,
                defaults={
                    "name": name,
                    "row": row,
                    "rack": rack,
                    "level": level,
                    "max_units": Decimal(capacity),
                    "is_active": True,
                    "updated_by": admin,
                },
            )
            locations[code] = location

        equipment_specs = [
            {
                "code": "SCN-LIN-01",
                "name": "Scanner linea 01",
                "equipment_type": EquipmentType.BARCODE_SCANNER,
                "connection_protocol": ConnectionProtocol.USB,
                "location": locations["LIN-01"],
                "warehouse": warehouses["BOD-WIP"],
                "manufacturer": "Zebra",
                "model": "DS2208",
            },
            {
                "code": "TRQ-CHS-01",
                "name": "Torquimetro chasis",
                "equipment_type": EquipmentType.MEASUREMENT,
                "connection_protocol": ConnectionProtocol.SERIAL,
                "serial_port": "COM3",
                "location": locations["LIN-01"],
                "warehouse": warehouses["BOD-WIP"],
                "manufacturer": "Atlas Copco",
                "model": "STwrench",
                "operating_parameters": "120-140 Nm",
                "is_quality_critical": True,
                "requires_calibration": True,
                "last_calibration_date": today - timedelta(days=20),
                "next_calibration_date": today + timedelta(days=160),
                "calibration_certificate_ref": "CAL-DEMO-TRQ-001",
                "requires_qualification": True,
            },
            {
                "code": "ZEBRA-PT-01",
                "name": "Impresora etiquetas PT",
                "equipment_type": EquipmentType.ZEBRA_PRINTER,
                "connection_protocol": ConnectionProtocol.TCP_RAW,
                "host": "192.168.10.45",
                "port": 9100,
                "location": locations["PT-A1"],
                "warehouse": warehouses["BOD-PT"],
                "manufacturer": "Zebra",
                "model": "ZT411",
            },
            {
                "code": "PLC-LIN-01",
                "name": "PLC linea 01",
                "equipment_type": EquipmentType.PRODUCTION_MACHINE,
                "connection_protocol": ConnectionProtocol.API,
                "host": "http://collector.local/plc/linea-01",
                "location": locations["LIN-01"],
                "warehouse": warehouses["BOD-WIP"],
                "manufacturer": "Siemens",
                "model": "S7-1200",
                "requires_maintenance": True,
                "last_maintenance_date": today - timedelta(days=30),
                "next_maintenance_date": today + timedelta(days=90),
            },
            {
                "code": "BANK-EOL-01",
                "name": "Banco prueba final EOL",
                "equipment_type": EquipmentType.MEASUREMENT,
                "connection_protocol": ConnectionProtocol.API,
                "host": "http://collector.local/eol/01",
                "location": locations["LIN-01"],
                "warehouse": warehouses["BOD-WIP"],
                "manufacturer": "Demo Instruments",
                "model": "EOL-100",
                "is_quality_critical": True,
                "requires_calibration": True,
                "last_calibration_date": today - timedelta(days=10),
                "next_calibration_date": today + timedelta(days=180),
                "calibration_certificate_ref": "CAL-DEMO-EOL-001",
                "requires_qualification": True,
            },
        ]
        equipment = {}
        for spec in equipment_specs:
            code = spec.pop("code")
            item, _ = EquipmentIntegration.objects.update_or_create(
                code=code,
                defaults={
                    **spec,
                    "is_active": True,
                    "updated_by": admin,
                },
            )
            equipment[code] = item

        for equipment_code in ["TRQ-CHS-01", "BANK-EOL-01"]:
            OperatorQualification.objects.update_or_create(
                operator=operator,
                equipment=equipment[equipment_code],
                defaults={
                    "qualified_on": today - timedelta(days=15),
                    "revalidate_on": today + timedelta(days=180),
                    "granted_by": quality,
                    "evidence_reference": f"CAP-DEMO-{equipment_code}",
                    "is_active": True,
                    "updated_by": admin,
                },
            )

        product, _ = AssembledProduct.objects.update_or_create(
            code="CKD-SUV",
            defaults={
                "name": "Vehiculo CKD SUV",
                "description": "Producto demo para ensamblaje serializado por estaciones.",
                "is_active": True,
                "updated_by": admin,
            },
        )
        version, _ = ProductVersion.objects.update_or_create(
            product=product,
            code="2026-AWD",
            defaults={
                "name": "Version AWD 2026",
                "description": "Configuracion demo con trazabilidad de componentes criticos.",
                "is_active": True,
                "updated_by": admin,
            },
        )
        line, _ = AssemblyLine.objects.update_or_create(
            code="LINEA-01",
            defaults={
                "name": "Linea principal CKD",
                "description": "Linea demo para secuencia de ensamblaje discreto.",
                "takt_time_seconds": 900,
                "is_active": True,
                "updated_by": admin,
            },
        )

        station_specs = [
            ("ST-010", "Recepcion kit CKD", 10, False, ["SCN-LIN-01"]),
            ("ST-020", "Chasis y torque", 20, True, ["TRQ-CHS-01", "SCN-LIN-01"]),
            ("ST-030", "Ensamble electrico", 30, False, ["PLC-LIN-01", "SCN-LIN-01"]),
            ("ST-040", "Control calidad EOL", 40, True, ["BANK-EOL-01"]),
            ("ST-050", "Liberacion y etiquetado", 50, True, ["ZEBRA-PT-01"]),
        ]
        stations = {}
        for code, name, sequence, requires_quality, equipment_codes in station_specs:
            station, _ = AssemblyStation.objects.update_or_create(
                line=line,
                code=code,
                defaults={
                    "name": name,
                    "sequence": sequence,
                    "takt_time_seconds": 900,
                    "requires_quality_gate": requires_quality,
                    "is_active": True,
                    "updated_by": admin,
                },
            )
            station.equipment.set([equipment[equipment_code] for equipment_code in equipment_codes])
            station.authorized_operators.set([operator, quality])
            stations[code] = station

        route, _ = AssemblyRoute.objects.update_or_create(
            version=version,
            code="RUTA-CKD",
            revision="A",
            defaults={
                "name": "Ruta principal CKD",
                "description": "Ruta demo desde recepcion hasta liberacion.",
                "approval_status": ApprovalStatus.APPROVED,
                "approved_by": admin,
                "approved_at": now,
                "is_active": True,
                "updated_by": admin,
            },
        )

        step_specs = [
            (10, "Validar kit CKD", "ST-010", 600, True, False, "Escanear kit y validar documentacion de recepcion."),
            (20, "Montaje de chasis", "ST-020", 1200, True, True, "Registrar torques criticos contra numero de serie."),
            (30, "Conexion electrica", "ST-030", 900, True, False, "Instalar arnes y registrar numero de lote."),
            (40, "Prueba final EOL", "ST-040", 1500, False, True, "Ejecutar banco de prueba y adjuntar evidencia."),
            (50, "Etiquetado y liberacion", "ST-050", 600, False, True, "Imprimir etiqueta, cerrar expediente y liberar."),
        ]
        steps = {}
        for sequence, name, station_code, duration, trace, quality_gate, instructions in step_specs:
            step, _ = AssemblyRouteStep.objects.update_or_create(
                route=route,
                sequence=sequence,
                defaults={
                    "station": stations[station_code],
                    "name": name,
                    "expected_duration_seconds": duration,
                    "requires_component_trace": trace,
                    "requires_quality_gate": quality_gate,
                    "instructions": instructions,
                    "is_active": True,
                    "updated_by": admin,
                },
            )
            steps[station_code] = step

        requirement_specs = [
            ("ST-010", "KIT-CKD", "Kit CKD principal", "1.0000", ComponentTraceability.LOT, False),
            ("ST-020", "CHS-FRAME", "Bastidor principal", "1.0000", ComponentTraceability.SERIAL, True),
            ("ST-030", "BATT-12V", "Bateria 12V", "1.0000", ComponentTraceability.SERIAL_AND_LOT, True),
        ]
        requirements = {}
        for station_code, part_code, part_name, quantity, traceability, critical in requirement_specs:
            requirement, _ = RouteStepComponentRequirement.objects.update_or_create(
                route_step=steps[station_code],
                part_code=part_code,
                defaults={
                    "part_name": part_name,
                    "quantity_required": Decimal(quantity),
                    "traceability": traceability,
                    "is_critical": critical,
                    "is_active": True,
                    "notes": "Requerimiento demo para expediente as-built.",
                    "created_by": admin,
                    "updated_by": admin,
                },
            )
            requirements[part_code] = requirement

        unit_specs = [
            ("KS-2026-0001", UnitStatus.RELEASED),
            ("KS-2026-0002", UnitStatus.COMPLETED),
            ("KS-2026-0003", UnitStatus.QUALITY_HOLD),
            ("KS-2026-0004", UnitStatus.REWORK),
            ("KS-2026-0005", UnitStatus.IN_PROCESS),
            ("KS-2026-0006", UnitStatus.REGISTERED),
        ]
        serial_units = {}
        for serial_number, status in unit_specs:
            unit, _ = SerializedUnit.objects.update_or_create(
                serial_number=serial_number,
                defaults={
                    "version": version,
                    "status": status,
                    "updated_by": admin,
                },
            )
            serial_units[serial_number] = unit

        demo_plan, _ = ProductionPlan.objects.update_or_create(
            code="PLAN-DEMO-2026-001",
            defaults={
                "version": version,
                "line": line,
                "planned_date": today,
                "shift": "Turno A",
                "target_quantity": 6,
                "status": ProductionPlanStatus.IN_EXECUTION,
                "priority": ProductionPlanPriority.HIGH,
                "planned_start_at": now.replace(hour=8, minute=0, second=0, microsecond=0),
                "planned_end_at": now.replace(hour=16, minute=0, second=0, microsecond=0),
                "notes": "Plan demo para validar planificacion de produccion MES.",
                "created_by": admin,
                "updated_by": admin,
            },
        )
        SerializedUnit.objects.filter(serial_number__in=serial_units.keys()).update(production_plan=demo_plan, updated_by=admin)
        demo_plan.create_queue_items(admin)

        self._populate_unit_flow(
            serial_units["KS-2026-0001"],
            ["ST-010", "ST-020", "ST-030", "ST-040", "ST-050"],
            stations,
            steps,
            operator,
            quality,
        )
        self._populate_unit_flow(
            serial_units["KS-2026-0002"],
            ["ST-010", "ST-020", "ST-030", "ST-040"],
            stations,
            steps,
            operator,
            quality,
        )
        self._populate_unit_flow(
            serial_units["KS-2026-0003"],
            ["ST-010", "ST-020", "ST-030", "ST-040"],
            stations,
            steps,
            operator,
            quality,
            quality_status=QualityGateStatus.PENDING,
        )
        self._populate_unit_flow(
            serial_units["KS-2026-0004"],
            ["ST-010", "ST-020"],
            stations,
            steps,
            operator,
            quality,
            quality_status=QualityGateStatus.FAILED,
        )
        self._populate_started_unit(serial_units["KS-2026-0005"], stations, steps, operator)

        for serial_number, unit in serial_units.items():
            if serial_number == "KS-2026-0006":
                continue
            self._components(unit, stations, steps, requirements, operator, serial_number)

        ReworkOrder.objects.get_or_create(
            unit=serial_units["KS-2026-0004"],
            defect_code="DEF-TORQUE-001",
            defaults={
                "station_detected": stations["ST-020"],
                "route_step_detected": steps["ST-020"],
                "description": "Torque fuera de rango en fijacion de chasis.",
                "status": ReworkStatus.IN_PROGRESS,
                "opened_by": quality,
                "opened_at": now - timedelta(hours=3),
                "created_by": quality,
                "updated_by": quality,
            },
        )
        self._event(
            serial_units["KS-2026-0004"],
            stations["ST-020"],
            steps["ST-020"],
            StationEventType.REWORK_OUT,
            now - timedelta(hours=3, minutes=5),
            quality,
            StationEventSource.MANUAL,
        )

        ReleaseApproval.objects.get_or_create(
            unit=serial_units["KS-2026-0001"],
            evidence_reference="REL-DEMO-KS-2026-0001",
            defaults={
                "decision": ReleaseDecision.APPROVED,
                "decided_by": quality,
                "decided_at": now - timedelta(hours=1),
                "notes": "Unidad liberada con expediente completo.",
                "created_by": quality,
                "updated_by": quality,
            },
        )

        return {
            "productos": AssembledProduct.objects.count(),
            "versiones": ProductVersion.objects.count(),
            "lineas": AssemblyLine.objects.count(),
            "estaciones": AssemblyStation.objects.count(),
            "rutas": AssemblyRoute.objects.count(),
            "pasos": AssemblyRouteStep.objects.count(),
            "requerimientos": RouteStepComponentRequirement.objects.count(),
            "planes": ProductionPlan.objects.count(),
            "secuencia": ProductionQueueItem.objects.count(),
            "unidades": SerializedUnit.objects.count(),
            "eventos": UnitStationEvent.objects.count(),
            "componentes": InstalledComponent.objects.count(),
            "calidad": QualityGate.objects.count(),
            "retrabajos": ReworkOrder.objects.count(),
            "liberaciones": ReleaseApproval.objects.count(),
            "equipos": EquipmentIntegration.objects.count(),
        }

    def _populate_unit_flow(
        self,
        unit,
        station_codes,
        stations,
        steps,
        operator,
        quality,
        quality_status=None,
    ):
        from assembly.models import QualityGate, QualityGateStatus, StationEventSource, StationEventType, UnitStationEvent

        base_time = timezone.now() - timedelta(days=1)
        for index, station_code in enumerate(station_codes):
            station = stations[station_code]
            step = steps[station_code]
            event_at = base_time + timedelta(minutes=index * 45)
            self._event(
                unit,
                station,
                step,
                StationEventType.ARRIVED,
                event_at,
                operator,
                StationEventSource.MANUAL,
            )
            self._event(
                unit,
                station,
                step,
                StationEventType.COMPLETED,
                event_at + timedelta(minutes=30),
                operator,
                StationEventSource.API if station_code in {"ST-020", "ST-040"} else StationEventSource.MANUAL,
            )
            if station.requires_quality_gate:
                status = quality_status if station_code == station_codes[-1] and quality_status else QualityGateStatus.PASSED
                inspected_at = None if status == QualityGateStatus.PENDING else event_at + timedelta(minutes=35)
                QualityGate.objects.get_or_create(
                    unit=unit,
                    station=station,
                    route_step=step,
                    evidence_reference=f"QA-DEMO-{unit.serial_number}-{station.code}",
                    defaults={
                        "status": status,
                        "is_blocking": True,
                        "inspected_by": quality if inspected_at else None,
                        "inspected_at": inspected_at,
                        "notes": "Control demo de estacion.",
                        "created_by": quality,
                        "updated_by": quality,
                    },
                )

    def _populate_started_unit(self, unit, stations, steps, operator):
        from assembly.models import StationEventSource, StationEventType

        event_at = timezone.now() - timedelta(hours=1)
        self._event(
            unit,
            stations["ST-010"],
            steps["ST-010"],
            StationEventType.COMPLETED,
            event_at - timedelta(minutes=45),
            operator,
            StationEventSource.MANUAL,
        )
        self._event(
            unit,
            stations["ST-020"],
            steps["ST-020"],
            StationEventType.STARTED,
            event_at,
            operator,
            StationEventSource.MANUAL,
        )

    def _event(self, unit, station, step, event_type, event_at, operator, source):
        from assembly.models import UnitStationEvent

        UnitStationEvent.objects.get_or_create(
            external_reference=f"EVT-DEMO-{unit.serial_number}-{station.code}-{event_type}",
            defaults={
                "unit": unit,
                "station": station,
                "route_step": step,
                "event_type": event_type,
                "event_at": event_at,
                "operator": operator,
                "source": source,
                "notes": "Evento generado por populate demo.",
                "metadata": {"demo": True},
                "created_by": operator,
                "updated_by": operator,
            },
        )

    def _components(self, unit, stations, steps, requirements, operator, serial_number):
        from assembly.models import InstalledComponent

        suffix = serial_number.rsplit("-", 1)[-1]
        component_specs = [
            ("KIT-CKD", "Kit CKD principal", "", f"LOT-CKD-2026-{suffix}", "ST-010", False),
            ("CHS-FRAME", "Bastidor principal", f"CHS-{suffix}", "", "ST-020", True),
            ("BATT-12V", "Bateria 12V", f"BAT-{suffix}", "LOT-BAT-2026-01", "ST-030", True),
        ]
        for part_code, part_name, component_serial, lot_number, station_code, critical in component_specs:
            InstalledComponent.objects.update_or_create(
                unit=unit,
                part_code=part_code,
                serial_number=component_serial,
                lot_number=lot_number,
                defaults={
                    "part_name": part_name,
                    "station": stations[station_code],
                    "route_step": steps[station_code],
                    "requirement": requirements.get(part_code),
                    "quantity": Decimal("1.0000"),
                    "installed_by": operator,
                    "installed_at": timezone.now() - timedelta(hours=4),
                    "is_critical": critical,
                    "notes": "Componente demo con trazabilidad.",
                    "created_by": operator,
                    "updated_by": operator,
                },
            )
