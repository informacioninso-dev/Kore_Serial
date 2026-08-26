"""Tareas periodicas de integraciones.

La cola hacia sistemas externos tiene que vaciarse sola, y los reintentos
tienen que respetar su espera sin que nadie los empuje a mano.
"""

import logging

from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from core.scheduling import for_each_tenant

from .services import flush_outbound


logger = logging.getLogger(__name__)


@db_periodic_task(crontab(minute="*"))
def flush_outbound_queue():
    """Envia lo pendiente y los reintentos ya vencidos. Cada minuto."""

    def run():
        sent, failed = flush_outbound()
        if sent or failed:
            logger.info("Connect: %s enviados, %s fallidos", sent, failed)
        return sent, failed

    return for_each_tenant(run, task_name="flush_outbound_queue")
