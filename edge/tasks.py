"""Tareas periodicas de conectividad.

Un comando que nadie recogio no puede quedarse en cola para siempre: vence.
"""

import logging

from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from core.scheduling import for_each_tenant

from .services import expire_commands


logger = logging.getLogger(__name__)


@db_periodic_task(crontab(minute="*/5"))
def expire_stale_commands():
    """Marca vencidos los comandos que el gateway nunca confirmo."""

    def run():
        expired = expire_commands()
        if expired:
            logger.info("Edge: %s comandos vencidos", expired)
        return expired

    return for_each_tenant(run, task_name="expire_stale_commands")
