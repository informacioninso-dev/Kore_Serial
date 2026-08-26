from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase

from assembly.models import (
    AssembledProduct,
    AssemblyLine,
    AssemblyRoute,
    AssemblyRouteStep,
    AssemblyStation,
    DowntimeStatus,
    ProductionDowntime,
    ProductionPlan,
    ProductionPlanStatus,
    ProductVersion,
    SerializedUnit,
    StationEventType,
)
from assembly.services import record_station_event
from tenants.models import TenantMembership

from .models import (
    DeliveryStatus,
    DomainEvent,
    EventDelivery,
    EventSubscription,
    EventType,
    IndicatorSnapshot,
    SubscriptionHandler,
)
from .services import (
    dispatch_pending,
    publish,
    rebuild_indicators,
    retry_delivery,
    seed_event_catalog,
)


class EventBusTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Empresa Eventos de prueba"

    @staticmethod
    def get_test_tenant_domain():
        return "eventos.test.com"

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        self.user = get_user_model().objects.create_user(
            username="bus-operator", password="StrongPass.2026"
        )
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        self.user.user_permissions.add(
            *Permission.objects.filter(content_type__app_label="eventbus")
        )
        self.client.force_login(self.user)
        seed_event_catalog(actor=self.user)

        self.line = AssemblyLine.objects.create(
            code="BUS-L1", name="Linea bus", created_by=self.user, updated_by=self.user
        )

    # ---------- fixtures ----------

    def build_unit(self, serial="BUS-UNIT-1"):
        product = AssembledProduct.objects.create(
            code=f"BUS-P-{serial}", name="Producto bus", created_by=self.user, updated_by=self.user
        )
        version = ProductVersion.objects.create(
            product=product, code="V1", name="Version", created_by=self.user, updated_by=self.user
        )
        unit = SerializedUnit.objects.create(
            version=version, serial_number=serial, created_by=self.user, updated_by=self.user
        )
        station = AssemblyStation.objects.create(
            line=self.line,
            code=f"BUS-ST-{serial}",
            name="Estacion bus",
            sequence=1,
            created_by=self.user,
            updated_by=self.user,
        )
        route = AssemblyRoute.objects.create(
            version=version, code=f"BUS-R-{serial}", name="Ruta bus",
            created_by=self.user, updated_by=self.user,
        )
        AssemblyRouteStep.objects.create(
            route=route, station=station, sequence=1, name="Paso",
            created_by=self.user, updated_by=self.user,
        )
        return unit, station

    def subscribe(self, handler=SubscriptionHandler.LEDGER, code="SUB-1", event_code=None, domain="PRODUCTION"):
        return EventSubscription.objects.create(
            code=code,
            name=f"Suscripcion {code}",
            event_type=EventType.objects.get(code=event_code) if event_code else None,
            domain="" if event_code else domain,
            handler=handler,
            created_by=self.user,
            updated_by=self.user,
        )

    # ---------- catalogo ----------

    def test_catalog_seed_is_idempotent(self):
        before = EventType.objects.count()
        created = seed_event_catalog(actor=self.user)
        self.assertEqual(created, 0)
        self.assertEqual(EventType.objects.count(), before)

    def test_unknown_event_type_is_not_published(self):
        event, created = publish(
            event_code="no.existe.en.catalogo",
            idempotency_key="x:1",
            payload={},
            actor=self.user,
        )
        self.assertIsNone(event)
        self.assertFalse(created)

    def test_inactive_event_type_is_not_published(self):
        event_type = EventType.objects.get(code="produccion.unidad.completada")
        event_type.is_active = False
        event_type.save(update_fields=["is_active"])

        event, created = publish(
            event_code=event_type.code,
            idempotency_key="inactivo:1",
            payload={},
            actor=self.user,
        )
        self.assertIsNone(event)
        self.assertFalse(created)

    def test_missing_contract_keys_are_flagged_but_published(self):
        event, created = publish(
            event_code="produccion.unidad.completada",
            idempotency_key="contrato:1",
            payload={"unit": "U1"},
            actor=self.user,
        )
        self.assertTrue(created)
        self.assertIn("station", event.detail)
        self.assertIn("line", event.detail)

    # ---------- idempotencia ----------

    def test_same_idempotency_key_publishes_once(self):
        first, created_first = publish(
            event_code="produccion.unidad.completada",
            idempotency_key="repetido:1",
            payload={"unit": "U1", "station": "S1", "line": "L1"},
            actor=self.user,
        )
        second, created_second = publish(
            event_code="produccion.unidad.completada",
            idempotency_key="repetido:1",
            payload={"unit": "U1", "station": "S1", "line": "L1"},
            actor=self.user,
        )
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(DomainEvent.objects.filter(idempotency_key="repetido:1").count(), 1)

    # ---------- emisores ----------

    def test_completing_a_station_emits_a_domain_event(self):
        unit, station = self.build_unit()
        record_station_event(
            actor=self.user,
            unit_serial_number=unit.serial_number,
            station_code=station.code,
            event_type=StationEventType.STARTED,
            external_reference="BUS-START-1",
        )
        record_station_event(
            actor=self.user,
            unit_serial_number=unit.serial_number,
            station_code=station.code,
            event_type=StationEventType.COMPLETED,
            external_reference="BUS-DONE-1",
        )
        event = DomainEvent.objects.filter(
            event_type__code="produccion.unidad.completada", aggregate_id=unit.serial_number
        ).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.line_id, self.line.pk)
        self.assertEqual(event.payload["station"], station.code)

    def test_closed_downtime_emits_event_with_minutes(self):
        started = timezone.now() - timedelta(minutes=30)
        downtime = ProductionDowntime.objects.create(
            code="BUS-DT-1",
            line=self.line,
            status=DowntimeStatus.CLOSED,
            started_at=started,
            ended_at=started + timedelta(minutes=30),
            cause_category="MECANICA",
            created_by=self.user,
            updated_by=self.user,
        )
        event = DomainEvent.objects.filter(idempotency_key=f"downtime:{downtime.pk}").first()
        self.assertIsNotNone(event)
        self.assertAlmostEqual(event.payload["minutes"], 30.0, places=1)

    def test_open_downtime_does_not_emit(self):
        ProductionDowntime.objects.create(
            code="BUS-DT-2",
            line=self.line,
            status=DowntimeStatus.OPEN,
            started_at=timezone.now(),
            cause_category="MECANICA",
            created_by=self.user,
            updated_by=self.user,
        )
        self.assertFalse(
            DomainEvent.objects.filter(event_type__code="produccion.paro.cerrado").exists()
        )

    # ---------- entregas ----------

    def test_event_fans_out_only_to_matching_subscriptions(self):
        self.subscribe(code="SUB-PROD", domain="PRODUCTION")
        self.subscribe(code="SUB-ALM", domain="WAREHOUSE")

        event, _ = publish(
            event_code="produccion.unidad.completada",
            idempotency_key="fanout:1",
            payload={"unit": "U1", "station": "S1", "line": "L1"},
            actor=self.user,
        )
        codes = list(event.deliveries.values_list("subscription__code", flat=True))
        self.assertEqual(codes, ["SUB-PROD"])

    def test_inactive_subscription_receives_nothing(self):
        subscription = self.subscribe(code="SUB-OFF")
        subscription.is_active = False
        subscription.save(update_fields=["is_active"])

        event, _ = publish(
            event_code="produccion.unidad.completada",
            idempotency_key="fanout:2",
            payload={"unit": "U1", "station": "S1", "line": "L1"},
            actor=self.user,
        )
        self.assertEqual(event.deliveries.count(), 0)

    def test_dispatch_marks_deliveries_processed(self):
        self.subscribe(code="SUB-LEDGER", handler=SubscriptionHandler.LEDGER)
        publish(
            event_code="produccion.unidad.completada",
            idempotency_key="dispatch:1",
            payload={"unit": "U1", "station": "S1", "line": "L1"},
            actor=self.user,
        )
        delivered, failed = dispatch_pending(actor=self.user)
        self.assertEqual((delivered, failed), (1, 0))
        self.assertEqual(
            EventDelivery.objects.filter(status=DeliveryStatus.DELIVERED).count(), 1
        )

    def test_failing_handler_marks_delivery_failed_without_breaking_publish(self):
        self.subscribe(code="SUB-OUT", handler=SubscriptionHandler.OUTBOUND)
        event, created = publish(
            event_code="produccion.unidad.completada",
            idempotency_key="dispatch:2",
            payload={"unit": "U1", "station": "S1", "line": "L1"},
            actor=self.user,
        )
        self.assertTrue(created)

        delivered, failed = dispatch_pending(actor=self.user)
        self.assertEqual((delivered, failed), (0, 1))
        delivery = event.deliveries.first()
        self.assertEqual(delivery.status, DeliveryStatus.FAILED)
        self.assertIn("contrato de salida", delivery.last_error)

    def test_retry_is_refused_after_max_attempts(self):
        subscription = self.subscribe(code="SUB-OUT2", handler=SubscriptionHandler.OUTBOUND)
        subscription.max_attempts = 1
        subscription.save(update_fields=["max_attempts"])
        publish(
            event_code="produccion.unidad.completada",
            idempotency_key="dispatch:3",
            payload={"unit": "U1", "station": "S1", "line": "L1"},
            actor=self.user,
        )
        dispatch_pending(actor=self.user)
        delivery = EventDelivery.objects.get(subscription=subscription)

        with self.assertRaises(ValueError):
            retry_delivery(delivery, actor=self.user)

    # ---------- indicadores ----------

    def test_indicators_are_rebuilt_from_events(self):
        today = timezone.localdate()
        product = AssembledProduct.objects.create(
            code="BUS-PLAN-P", name="Producto plan", created_by=self.user, updated_by=self.user
        )
        version = ProductVersion.objects.create(
            product=product, code="V1", name="Version", created_by=self.user, updated_by=self.user
        )
        ProductionPlan.objects.create(
            code="BUS-PLAN-1",
            version=version,
            line=self.line,
            planned_date=today,
            shift="M",
            target_quantity=10,
            status=ProductionPlanStatus.RELEASED,
            created_by=self.user,
            updated_by=self.user,
        )
        for index in range(8):
            publish(
                event_code="produccion.unidad.completada",
                idempotency_key=f"ind-done:{index}",
                payload={"unit": f"U{index}", "station": "S1", "line": self.line.code},
                aggregate_type="unit",
                aggregate_id=f"U{index}",
                line=self.line,
                actor=self.user,
            )
        publish(
            event_code="produccion.estacion.falla",
            idempotency_key="ind-fail:1",
            payload={"unit": "U0", "station": "S1", "line": self.line.code},
            aggregate_type="unit",
            aggregate_id="U0",
            line=self.line,
            actor=self.user,
        )
        publish(
            event_code="produccion.paro.cerrado",
            idempotency_key="ind-down:1",
            payload={"line": self.line.code, "minutes": 48, "cause": "MECANICA"},
            aggregate_type="line",
            aggregate_id=self.line.code,
            line=self.line,
            actor=self.user,
        )

        snapshot = rebuild_indicators(line=self.line, date=today, actor=self.user)

        self.assertEqual(snapshot.completed_units, 8)
        self.assertEqual(snapshot.failure_count, 1)
        self.assertEqual(snapshot.downtime_minutes, Decimal("48.00"))
        # turno por defecto 480 min, 48 de paro -> 90% disponible
        self.assertEqual(snapshot.availability_percent, Decimal("90.00"))
        # 8 completadas sobre objetivo 10 -> 80%
        self.assertEqual(snapshot.performance_percent, Decimal("80.00"))
        # 8 completadas sobre 9 hechos -> 88.89%
        self.assertEqual(snapshot.quality_percent, Decimal("88.89"))
        # 7 unidades sin falla sobre 8 completadas
        self.assertEqual(snapshot.fpy_percent, Decimal("87.50"))
        self.assertEqual(snapshot.mttr_minutes, Decimal("48.00"))
        self.assertIsNotNone(snapshot.oee_percent)

    def test_rebuild_is_idempotent_for_the_same_day(self):
        today = timezone.localdate()
        rebuild_indicators(line=self.line, date=today, actor=self.user)
        rebuild_indicators(line=self.line, date=today, actor=self.user)
        self.assertEqual(
            IndicatorSnapshot.objects.filter(line=self.line, date=today).count(), 1
        )

    def test_indicator_handler_recomputes_on_dispatch(self):
        self.subscribe(code="SUB-IND", handler=SubscriptionHandler.INDICATORS)
        publish(
            event_code="produccion.unidad.completada",
            idempotency_key="ind-auto:1",
            payload={"unit": "U9", "station": "S1", "line": self.line.code},
            aggregate_type="unit",
            aggregate_id="U9",
            line=self.line,
            actor=self.user,
        )
        dispatch_pending(actor=self.user)

        snapshot = IndicatorSnapshot.objects.filter(line=self.line).first()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.completed_units, 1)

    # ---------- GUI ----------

    def test_module_screens_render(self):
        for url in [
            "/eventos/",
            "/eventos/catalogo/",
            "/eventos/eventos/",
            "/eventos/suscripciones/",
            "/eventos/entregas/",
            "/eventos/indicadores/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_module_is_hidden_without_permission(self):
        stranger = get_user_model().objects.create_user(
            username="sin-bus", password="StrongPass.2026"
        )
        TenantMembership.objects.create(tenant=self.tenant, user=stranger, is_active=True)
        outsider = Client()
        outsider.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        outsider.force_login(stranger)

        self.assertNotContains(outsider.get("/"), 'href="/eventos/"')
        self.assertEqual(outsider.get("/eventos/").status_code, 403)
