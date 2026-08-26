"""Utilidades para tareas de fondo en un sistema multi-tenant.

Una tarea periodica no vive dentro de ningun tenant: el consumidor de huey
arranca en el esquema publico. Por eso toda tarea tiene que recorrer los
tenants uno por uno y entrar a su esquema, o escribiria en el lugar
equivocado (o en ninguno).
"""

import logging

from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context


logger = logging.getLogger(__name__)


def active_tenants():
    """Tenants reales, sin el esquema publico."""
    return (
        get_tenant_model()
        .objects.exclude(schema_name=get_public_schema_name())
        .order_by("schema_name")
    )


def for_each_tenant(func, *, task_name=""):
    """Ejecuta `func()` dentro del esquema de cada tenant.

    El fallo de un tenant no puede dejar sin procesar a los demas: se registra
    y se sigue. Devuelve {schema: resultado} para poder ver que hizo cada uno.
    """
    results = {}
    for tenant in active_tenants():
        try:
            with schema_context(tenant.schema_name):
                results[tenant.schema_name] = func()
        except Exception:  # noqa: BLE001 - una planta caida no frena a las otras
            logger.exception(
                "Tarea %s fallo en el tenant %s", task_name or func.__name__, tenant.schema_name
            )
            results[tenant.schema_name] = None
    return results
