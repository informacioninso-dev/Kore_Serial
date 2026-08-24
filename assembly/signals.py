from django.db.models.signals import post_save
from django.dispatch import receiver

from core.audit import log_operational_event

from .models import SerializedUnit


@receiver(post_save, sender=SerializedUnit)
def log_serialized_unit_creation(sender, instance, created, **kwargs):
    if created:
        log_operational_event(
            module="PRODUCTION",
            action="CREATE",
            actor=instance.created_by,
            obj=instance,
            document_type="Unidad serializada",
            document_code=instance.serial_number,
            to_status=instance.status,
        )
