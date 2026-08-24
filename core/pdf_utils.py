"""
core/pdf_utils.py
Utilidades centralizadas para generación de PDFs y Excels con logo de empresa.
"""
import hashlib
import io
import json
import os

from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.utils import timezone
from xhtml2pdf import pisa

from core.models import CompanyConfig


# Tope de filas para listados en PDF. xhtml2pdf cuesta ~6 ms por fila, asi que
# un listado sin recortar bloquea un worker durante minutos. Los Excel no usan
# este tope: openpyxl absorbe volumenes mucho mayores sin penalizacion.
PDF_ROW_LIMIT = 500


def limit_pdf_rows(queryset, context: dict, *, limit: int = PDF_ROW_LIMIT):
    """
    Recorta un listado para PDF y deja constancia en el propio documento.

    Un informe que omite filas sin decirlo es un registro enganoso: si hay
    recorte se anota en el contexto y el pie del PDF lo declara.
    """
    total = queryset.count()
    if total > limit:
        context["pdf_rows_total"] = total
        context["pdf_rows_limit"] = limit
    return queryset[:limit]


def _pdf_generation_context(context: dict, user=None) -> None:
    generated_at = timezone.now()
    is_authenticated = bool(user and getattr(user, "is_authenticated", False))
    generated_by = user if is_authenticated else None
    generated_by_name = "Sistema Kore (proceso automatico)"
    if generated_by is not None:
        full_name = (generated_by.get_full_name() or "").strip()
        generated_by_name = full_name or generated_by.get_username()

    context["now"] = generated_at
    context["generated_at"] = generated_at
    context["generated_by"] = generated_by
    context["generated_by_name"] = generated_by_name


def _append_pdf_generation_meta(html: str, context: dict) -> str:
    meta = render_to_string("core/_pdf_generation_meta.html", context)
    closing_index = html.lower().rfind("</body>")
    if closing_index < 0:
        return f"{html}{meta}"
    return f"{html[:closing_index]}{meta}{html[closing_index:]}"


# ── Link callback para xhtml2pdf ─────────────────────────────────────────────
def pdf_link_callback(uri, rel):
    """Convierte URLs /media/ y /static/ a rutas absolutas en disco para xhtml2pdf."""
    if uri.startswith(settings.MEDIA_URL):
        return os.path.join(settings.MEDIA_ROOT, uri[len(settings.MEDIA_URL):])
    if uri.startswith(settings.STATIC_URL):
        for d in getattr(settings, "STATICFILES_DIRS", []):
            candidate = os.path.join(d, uri[len(settings.STATIC_URL):])
            if os.path.isfile(candidate):
                return candidate
        static_root = getattr(settings, "STATIC_ROOT", None)
        if static_root:
            return os.path.join(static_root, uri[len(settings.STATIC_URL):])
    return uri


def render_pdf_buffer(template_name: str, context: dict, *, user=None, source_model: str = "", source_id: int = 0, source_code: str = "", data_snapshot: dict | None = None) -> io.BytesIO:
    """
    Renderiza un template como PDF y retorna un BytesIO (útil para adjuntos de email).
    Inyecta automáticamente `config` en el contexto.
    """
    context.setdefault("config", CompanyConfig.get())
    _pdf_generation_context(context, user)
    html = render_to_string(template_name, context)
    html = _append_pdf_generation_meta(html, context)
    buffer = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=buffer, link_callback=pdf_link_callback)
    buffer.seek(0)
    if user and source_model and source_id:
        register_report_emission(
            template_name=template_name,
            source_model=source_model,
            source_id=source_id,
            source_code=source_code,
            data_snapshot=data_snapshot or {},
            user=user,
        )
    return buffer


# ── Registro auditable de documentos emitidos ────────────────────────────────

def register_report_emission(
    *,
    template_name: str,
    source_model: str,
    source_id: int,
    source_code: str = "",
    data_snapshot: dict,
    user,
    template_version: str = "v1",
):
    """
    Registra la emisión de un documento en ReportRegistry con hash SHA-256.
    Llamar desde cualquier vista que genere un PDF auditable.

    Ejemplo:
        register_report_emission(
            template_name="quality/pdf_inspection.html",
            source_model="quality.QualityInspection",
            source_id=inspection.pk,
            source_code=f"INS-{inspection.pk}",
            data_snapshot={"lot": lot.lot_number, "result": inspection.result, ...},
            user=request.user,
        )
    """
    from core.models import ReportRegistry

    snapshot_json = json.dumps(data_snapshot, sort_keys=True, default=str)
    data_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()

    year = timezone.now().year
    with transaction.atomic():
        from core.db_locks import lock_series

        lock_series("report_registry", year)
        last = (
            ReportRegistry.objects
            .filter(document_code__startswith=f"DOC-{year}-")
            .order_by("-document_code")
            .values_list("document_code", flat=True)
            .first()
        )
        seq = int(last.split("-")[-1]) + 1 if last else 1
        doc_code = f"DOC-{year}-{seq:06d}"

        return ReportRegistry.objects.create(
            document_code=doc_code,
            template_name=template_name,
            template_version=template_version,
            source_model=source_model,
            source_id=source_id,
            source_code=source_code,
            data_snapshot=data_snapshot,
            data_hash=data_hash,
            emitted_by=user if (user and user.is_authenticated) else None,
        )


def render_pdf_response(
    template_name: str,
    context: dict,
    filename: str,
    *,
    user,
    source_model: str = "",
    source_id: int = 0,
    source_code: str = "",
    data_snapshot: dict | None = None,
    source=None,
) -> HttpResponse:
    """
    Renderiza un template como PDF y retorna HttpResponse.
    Si se proveen user + source_model + source_id, registra automáticamente
    la emisión en ReportRegistry.
    Si se pasa `source` (el objeto del documento), deja en el contexto la
    cadena de responsables (`signatories`) para el bloque de firmas comun.
    """
    if source is not None and "signatories" not in context:
        from core.responsibilities import build_signatories

        context["signatories"] = build_signatories(source)
    context.setdefault("config", CompanyConfig.get())
    _pdf_generation_context(context, user)
    html = render_to_string(template_name, context)
    html = _append_pdf_generation_meta(html, context)
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    pisa.CreatePDF(io.StringIO(html), dest=response, link_callback=pdf_link_callback)

    if user and getattr(user, "is_authenticated", False):
        register_report_emission(
            template_name=template_name,
            source_model=source_model or "core.GeneratedPDF",
            source_id=source_id or 0,
            source_code=source_code or filename[:60],
            data_snapshot=data_snapshot or {
                "filename": filename,
                "template": template_name,
            },
            user=user,
        )

    return response


# ── Logo para Excel ───────────────────────────────────────────────────────────
def get_logo_for_excel():
    """
    Retorna una instancia de openpyxl Image con el logo de empresa,
    o None si no está configurado o el archivo no existe.

    Uso:
        logo = get_logo_for_excel()
        if logo:
            logo.anchor = "A1"
            ws.add_image(logo)
    """
    try:
        from openpyxl.drawing.image import Image as XLImage
        config = CompanyConfig.get()
        if not config or not config.logo:
            return None
        logo_path = os.path.join(settings.MEDIA_ROOT, config.logo.name)
        if not os.path.isfile(logo_path):
            return None
        img = XLImage(logo_path)
        img.width = 80
        img.height = 80
        return img
    except Exception:
        return None


# ── Generación automática de números de lote ─────────────────────────────────

def auto_generate_lot_number(product, reception_date=None, tenant=None) -> str:
    """
    Genera un número de lote automático basado en la fórmula configurada en CompanyConfig.

    Variables disponibles en la fórmula:
      {PREFIX}      → product.lot_prefix o lot_default_prefix de CompanyConfig
      {CODE}        → product.code
      {YYYY}        → año 4 dígitos
      {YY}          → año 2 dígitos
      {MM}          → mes 2 dígitos
      {DD}          → día 2 dígitos
      {SEQ:04d}     → secuencial con ceros a la izquierda (ajustar dígitos)
      {SEQ}         → secuencial sin formato

    Ejemplo: {PREFIX}-{YYYYMM}-{SEQ:04d} → MP001-202605-0001
    """
    from django.utils import timezone
    from inventory.models import Lot

    config = CompanyConfig.get()
    formula = (config.lot_formula if config and config.lot_formula else "{PREFIX}-{YYYYMM}-{SEQ:04d}").strip()
    default_prefix = (config.lot_default_prefix if config and config.lot_default_prefix else "REC").strip()

    date = reception_date or timezone.localdate()
    prefix = (product.lot_prefix or default_prefix or "REC").strip().upper()

    # Calcular secuencial: buscar el último lote del producto en el año/mes actual
    year_str  = str(date.year)
    month_str = str(date.month).zfill(2)
    day_str   = str(date.day).zfill(2)
    yy_str    = year_str[-2:]
    yyyymm    = year_str + month_str
    yyyymmdd  = year_str + month_str + day_str

    # Construir prefijo fijo de la fórmula para buscar el último secuencial
    prefix_part = (
        formula
        .replace("{PREFIX}", prefix)
        .replace("{CODE}", product.code or "")
        .replace("{YYYY}", year_str)
        .replace("{YY}", yy_str)
        .replace("{MM}", month_str)
        .replace("{DD}", day_str)
        .replace("{YYYYMM}", yyyymm)
        .replace("{YYYYMMDD}", yyyymmdd)
    )
    # Quitar la parte del secuencial para buscar por prefijo
    import re
    prefix_search = re.sub(r'\{SEQ[^}]*\}', '', prefix_part).rstrip('-').rstrip('_').rstrip('/')

    # Obtener el último lote con ese prefijo para calcular el siguiente secuencial
    last = (
        Lot.objects
        .filter(product=product, lot_number__startswith=prefix_search)
        .order_by("-lot_number")
        .values_list("lot_number", flat=True)
        .first()
    )
    seq = 1
    if last:
        parts = re.split(r'[-_/]', last)
        for part in reversed(parts):
            if part.isdigit():
                seq = int(part) + 1
                break

    # Aplicar secuencial a la fórmula
    seq_match = re.search(r'\{SEQ(?::(\d+)d)?\}', formula)
    if seq_match:
        digits = int(seq_match.group(1)) if seq_match.group(1) else 4
        seq_str = str(seq).zfill(digits)
        formula = re.sub(r'\{SEQ(?::\d+d)?\}', seq_str, formula)

    lot_number = (
        formula
        .replace("{PREFIX}", prefix)
        .replace("{CODE}", product.code or "")
        .replace("{YYYY}", year_str)
        .replace("{YY}", yy_str)
        .replace("{MM}", month_str)
        .replace("{DD}", day_str)
        .replace("{YYYYMM}", yyyymm)
        .replace("{YYYYMMDD}", yyyymmdd)
    )
    return lot_number
