import json

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

from core.models import OperationalAuditEvent


def _object_code(obj) -> str:
    if obj is None:
        return ""
    for attr in ("code", "number", "full_number", "document_number", "lot_number", "access_key"):
        value = getattr(obj, attr, None)
        if callable(value):
            value = value()
        if value:
            return str(value)
    if getattr(obj, "pk", None):
        return f"{_model_label(obj)}-{obj.pk}"
    return str(obj)


def _content_type(obj):
    """
    Solo un modelo Django real tiene ContentType. Se comprueba con isinstance
    y no con getattr(_meta): cualquier doble de prueba responde a _meta y
    acabaria insertando basura en contenttypes.
    """
    if not isinstance(obj, Model) or not getattr(obj, "pk", None):
        return None
    return ContentType.objects.get_for_model(obj, for_concrete_model=False)


def _model_label(obj) -> str:
    if obj is None:
        return ""
    if isinstance(obj, Model):
        return obj._meta.label
    return type(obj).__name__


def _actor(actor):
    """
    Solo un usuario real puede firmar el evento. Un doble de prueba responde
    a is_authenticated y pasaria el filtro, y luego la FK lo rechaza.
    """
    from django.contrib.auth import get_user_model

    if not isinstance(actor, get_user_model()) or not getattr(actor, "pk", None):
        return None
    return actor


def _object_pk(obj):
    """El id de origen solo es utilizable si viene de un modelo real."""
    if not isinstance(obj, Model):
        return None
    pk = getattr(obj, "pk", None)
    return pk if isinstance(pk, int) else None


def _clean_metadata(metadata):
    if not metadata:
        return {}
    return json.loads(json.dumps(metadata, default=str))


def log_operational_event(
    *,
    module: str,
    action: str,
    actor=None,
    obj=None,
    document_type: str = "",
    document_code: str = "",
    related_obj=None,
    related_code: str = "",
    from_status: str = "",
    to_status: str = "",
    reason: str = "",
    metadata: dict | None = None,
):
    """
    Registra un evento operacional auditable.

    Se debe llamar dentro del mismo flujo transaccional del cambio que evidencia.
    """
    return OperationalAuditEvent.objects.create(
        module=module,
        action=action,
        actor=_actor(actor),
        source_content_type=_content_type(obj),
        source_object_id=_object_pk(obj),
        source_model=_model_label(obj),
        source_code=_object_code(obj),
        document_type=str(document_type or ""),
        document_code=str(document_code or _object_code(obj) or ""),
        related_content_type=_content_type(related_obj),
        related_object_id=_object_pk(related_obj),
        related_code=str(related_code or _object_code(related_obj) or ""),
        from_status=str(from_status or ""),
        to_status=str(to_status or ""),
        reason=str(reason or ""),
        metadata=_clean_metadata(metadata),
    )
