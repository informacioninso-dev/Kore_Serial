from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from eventbus.models import EventSubscription, EventType, SubscriptionHandler
from eventbus.services import dispatch_pending, publish, seed_event_catalog
from tenants.models import TenantMembership

from .models import (
    Connector,
    ConnectorContract,
    ConnectorDirection,
    ConnectorSystem,
    ConnectorTransport,
    InboundMessage,
    InboundStatus,
    MessageStatus,
    OutboundMessage,
)
from .services import (
    flush_outbound,
    queue_from_event,
    receive_inbound,
    reconcile,
    requeue_missing,
    send_message,
)


class ConnectTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Empresa Connect de prueba"

    @staticmethod
    def get_test_tenant_domain():
        return "connect.test.com"

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        self.user = get_user_model().objects.create_user(
            username="connect-operator", password="StrongPass.2026"
        )
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        self.user.user_permissions.add(
            *Permission.objects.filter(content_type__app_label="connect")
        )
        self.user.user_permissions.add(
            *Permission.objects.filter(content_type__app_label="eventbus")
        )
        self.client.force_login(self.user)
        seed_event_catalog(actor=self.user)

        self.connector = Connector.objects.create(
            code="ERP-01",
            name="ERP corporativo",
            system=ConnectorSystem.ERP,
            direction=ConnectorDirection.BIDIRECTIONAL,
            inbound_token="token-erp-01",
            created_by=self.user,
            updated_by=self.user,
        )
        self.event_type = EventType.objects.get(code="produccion.unidad.completada")
        self.contract = ConnectorContract.objects.create(
            connector=self.connector,
            code="ERP-OUT-UNIDAD",
            name="Unidad completada hacia ERP",
            direction=ConnectorDirection.OUTBOUND,
            event_type=self.event_type,
            field_map={"orderNo": "unit", "workCenter": "station"},
            static_fields={"source": "KORE"},
            created_by=self.user,
            updated_by=self.user,
        )

    def make_event(self, key="evt:1", unit="U1"):
        event, _ = publish(
            event_code="produccion.unidad.completada",
            idempotency_key=key,
            payload={"unit": unit, "station": "ST-01", "line": "L1"},
            aggregate_type="unit",
            aggregate_id=unit,
            actor=self.user,
        )
        return event

    # ---------- contratos ----------

    def test_contract_renders_external_vocabulary(self):
        body = self.contract.render({"unit": "U1", "station": "ST-01", "line": "L1"})
        self.assertEqual(body["orderNo"], "U1")
        self.assertEqual(body["workCenter"], "ST-01")
        self.assertEqual(body["source"], "KORE")
        self.assertNotIn("line", body)

    def test_contract_without_map_passes_payload_through(self):
        self.contract.field_map = {}
        self.contract.save(update_fields=["field_map"])
        body = self.contract.render({"unit": "U1", "line": "L1"})
        self.assertEqual(body["unit"], "U1")
        self.assertEqual(body["line"], "L1")

    # ---------- cola de salida ----------

    def test_event_queues_one_message_per_contract(self):
        event = self.make_event()
        messages = queue_from_event(event, actor=self.user)
        self.assertEqual(len(messages), 1)
        message = messages[0]
        self.assertEqual(message.status, MessageStatus.QUEUED)
        self.assertEqual(message.payload["orderNo"], "U1")

    def test_requeueing_the_same_event_does_not_duplicate(self):
        event = self.make_event()
        queue_from_event(event, actor=self.user)
        queue_from_event(event, actor=self.user)
        self.assertEqual(OutboundMessage.objects.filter(event=event).count(), 1)

    def test_inactive_contract_does_not_queue(self):
        self.contract.is_active = False
        self.contract.save(update_fields=["is_active"])
        event = self.make_event()
        self.assertEqual(queue_from_event(event, actor=self.user), [])

    def test_inactive_connector_does_not_queue(self):
        self.connector.is_active = False
        self.connector.save(update_fields=["is_active"])
        event = self.make_event()
        self.assertEqual(queue_from_event(event, actor=self.user), [])

    # ---------- envio ----------

    def test_log_transport_marks_sent_without_leaving_the_system(self):
        event = self.make_event()
        message = queue_from_event(event, actor=self.user)[0]
        send_message(message, actor=self.user)

        self.assertEqual(message.status, MessageStatus.SENT)
        self.assertIn("sin enviar", message.response_body)
        self.assertIsNotNone(message.sent_at)

    def test_http_transport_failure_schedules_a_retry(self):
        self.connector.transport = ConnectorTransport.HTTP
        self.connector.endpoint = "http://127.0.0.1:9/no-existe"
        self.connector.max_attempts = 3
        self.connector.save(update_fields=["transport", "endpoint", "max_attempts"])

        event = self.make_event()
        message = queue_from_event(event, actor=self.user)[0]
        send_message(message, actor=self.user)

        self.assertEqual(message.status, MessageStatus.FAILED)
        self.assertEqual(message.attempts, 1)
        self.assertIsNotNone(message.next_attempt_at)
        self.assertTrue(message.last_error)

    def test_message_is_discarded_after_max_attempts(self):
        self.connector.transport = ConnectorTransport.HTTP
        self.connector.endpoint = "http://127.0.0.1:9/no-existe"
        self.connector.max_attempts = 2
        self.connector.retry_backoff_seconds = 0
        self.connector.save(
            update_fields=["transport", "endpoint", "max_attempts", "retry_backoff_seconds"]
        )

        event = self.make_event()
        message = queue_from_event(event, actor=self.user)[0]
        send_message(message, actor=self.user)
        send_message(message, actor=self.user)

        self.assertEqual(message.status, MessageStatus.DISCARDED)
        self.assertEqual(message.attempts, 2)
        self.assertIsNone(message.next_attempt_at)

    def test_sent_message_is_not_sent_twice(self):
        event = self.make_event()
        message = queue_from_event(event, actor=self.user)[0]
        send_message(message, actor=self.user)
        with self.assertRaises(ValueError):
            send_message(message, actor=self.user)

    def test_flush_skips_messages_waiting_for_their_backoff(self):
        self.connector.transport = ConnectorTransport.HTTP
        self.connector.endpoint = "http://127.0.0.1:9/no-existe"
        self.connector.retry_backoff_seconds = 600
        self.connector.save(update_fields=["transport", "endpoint", "retry_backoff_seconds"])

        event = self.make_event()
        message = queue_from_event(event, actor=self.user)[0]
        send_message(message, actor=self.user)

        sent, failed = flush_outbound(actor=self.user)
        message.refresh_from_db()
        self.assertEqual((sent, failed), (0, 0))
        self.assertEqual(message.attempts, 1)

    # ---------- el bus encola en Connect ----------

    def test_outbound_subscription_queues_through_connect(self):
        EventSubscription.objects.create(
            code="SUB-ERP",
            name="Salida a ERP",
            event_type=self.event_type,
            handler=SubscriptionHandler.OUTBOUND,
            created_by=self.user,
            updated_by=self.user,
        )
        self.make_event(key="evt-bus:1", unit="U9")
        delivered, failed = dispatch_pending(actor=self.user)

        self.assertEqual((delivered, failed), (1, 0))
        self.assertTrue(OutboundMessage.objects.filter(payload__orderNo="U9").exists())

    # ---------- entrada ----------

    def test_inbound_is_idempotent(self):
        first, created_first = receive_inbound(
            connector=self.connector,
            external_id="ERP-MSG-1",
            payload={"orderNo": "U1"},
            actor=self.user,
        )
        second, created_second = receive_inbound(
            connector=self.connector,
            external_id="ERP-MSG-1",
            payload={"orderNo": "U1"},
            actor=self.user,
        )
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(InboundMessage.objects.count(), 1)

    def test_outbound_only_connector_refuses_inbound(self):
        self.connector.direction = ConnectorDirection.OUTBOUND
        self.connector.save(update_fields=["direction"])
        with self.assertRaises(ValueError):
            receive_inbound(
                connector=self.connector,
                external_id="ERP-MSG-2",
                payload={},
                actor=self.user,
            )

    def test_api_requires_connector_token(self):
        api = APIClient()
        headers = {"HTTP_HOST": self.get_test_tenant_domain()}

        anon = api.post("/api/connect/v1/inbound/", {}, format="json", **headers)
        self.assertEqual(anon.status_code, 403)

        wrong = api.post(
            "/api/connect/v1/inbound/",
            {"external_id": "X"},
            format="json",
            HTTP_X_CONNECT_TOKEN="token-falso",
            **headers,
        )
        self.assertEqual(wrong.status_code, 403)

    def test_api_receives_and_flags_duplicates(self):
        api = APIClient()
        headers = {
            "HTTP_HOST": self.get_test_tenant_domain(),
            "HTTP_X_CONNECT_TOKEN": self.connector.inbound_token,
        }
        body = {"external_id": "ERP-API-1", "payload": {"orderNo": "U5"}}

        first = api.post("/api/connect/v1/inbound/", body, format="json", **headers)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.data["duplicated"])

        again = api.post("/api/connect/v1/inbound/", body, format="json", **headers)
        self.assertTrue(again.data["duplicated"])
        self.assertEqual(InboundMessage.objects.count(), 1)

    # ---------- reconciliacion ----------

    def test_reconciliation_reports_the_gap(self):
        today = timezone.localdate()
        sent_event = self.make_event(key="evt-rec:1", unit="U1")
        self.make_event(key="evt-rec:2", unit="U2")

        message = queue_from_event(sent_event, actor=self.user)[0]
        send_message(message, actor=self.user)

        run = reconcile(
            connector=self.connector, date_from=today, date_to=today, actor=self.user
        )

        self.assertEqual(run.expected_count, 2)
        self.assertEqual(run.sent_count, 1)
        self.assertEqual(run.gap, 1)
        self.assertIn("evt-rec:2", run.missing_keys)
        self.assertFalse(run.is_clean)

    def test_requeue_missing_creates_the_pending_messages(self):
        today = timezone.localdate()
        self.make_event(key="evt-rec:3", unit="U3")
        run = reconcile(
            connector=self.connector, date_from=today, date_to=today, actor=self.user
        )
        self.assertEqual(run.gap, 1)

        created = requeue_missing(run, actor=self.user)
        self.assertEqual(created, 1)
        self.assertTrue(OutboundMessage.objects.filter(payload__orderNo="U3").exists())

    def test_clean_reconciliation_when_everything_was_sent(self):
        today = timezone.localdate()
        event = self.make_event(key="evt-rec:4", unit="U4")
        send_message(queue_from_event(event, actor=self.user)[0], actor=self.user)

        run = reconcile(
            connector=self.connector, date_from=today, date_to=today, actor=self.user
        )
        self.assertTrue(run.is_clean)
        self.assertEqual(run.gap, 0)

    # ---------- GUI ----------

    def test_module_screens_render(self):
        for url in [
            "/integraciones/",
            "/integraciones/conectores/",
            "/integraciones/contratos/",
            "/integraciones/salida/",
            "/integraciones/entrada/",
            "/integraciones/reconciliacion/",
            "/integraciones/reconciliacion/nueva/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_module_is_hidden_without_permission(self):
        stranger = get_user_model().objects.create_user(
            username="sin-connect", password="StrongPass.2026"
        )
        TenantMembership.objects.create(tenant=self.tenant, user=stranger, is_active=True)
        outsider = Client()
        outsider.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        outsider.force_login(stranger)

        self.assertNotContains(outsider.get("/"), 'href="/integraciones/"')
        self.assertEqual(outsider.get("/integraciones/").status_code, 403)
