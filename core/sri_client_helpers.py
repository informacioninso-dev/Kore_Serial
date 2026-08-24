"""
core/sri_client_helpers.py

Helpers para aplicar respuestas de la API externa a los modelos de documento.
"""
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def _status_enum(document):
    model_name = document._meta.model_name
    if model_name in {"supplierretention", "purchaseliquidation"}:
        from finance.models import FiscalDocumentStatus

        return FiscalDocumentStatus
    if model_name == "guiaremision":
        from sales.models import GuiaRemisionStatus

        return GuiaRemisionStatus
    if model_name == "creditnote":
        from sales.models import CreditNoteStatus

        return CreditNoteStatus
    from sales.models import InvoiceStatus

    return InvoiceStatus


def _document_code(document) -> str:
    value = getattr(document, "full_number", "")
    if callable(value):
        value = value()
    return str(value or getattr(document, "code", "") or getattr(document, "access_key", "") or document.pk)


def _document_label(document) -> str:
    """
    Etiqueta legible del documento. Es solo texto para la bitacora: si no se
    puede derivar no debe abortar la emision fiscal, que es la operacion real.
    """
    meta = getattr(document, "_meta", None)
    verbose_name = getattr(meta, "verbose_name", None)
    return str(verbose_name or type(document).__name__).title()


def _log_fiscal_document_status(document, previous_status, reason, result=None) -> None:
    from core.audit import log_operational_event

    log_operational_event(
        module="BILLING",
        action="STATUS_CHANGE",
        actor=getattr(document, "updated_by", None) or getattr(document, "created_by", None),
        obj=document,
        document_type=_document_label(document),
        document_code=_document_code(document),
        from_status=previous_status,
        to_status=document.status,
        reason=reason,
        metadata={
            "access_key": getattr(document, "access_key", ""),
            "authorization_number": getattr(document, "authorization_number", ""),
            "sri_response": getattr(document, "sri_response", ""),
            "gateway_status": (result or {}).get("status") or (result or {}).get("estado") or "",
        },
    )


def apply_sign_result(document, result: dict) -> None:
    """
    Aplica el resultado de POST /firmar al documento.
    La API debe devolver: { "xml_firmado": "...", "ok": true }
    """
    StatusEnum = _status_enum(document)

    if not result.get("ok"):
        error = result.get("error") or result.get("detail") or "Error desconocido al firmar"
        raise ValidationError(f"Error al firmar: {error}")

    xml_signed = result.get("xml_firmado") or result.get("xml_signed")
    if not xml_signed:
        raise ValidationError("La API no devolvio el XML firmado.")

    previous_status = document.status
    document.xml_signed = xml_signed
    document.status = StatusEnum.SIGNED
    document.save(update_fields=["xml_signed", "status"])
    _log_fiscal_document_status(document, previous_status, "Documento firmado por gateway fiscal.", result)


def apply_send_result(document, result: dict) -> None:
    """
    Aplica el resultado de POST /emitir al documento legacy.
    """
    from sales.sri_service import _try_create_accounting_event

    StatusEnum = _status_enum(document)
    estado = result.get("estado", "").upper()

    if estado == "AUTORIZADO":
        previous_status = document.status
        document.authorization_number = result.get("numero_autorizacion", document.access_key)
        raw_date = result.get("fecha_autorizacion")
        if raw_date:
            from dateutil import parser as date_parser

            try:
                document.authorization_date = date_parser.parse(raw_date)
            except Exception:
                document.authorization_date = timezone.now()
        else:
            document.authorization_date = timezone.now()
        document.sri_response = f"AUTORIZADO - {document.authorization_number}"
        document.status = StatusEnum.AUTHORIZED
        document.save(update_fields=[
            "authorization_number",
            "authorization_date",
            "sri_response",
            "status",
        ])
        _log_fiscal_document_status(document, previous_status, "Documento autorizado por SRI.", result)
        _try_create_accounting_event(document)
        return

    if estado in ("DEVUELTA", "RECHAZADO"):
        previous_status = document.status
        msg = result.get("mensaje") or result.get("error") or estado
        document.sri_response = msg
        document.status = StatusEnum.REJECTED
        document.save(update_fields=["sri_response", "status"])
        _log_fiscal_document_status(document, previous_status, f"SRI {estado}: {msg}", result)
        raise ValidationError(f"SRI {estado}: {msg}")

    previous_status = document.status
    document.sri_response = result.get("mensaje", "Enviado - pendiente de autorizacion")
    document.status = StatusEnum.SENT
    document.save(update_fields=["sri_response", "status"])
    _log_fiscal_document_status(document, previous_status, "Documento enviado al SRI.", result)


def apply_b22_emit_result(document, result: dict) -> None:
    """
    Aplica la respuesta de B22 POST /v1/comprobantes.
    """
    from sales.sri_service import _try_create_accounting_event

    StatusEnum = _status_enum(document)
    status = (result.get("status") or "").upper()
    access_key = result.get("access_key") or document.access_key
    xml_signed = result.get("xml_signed") or document.xml_signed

    if status == "AUTHORIZED":
        previous_status = document.status
        document.access_key = access_key
        document.xml_signed = xml_signed
        document.authorization_number = result.get("authorization", access_key)
        raw_date = result.get("authorized_at")
        if raw_date:
            parsed = parse_datetime(str(raw_date))
            document.authorization_date = parsed or timezone.now()
        else:
            document.authorization_date = timezone.now()
        document.sri_response = f"AUTORIZADO - {document.authorization_number}"
        document.status = StatusEnum.AUTHORIZED
        document.save(update_fields=[
            "access_key",
            "xml_signed",
            "authorization_number",
            "authorization_date",
            "sri_response",
            "status",
        ])
        _log_fiscal_document_status(document, previous_status, "Documento autorizado por gateway fiscal.", result)
        _try_create_accounting_event(document)
        return

    if status == "REJECTED":
        previous_status = document.status
        msg = result.get("error_message") or "Rechazado por gateway fiscal"
        document.access_key = access_key
        document.xml_signed = xml_signed
        document.sri_response = msg
        document.status = StatusEnum.REJECTED
        document.save(update_fields=["access_key", "xml_signed", "sri_response", "status"])
        _log_fiscal_document_status(document, previous_status, f"SRI RECHAZADO: {msg}", result)
        raise ValidationError(f"SRI RECHAZADO: {msg}")

    if status in {"RECEIVED", "RETRY_SCHEDULED"}:
        previous_status = document.status
        if status == "RETRY_SCHEDULED":
            default_message = (
                "B22 programo un reintento automatico porque el SRI no respondio a tiempo."
            )
        else:
            default_message = "Recibido por gateway fiscal, pendiente de autorizacion"
        document.access_key = access_key
        document.xml_signed = xml_signed
        document.sri_response = result.get("error_message") or default_message
        document.status = StatusEnum.SENT
        document.save(update_fields=["access_key", "xml_signed", "sri_response", "status"])
        _log_fiscal_document_status(document, previous_status, document.sri_response, result)
        return

    if status == "ERROR":
        msg = result.get("error_message") or "Error del gateway fiscal"
        document.access_key = access_key
        document.xml_signed = xml_signed
        document.sri_response = msg
        document.save(update_fields=["access_key", "xml_signed", "sri_response"])
        raise ValidationError(f"Error B22: {msg}")

    document.access_key = access_key
    document.sri_response = result.get("error_message") or f"Estado B22 desconocido: {status or 'N/A'}"
    document.save(update_fields=["access_key", "sri_response"])
    raise ValidationError(document.sri_response)
