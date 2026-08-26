from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context

from connect.models import (
    Connector,
    ConnectorContract,
    ConnectorDirection,
    ConnectorSystem,
    ConnectorTransport,
)
from eventbus.models import EventSubscription, EventType, SubscriptionHandler
from tenants.models import Client


class Command(BaseCommand):
    help = "Crea un conector ERP de demostracion con sus contratos. No envia nada."

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
            created = self._populate(admin)

        self.stdout.write(
            self.style.SUCCESS(
                f"Integraciones listas en {tenant.schema_name}: {created} objetos nuevos. "
                "El conector queda en transporte LOG: no envia nada hasta que lo cambies."
            )
        )

    def _populate(self, admin):
        audit = {"created_by": admin, "updated_by": admin}
        created = 0

        connector, was_created = Connector.objects.get_or_create(
            code="ERP-DEMO",
            defaults={
                "name": "ERP de demostracion",
                "system": ConnectorSystem.ERP,
                "direction": ConnectorDirection.BIDIRECTIONAL,
                "transport": ConnectorTransport.LOG,
                "inbound_token": "demo-erp-token",
                **audit,
            },
        )
        created += int(was_created)

        completed = EventType.objects.filter(code="produccion.unidad.completada").first()
        if completed is not None:
            _, was_created = ConnectorContract.objects.get_or_create(
                code="ERP-OUT-UNIDAD",
                defaults={
                    "connector": connector,
                    "name": "Unidad completada hacia ERP",
                    "direction": ConnectorDirection.OUTBOUND,
                    "event_type": completed,
                    "field_map": {"orderNo": "unit", "workCenter": "station", "plant": "line"},
                    "static_fields": {"source": "KORE-LINE"},
                    **audit,
                },
            )
            created += int(was_created)

            _, was_created = EventSubscription.objects.get_or_create(
                code="SUB-ERP-SALIDA",
                defaults={
                    "name": "Salida hacia ERP",
                    "event_type": completed,
                    "handler": SubscriptionHandler.OUTBOUND,
                    **audit,
                },
            )
            created += int(was_created)

        _, was_created = ConnectorContract.objects.get_or_create(
            code="ERP-IN-ORDEN",
            defaults={
                "connector": connector,
                "name": "Orden de produccion desde ERP",
                "direction": ConnectorDirection.INBOUND,
                "field_map": {"code": "orderNo", "quantity": "qty"},
                **audit,
            },
        )
        created += int(was_created)

        return created
