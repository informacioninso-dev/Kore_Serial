"""Tareas periodicas del bus.

En planta nadie va a estar apretando "procesar pendientes": el reparto de
eventos y el recalculo de indicadores tienen que ocurrir solos.
"""

import logging

from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from core.scheduling import for_each_tenant

from .services import dispatch_pending, rebuild_all_indicators


logger = logging.getLogger(__name__)


@db_periodic_task(crontab(minute="*"))
def dispatch_pending_deliveries():
    """Reparte a los suscriptores lo que quedo en cola. Cada minuto."""

    def run():
        delivered, failed = dispatch_pending()
        if delivered or failed:
            logger.info("Bus: %s entregas correctas, %s fallidas", delivered, failed)
        return delivered, failed

    return for_each_tenant(run, task_name="dispatch_pending_deliveries")


@db_periodic_task(crontab(minute="*/10"))
def refresh_daily_indicators():
    """Rehace la foto del dia. Cada diez minutos alcanza para un tablero."""

    def run():
        snapshots = rebuild_all_indicators(timezone.localdate())
        return len(snapshots)

    return for_each_tenant(run, task_name="refresh_daily_indicators")
