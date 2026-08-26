from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from assembly.models import (
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    EquipmentInboundEventStatus,
    ProductionMeasurement,
    ProductVersion,
    SerializedUnit,
    StationEventType,
    UnitStationEvent,
)
from core.models import EquipmentIntegration, EquipmentType
from tenants.models import TenantMembership

from .models import (
    EdgeCommand,
    EdgeCommandStatus,
    EdgeCommandType,
    EdgeDevice,
    EdgeDeviceType,
    EdgeGateway,
    EdgeGatewayStatus,
    EdgeRuleAction,
    EdgeSignal,
    EdgeSignalRule,
    EdgeSignalStatus,
)
from .services import (
    ack_command,
    claim_commands,
    expire_commands,
    ingest_signal,
    queue_command,
    register_heartbeat,
    retry_signal,
)


class EdgeTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Empresa Edge de prueba"

    @staticmethod
    def get_test_tenant_domain():
        return "edge.test.com"

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        self.user = get_user_model().objects.create_user(
            username="edge-operator", password="StrongPass.2026"
        )
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="edge"))
        self.client.force_login(self.user)

        self.gateway = EdgeGateway.objects.create(
            code="GW-01",
            name="Collector linea 1",
            heartbeat_interval_seconds=60,
            degraded_after_missed=2,
            offline_after_missed=5,
            created_by=self.user,
            updated_by=self.user,
        )

    # ---------- fixtures ----------

    def build_station_context(self):
        """Unidad con ruta activa, estacion y equipo enlazado al dispositivo."""
        product = AssembledProduct.objects.create(
            code="EDGE-P1", name="Producto edge", created_by=self.user, updated_by=self.user
        )
        version = ProductVersion.objects.create(
            product=product, code="V1", name="Version 1", created_by=self.user, updated_by=self.user
        )
        unit = SerializedUnit.objects.create(
            version=version, serial_number="EDGE-UNIT-1", created_by=self.user, updated_by=self.user
        )
        line = AssemblyLine.objects.create(
            code="EDGE-L1", name="Linea edge", created_by=self.user, updated_by=self.user
        )
        station = AssemblyStation.objects.create(
            line=line, code="EDGE-ST1", name="Estacion edge", sequence=1,
            created_by=self.user, updated_by=self.user,
        )
        route = AssemblyRoute.objects.create(
            version=version, code="EDGE-R1", name="Ruta edge", created_by=self.user, updated_by=self.user
        )
        AssemblyRouteStep.objects.create(
            route=route, station=station, sequence=1, name="Paso edge",
            created_by=self.user, updated_by=self.user,
        )
        equipment = EquipmentIntegration.objects.create(
            code="TORQ-01",
            name="Torquimetro estacion 1",
            equipment_type=EquipmentType.MEASUREMENT,
            created_by=self.user,
            updated_by=self.user,
        )
        station.equipment.add(equipment)
        device = EdgeDevice.objects.create(
            gateway=self.gateway,
            code="DEV-TORQ-01",
            name="Torquimetro",
            device_type=EdgeDeviceType.TORQUE_TOOL,
            equipment=equipment,
            station=station,
            created_by=self.user,
            updated_by=self.user,
        )
        return unit, station, device

    def make_rule(self, device=None, **kwargs):
        defaults = {
            "code": "R-INICIO",
            "name": "Inicio por lector",
            "signal_key": "scan.unit",
            "action": EdgeRuleAction.STATION_EVENT,
            "station_event_type": StationEventType.STARTED,
            "device": device,
            "created_by": self.user,
            "updated_by": self.user,
        }
        defaults.update(kwargs)
        return EdgeSignalRule.objects.create(**defaults)

    # ---------- salud del gateway ----------

    def test_gateway_health_is_derived_from_last_heartbeat(self):
        self.assertEqual(self.gateway.health_status, EdgeGatewayStatus.OFFLINE)

        register_heartbeat(gateway=self.gateway, actor=self.user, buffered_count=3, agent_version="1.2.0")
        self.gateway.refresh_from_db()
        self.assertEqual(self.gateway.health_status, EdgeGatewayStatus.ONLINE)
        self.assertEqual(self.gateway.buffered_signal_count, 3)
        self.assertEqual(self.gateway.agent_version, "1.2.0")

        self.gateway.last_seen_at = timezone.now() - timedelta(seconds=180)
        self.assertEqual(self.gateway.health_status, EdgeGatewayStatus.DEGRADED)

        self.gateway.last_seen_at = timezone.now() - timedelta(seconds=600)
        self.assertEqual(self.gateway.health_status, EdgeGatewayStatus.OFFLINE)

        self.gateway.is_active = False
        self.assertEqual(self.gateway.health_status, EdgeGatewayStatus.DISABLED)

    # ---------- ingesta e idempotencia ----------

    def test_buffer_replay_does_not_duplicate_signals(self):
        _, _, device = self.build_station_context()
        payload = {
            "gateway": self.gateway,
            "device_code": device.code,
            "external_id": "SIG-0001",
            "signal_key": "torque.final",
            "raw_value": "42.5",
            "actor": self.user,
        }
        first, created_first = ingest_signal(**payload)
        second, created_second = ingest_signal(**dict(payload, from_buffer=True))

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(EdgeSignal.objects.filter(external_id="SIG-0001").count(), 1)

    def test_signal_from_unknown_device_is_rejected(self):
        with self.assertRaises(ValueError):
            ingest_signal(
                gateway=self.gateway,
                device_code="NO-EXISTE",
                external_id="SIG-0002",
                signal_key="scan.unit",
                actor=self.user,
            )

    # ---------- normalizacion ----------

    def test_signal_without_rule_stays_pending(self):
        _, _, device = self.build_station_context()
        signal, _ = ingest_signal(
            gateway=self.gateway,
            device_code=device.code,
            external_id="SIG-0003",
            signal_key="sin.regla",
            actor=self.user,
        )
        self.assertEqual(signal.status, EdgeSignalStatus.PENDING)
        self.assertIn("Sin regla", signal.result_detail)

    def test_signal_becomes_station_event_in_mes(self):
        unit, station, device = self.build_station_context()
        self.make_rule(device=device)

        signal, _ = ingest_signal(
            gateway=self.gateway,
            device_code=device.code,
            external_id="SIG-0004",
            signal_key="scan.unit",
            raw_value=unit.serial_number,
            unit_serial_number=unit.serial_number,
            operator_username=self.user.username,
            actor=self.user,
        )

        self.assertEqual(signal.status, EdgeSignalStatus.NORMALIZED)
        self.assertIsNotNone(signal.inbound_event)
        self.assertEqual(signal.inbound_event.status, EquipmentInboundEventStatus.PROCESSED)
        self.assertTrue(
            UnitStationEvent.objects.filter(
                unit=unit, station=station, event_type=StationEventType.STARTED
            ).exists()
        )

    def test_signal_becomes_measurement(self):
        unit, _, device = self.build_station_context()
        self.make_rule(
            device=device,
            code="R-TORQUE",
            name="Torque final",
            signal_key="torque.final",
            action=EdgeRuleAction.MEASUREMENT,
            station_event_type="",
            measurement_code="TORQUE",
            measurement_name="Torque final",
            unit_of_measure="Nm",
            min_value=Decimal("40"),
            max_value=Decimal("45"),
        )

        signal, _ = ingest_signal(
            gateway=self.gateway,
            device_code=device.code,
            external_id="SIG-0005",
            signal_key="torque.final",
            raw_value="42.5",
            unit_serial_number=unit.serial_number,
            actor=self.user,
        )

        self.assertEqual(signal.status, EdgeSignalStatus.NORMALIZED)
        self.assertIsNotNone(signal.measurement)
        self.assertTrue(ProductionMeasurement.objects.filter(code="TORQUE").exists())

    def test_out_of_range_reading_is_rejected(self):
        unit, _, device = self.build_station_context()
        self.make_rule(
            device=device,
            code="R-TORQUE",
            signal_key="torque.final",
            action=EdgeRuleAction.MEASUREMENT,
            station_event_type="",
            measurement_code="TORQUE",
            min_value=Decimal("40"),
            max_value=Decimal("45"),
        )

        signal, _ = ingest_signal(
            gateway=self.gateway,
            device_code=device.code,
            external_id="SIG-0006",
            signal_key="torque.final",
            raw_value="80",
            unit_serial_number=unit.serial_number,
            actor=self.user,
        )

        self.assertEqual(signal.status, EdgeSignalStatus.REJECTED)
        self.assertIn("sobre el maximo", signal.result_detail)
        self.assertFalse(ProductionMeasurement.objects.filter(code="TORQUE").exists())

    def test_ignore_rule_marks_signal_as_ignored(self):
        _, _, device = self.build_station_context()
        self.make_rule(
            device=device,
            code="R-RUIDO",
            signal_key="heartbeat.tick",
            action=EdgeRuleAction.IGNORE,
            station_event_type="",
        )
        signal, _ = ingest_signal(
            gateway=self.gateway,
            device_code=device.code,
            external_id="SIG-0007",
            signal_key="heartbeat.tick",
            actor=self.user,
        )
        self.assertEqual(signal.status, EdgeSignalStatus.IGNORED)

    def test_retry_normalizes_after_rule_is_created(self):
        unit, _, device = self.build_station_context()
        signal, _ = ingest_signal(
            gateway=self.gateway,
            device_code=device.code,
            external_id="SIG-0008",
            signal_key="scan.unit",
            unit_serial_number=unit.serial_number,
            operator_username=self.user.username,
            actor=self.user,
        )
        self.assertEqual(signal.status, EdgeSignalStatus.PENDING)

        self.make_rule(device=device)
        retry_signal(signal, actor=self.user)

        self.assertEqual(signal.status, EdgeSignalStatus.NORMALIZED)

    def test_retry_on_normalized_signal_is_refused(self):
        unit, _, device = self.build_station_context()
        self.make_rule(device=device)
        signal, _ = ingest_signal(
            gateway=self.gateway,
            device_code=device.code,
            external_id="SIG-0009",
            signal_key="scan.unit",
            unit_serial_number=unit.serial_number,
            operator_username=self.user.username,
            actor=self.user,
        )
        with self.assertRaises(ValueError):
            retry_signal(signal, actor=self.user)

    def test_device_specific_rule_wins_over_generic_one(self):
        unit, _, device = self.build_station_context()
        self.make_rule(
            code="R-GENERICA",
            name="Generica",
            device=None,
            priority=10,
            station_event_type=StationEventType.COMPLETED,
        )
        self.make_rule(
            code="R-ESPECIFICA",
            name="Especifica",
            device=device,
            priority=1,
            station_event_type=StationEventType.STARTED,
        )

        signal, _ = ingest_signal(
            gateway=self.gateway,
            device_code=device.code,
            external_id="SIG-0010",
            signal_key="scan.unit",
            unit_serial_number=unit.serial_number,
            operator_username=self.user.username,
            actor=self.user,
        )
        self.assertEqual(signal.rule.code, "R-ESPECIFICA")

    # ---------- handshake de comandos ----------

    def test_command_handshake_queue_claim_ack(self):
        command = queue_command(
            gateway=self.gateway, command_type=EdgeCommandType.PING, actor=self.user
        )
        self.assertEqual(command.status, EdgeCommandStatus.QUEUED)
        self.assertIsNotNone(command.expires_at)

        claimed = claim_commands(self.gateway, actor=self.user)
        command.refresh_from_db()
        self.assertEqual([item.pk for item in claimed], [command.pk])
        self.assertEqual(command.status, EdgeCommandStatus.SENT)

        ack_command(command=command, succeeded=True, actor=self.user, response={"pong": True})
        command.refresh_from_db()
        self.assertEqual(command.status, EdgeCommandStatus.ACKED)
        self.assertEqual(command.response, {"pong": True})

    def test_failed_ack_marks_command_failed(self):
        command = queue_command(
            gateway=self.gateway, command_type=EdgeCommandType.RESTART_AGENT, actor=self.user
        )
        claim_commands(self.gateway, actor=self.user)
        command.refresh_from_db()
        ack_command(command=command, succeeded=False, actor=self.user, detail="Sin permisos")
        command.refresh_from_db()
        self.assertEqual(command.status, EdgeCommandStatus.FAILED)

    def test_expired_command_is_not_delivered(self):
        command = queue_command(
            gateway=self.gateway,
            command_type=EdgeCommandType.PING,
            actor=self.user,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        claimed = claim_commands(self.gateway, actor=self.user)
        command.refresh_from_db()
        self.assertEqual(claimed, [])
        self.assertEqual(command.status, EdgeCommandStatus.EXPIRED)

    def test_command_for_foreign_device_is_refused(self):
        other_gateway = EdgeGateway.objects.create(
            code="GW-02", name="Otro collector", created_by=self.user, updated_by=self.user
        )
        _, _, device = self.build_station_context()
        with self.assertRaises(ValueError):
            queue_command(
                gateway=other_gateway,
                command_type=EdgeCommandType.PING,
                actor=self.user,
                device=device,
            )

    # ---------- API del collector ----------

    def test_api_requires_valid_gateway_token(self):
        api = APIClient()
        response = api.post(
            "/api/edge/v1/heartbeat/", {}, format="json", HTTP_HOST=self.get_test_tenant_domain()
        )
        self.assertEqual(response.status_code, 403)

        response = api.post(
            "/api/edge/v1/heartbeat/",
            {},
            format="json",
            HTTP_HOST=self.get_test_tenant_domain(),
            HTTP_X_EDGE_TOKEN="token-falso",
        )
        self.assertEqual(response.status_code, 403)

    def test_api_ingests_batch_and_reports_duplicates(self):
        _, _, device = self.build_station_context()
        api = APIClient()
        body = {
            "signals": [
                {
                    "external_id": "API-0001",
                    "device_code": device.code,
                    "signal_key": "torque.final",
                    "raw_value": "41",
                },
                {
                    "external_id": "API-0002",
                    "device_code": device.code,
                    "signal_key": "torque.final",
                    "raw_value": "43",
                    "from_buffer": True,
                },
            ]
        }
        headers = {
            "HTTP_HOST": self.get_test_tenant_domain(),
            "HTTP_X_EDGE_TOKEN": self.gateway.auth_token,
        }

        first = api.post("/api/edge/v1/signals/", body, format="json", **headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(first.data["accepted"]), 2)

        again = api.post("/api/edge/v1/signals/", body, format="json", **headers)
        self.assertEqual(len(again.data["accepted"]), 0)
        self.assertEqual(len(again.data["duplicated"]), 2)
        self.assertEqual(EdgeSignal.objects.count(), 2)

    def test_api_heartbeat_reports_pending_commands(self):
        queue_command(gateway=self.gateway, command_type=EdgeCommandType.PING, actor=self.user)
        api = APIClient()
        response = api.post(
            "/api/edge/v1/heartbeat/",
            {"agent_version": "1.3.0", "buffered_count": 7},
            format="json",
            HTTP_HOST=self.get_test_tenant_domain(),
            HTTP_X_EDGE_TOKEN=self.gateway.auth_token,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["pending_commands"], 1)
        self.gateway.refresh_from_db()
        self.assertEqual(self.gateway.buffered_signal_count, 7)

    def test_api_command_pull_and_ack(self):
        command = queue_command(
            gateway=self.gateway, command_type=EdgeCommandType.FLUSH_BUFFER, actor=self.user
        )
        api = APIClient()
        headers = {
            "HTTP_HOST": self.get_test_tenant_domain(),
            "HTTP_X_EDGE_TOKEN": self.gateway.auth_token,
        }

        pull = api.get("/api/edge/v1/commands/", **headers)
        self.assertEqual(pull.status_code, 200)
        self.assertEqual(pull.data["commands"][0]["id"], command.pk)

        ack = api.post(
            "/api/edge/v1/commands/ack/",
            {"command_id": command.pk, "succeeded": True, "response": {"flushed": 12}},
            format="json",
            **headers,
        )
        self.assertEqual(ack.status_code, 200)
        command.refresh_from_db()
        self.assertEqual(command.status, EdgeCommandStatus.ACKED)

    def test_api_device_config_lists_active_devices(self):
        _, station, device = self.build_station_context()
        api = APIClient()
        response = api.get(
            "/api/edge/v1/devices/",
            HTTP_HOST=self.get_test_tenant_domain(),
            HTTP_X_EDGE_TOKEN=self.gateway.auth_token,
        )
        self.assertEqual(response.status_code, 200)
        codes = [item["code"] for item in response.data["devices"]]
        self.assertIn(device.code, codes)
        self.assertEqual(response.data["devices"][0]["station_code"], station.code)

    # ---------- GUI ----------

    def test_module_screens_render(self):
        self.build_station_context()
        for url in [
            "/conectividad/",
            "/conectividad/gateways/",
            "/conectividad/dispositivos/",
            "/conectividad/reglas/",
            "/conectividad/senales/",
            "/conectividad/salud/",
            "/conectividad/comandos/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_module_is_hidden_without_permission(self):
        stranger = get_user_model().objects.create_user(
            username="sin-edge", password="StrongPass.2026"
        )
        TenantMembership.objects.create(tenant=self.tenant, user=stranger, is_active=True)
        outsider = Client()
        outsider.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        outsider.force_login(stranger)

        home = outsider.get("/")
        self.assertNotContains(home, 'href="/conectividad/"')
        self.assertEqual(outsider.get("/conectividad/").status_code, 403)

    def test_gateway_token_rotation_changes_credential(self):
        original = self.gateway.auth_token
        response = self.client.post(f"/conectividad/gateways/{self.gateway.pk}/token/")
        self.assertEqual(response.status_code, 302)
        self.gateway.refresh_from_db()
        self.assertNotEqual(self.gateway.auth_token, original)
