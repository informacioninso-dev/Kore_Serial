from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_tenants.utils import schema_context

from assembly.models import AssemblyStation, Plant, StationEventType
from core.models import EquipmentIntegration
from edge.models import (
    EdgeDevice,
    EdgeDeviceType,
    EdgeGateway,
    EdgeGatewayStatus,
    EdgeRuleAction,
    EdgeSignalRule,
)
from edge.services import register_heartbeat
from tenants.models import Client


class Command(BaseCommand):
    help = "Carga un gateway Edge de demostracion con dispositivos y reglas."

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
        self.stdout.write(self.style.SUCCESS(f"Populate Edge listo en schema {tenant.schema_name}."))

    def _populate(self, admin):
        audit = {"created_by": admin, "updated_by": admin}

        gateway, _ = EdgeGateway.objects.get_or_create(
            code="GW-LINEA-1",
            defaults={
                "name": "Collector linea 1",
                "plant": Plant.objects.order_by("code").first(),
                "host": "10.10.20.15",
                "agent_version": "1.0.0",
                "heartbeat_interval_seconds": 60,
                **audit,
            },
        )

        stations = list(AssemblyStation.objects.filter(is_active=True).order_by("sequence")[:2])
        equipments = list(EquipmentIntegration.objects.filter(is_active=True).order_by("code")[:2])

        scanner = self._device(
            gateway,
            code="DEV-SCAN-01",
            name="Lector de VIN estacion 1",
            device_type=EdgeDeviceType.SCANNER,
            station=stations[0] if stations else None,
            equipment=equipments[0] if equipments else None,
            audit=audit,
        )
        torque = self._device(
            gateway,
            code="DEV-TORQ-01",
            name="Torquimetro estacion 2",
            device_type=EdgeDeviceType.TORQUE_TOOL,
            station=stations[1] if len(stations) > 1 else None,
            equipment=equipments[1] if len(equipments) > 1 else None,
            audit=audit,
        )

        EdgeSignalRule.objects.get_or_create(
            code="RULE-SCAN-START",
            defaults={
                "name": "Escaneo de unidad inicia estacion",
                "signal_key": "scan.unit",
                "device": scanner,
                "action": EdgeRuleAction.STATION_EVENT,
                "station_event_type": StationEventType.STARTED,
                "priority": 10,
                **audit,
            },
        )
        EdgeSignalRule.objects.get_or_create(
            code="RULE-TORQUE",
            defaults={
                "name": "Torque final como medicion",
                "signal_key": "torque.final",
                "device": torque,
                "action": EdgeRuleAction.MEASUREMENT,
                "measurement_code": "TORQUE-FINAL",
                "measurement_name": "Torque final",
                "unit_of_measure": "Nm",
                "min_value": Decimal("40"),
                "max_value": Decimal("45"),
                "priority": 10,
                **audit,
            },
        )
        EdgeSignalRule.objects.get_or_create(
            code="RULE-RUIDO",
            defaults={
                "name": "Descarta telemetria de relleno",
                "signal_key": "agent.tick",
                "action": EdgeRuleAction.IGNORE,
                "priority": 900,
                **audit,
            },
        )

        register_heartbeat(
            gateway=gateway,
            actor=admin,
            agent_version="1.0.0",
            queue_depth=0,
            buffered_count=0,
            latency_ms=35,
            status=EdgeGatewayStatus.ONLINE,
            detail="Latido de demostracion.",
            reported_at=timezone.now(),
        )

    def _device(self, gateway, *, code, name, device_type, station, equipment, audit):
        device, _ = EdgeDevice.objects.get_or_create(
            code=code,
            defaults={
                "gateway": gateway,
                "name": name,
                "device_type": device_type,
                "station": station,
                "equipment": equipment,
                **audit,
            },
        )
        return device
