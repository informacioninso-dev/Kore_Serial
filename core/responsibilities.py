"""
Cadena de responsables de un documento (recibe / revisa / aprueba / libera...).

ISO 13485 exige que el documento evidencie quien participo en cada paso, no solo
quien lo ejecuto. Los modelos ya guardan esos datos en campos `*_by` (con su
fecha), pero cada documento los nombra distinto. Este modulo los normaliza en una
sola lista para que el PDF y el Excel muestren el mismo bloque de firmas en todos
los documentos, sin repetir la logica en cada vista.

Uso:

    from core.responsibilities import build_signatories
    firmas = build_signatories(obj)
    # -> [{"role": "Elaborado por", "name": "Ana Perez", "date": "17/08/2026 10:22"}, ...]
"""

# Campos de responsabilidad conocidos, en orden de flujo (elaborar -> recibir ->
# revisar -> inspeccionar -> aprobar -> liberar -> cerrar). Cada entrada es
# (campo_usuario, etiqueta, campo_fecha_opcional).
_RESPONSABLES = [
    ("created_by", "Elaborado por", "created_at"),
    ("received_by", "Recibido por", "received_at"),
    ("order_reviewed_by", "Revisado por", "order_reviewed_at"),
    ("reviewed_by", "Revisado por", "reviewed_at"),
    ("availability_reviewed_by", "Disponibilidad revisada por", "availability_reviewed_at"),
    ("inspected_by", "Inspeccionado por", "inspected_at"),
    ("checked_by", "Verificado por", "checked_at"),
    ("evaluated_by", "Evaluado por", "evaluation_date"),
    ("reconciled_by", "Conciliado por", "reconciled_at"),
    ("cleared_by", "Despejado por", "cleared_at"),
    ("verified_by", "Verificado por", "verified_at"),
    ("confirmed_by", "Confirmado por", "confirmed_at"),
    ("order_confirmed_by", "Confirmado por", "order_confirmed_at"),
    ("posted_by", "Contabilizado por", "posted_at"),
    ("reported_by", "Reportado por", None),
    ("approved_by", "Aprobado por", "approved_at"),
    ("quality_approved_by", "Aprobado por Calidad", "quality_approved_at"),
    ("released_by", "Liberado por", "released_at"),
    ("closed_by", "Cerrado por", "closed_at"),
]


def _name(user):
    if user is None:
        return ""
    full = user.get_full_name() if hasattr(user, "get_full_name") else ""
    return full or getattr(user, "username", "") or ""


def _fecha(obj, campo, fmt):
    if not campo:
        return ""
    valor = getattr(obj, campo, None)
    if not valor:
        return ""
    try:
        return valor.strftime(fmt)
    except (AttributeError, ValueError):
        return str(valor)


def build_signatories(obj, fmt="%d/%m/%Y %H:%M"):
    """Devuelve la cadena de responsables presente en `obj`.

    Solo incluye los pasos que tienen usuario asignado. Nunca falla si un campo
    no existe: al documento que solo tiene `created_by` le sale una sola firma.
    """
    firmas = []
    vistos = set()
    for campo, etiqueta, campo_fecha in _RESPONSABLES:
        if not hasattr(obj, campo):
            continue
        user = getattr(obj, campo, None)
        if user is None:
            continue
        # Evitar duplicar la misma persona en el mismo rol.
        clave = (etiqueta, getattr(user, "pk", None))
        if clave in vistos:
            continue
        vistos.add(clave)
        firmas.append({
            "role": etiqueta,
            "name": _name(user),
            "date": _fecha(obj, campo_fecha, fmt),
        })
    return firmas
