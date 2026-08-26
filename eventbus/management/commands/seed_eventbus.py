from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_tenants.utils import schema_context

from eventbus.models import EventSubscription, SubscriptionHandler
from eventbus.services import rebuild_all_indicators, seed_event_catalog
from tenants.models import Client


class Command(BaseCommand):
    help = "Siembra el catalogo de eventos y las suscripciones base de un tenant."

    def add_arguments(self, parser):
        parser.add_argument("--schema", default="demo", help="Schema tenant destino.")
        parser.add_argument(
            "--rebuild",
            action="store_true",
            help="Recalcula ademas los indicadores del dia.",
        )

    def handle(self, *args, **options):
        tenant = Client.objects.filter(schema_name=options["schema"]).first()
        if tenant is None:
            raise CommandError(f"Tenant no encontrado: {options['schema']}")
        admin = get_user_model().objects.filter(username="admin").first()
        if admin is None:
            raise CommandError("No existe el usuario admin. Ejecuta primero populate_kore_serial.")

        with schema_context(tenant.schema_name):
            created_types = seed_event_catalog(actor=admin)
            created_subs = self._seed_subscriptions(admin)
            if options["rebuild"]:
                snapshots = rebuild_all_indicators(timezone.localdate(), actor=admin)
                self.stdout.write(f"Indicadores recalculados: {len(snapshots)}.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Bus listo en {tenant.schema_name}: {created_types} tipos y {created_subs} suscripciones nuevas."
            )
        )

    def _seed_subscriptions(self, admin):
        """Indicadores escucha produccion y calidad; la bitacora escucha todo."""
        wanted = [
            ("SUB-INDICADORES-PROD", "Indicadores desde produccion", "PRODUCTION", SubscriptionHandler.INDICATORS),
            ("SUB-INDICADORES-CAL", "Indicadores desde calidad", "QUALITY", SubscriptionHandler.INDICATORS),
            ("SUB-BITACORA-ALM", "Bitacora de almacen", "WAREHOUSE", SubscriptionHandler.LEDGER),
            ("SUB-BITACORA-CON", "Bitacora de conectividad", "CONNECTIVITY", SubscriptionHandler.LEDGER),
        ]
        created = 0
        for code, name, domain, handler in wanted:
            _, was_created = EventSubscription.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "domain": domain,
                    "handler": handler,
                    "created_by": admin,
                    "updated_by": admin,
                },
            )
            created += int(was_created)
        return created
