"""
core/sri_client.py

Cliente HTTP para la API externa de SRI Ecuador.

Soporta dos contratos:
1. `legacy`: endpoints separados /firmar y /emitir
2. `b22`: gateway fiscal unificado vía /v1/comprobantes

Cuando settings.SRI_API_URL está configurado, Kore delega la operación
al servicio externo según el modo configurado. Cuando no está configurado,
el caller debe usar la implementación SOAP directa (sales/sri_service.py).

Uso desde sri_service.py:
    from core.sri_client import get_sri_client, SRIAPINotConfigured

    try:
        client = get_sri_client()
        client.sign(document)
    except SRIAPINotConfigured:
        # fallback a SOAP
        ...
"""
import base64
import logging
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class SRIAPINotConfigured(Exception):
    """Se lanza cuando SRI_API_URL no está configurado en settings."""


class SRIAPIError(ValidationError):
    """Error devuelto por la API externa de SRI."""


class SRINotFound(SRIAPIError):
    """El recurso no existe en la API (HTTP 404).

    Se distingue del resto de errores porque "no existe" suele ser una
    respuesta valida: p.ej. consultar un emisor que aun no se ha registrado.
    """


class SRIConflict(SRIAPIError):
    """El recurso ya existe en la API (HTTP 409).

    Se distingue porque suele tener arreglo: p.ej. si el integrador ya estaba
    creado, se recupera en vez de dejar a la empresa sin poder emitir.
    """


class SRIClient:
    """
    Cliente HTTP para la API externa de SRI.

    Todos los métodos tienen la misma firma que sales/sri_service.py
    para que el cambio sea transparente al llamador.
    """

    def __init__(self, base_url: str, timeout: int = 30, api_key: str = "", mode: str = ""):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        mode = (mode or "").strip().lower()
        if mode:
            self.mode = mode
        else:
            self.mode = "b22" if api_key else "legacy"

    def _headers(self) -> dict:
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    @staticmethod
    def _extract_error(body: dict) -> str:
        """Extrae el mensaje de error de la respuesta.

        B22 responde {"error": {"code", "message", ...}}; el modo legacy usa
        {"detail": ...} o {"error": "texto"}. Soporta ambos.
        """
        if not isinstance(body, dict):
            return ""
        err = body.get("error")
        if isinstance(err, dict):
            return err.get("message") or ""
        return err or body.get("detail") or ""

    def _post(self, path: str, payload: dict, idempotency_key: str = "") -> dict:
        try:
            import httpx
        except ImportError:
            raise SRIAPIError(
                "La librería 'httpx' no está instalada. "
                "Ejecuta: pip install httpx"
            )
        url = f"{self.base_url}{path}"
        logger.info(f"SRI API → POST {url}")
        headers = self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = str(idempotency_key)
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            body = {}
            try:
                body = e.response.json()
            except Exception:
                pass
            msg = self._extract_error(body) or str(e)
            logger.error(f"SRI API error {e.response.status_code}: {msg}")
            error = SRIConflict if e.response.status_code == 409 else SRIAPIError
            raise error(f"Error SRI API ({e.response.status_code}): {msg}")
        except httpx.TimeoutException:
            raise SRIAPIError(
                f"Timeout conectando a la API SRI ({self.timeout}s). "
                "Verifique que el servicio esté disponible."
            )
        except httpx.RequestError as e:
            raise SRIAPIError(
                f"No se pudo conectar a la API SRI: {e}. "
                f"URL: {url}"
            )

    def _get(self, path: str) -> dict:
        try:
            import httpx
        except ImportError:
            raise SRIAPIError("La librería 'httpx' no está instalada.")
        url = f"{self.base_url}{path}"
        try:
            response = httpx.get(url, headers=self._headers(), timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            # El 404 se marca aparte: "no existe" es una respuesta legitima
            # (ej. consultar un emisor aun no registrado), no un fallo.
            if e.response.status_code == 404:
                raise SRINotFound(f"No encontrado: {path}")
            raise SRIAPIError(f"Error SRI API ({e.response.status_code}): {e}")
        except httpx.RequestError as e:
            raise SRIAPIError(f"No se pudo conectar a la API SRI: {e}")

    def _patch(self, path: str, payload: dict) -> dict:
        try:
            import httpx
        except ImportError:
            raise SRIAPIError("La librería 'httpx' no está instalada.")
        url = f"{self.base_url}{path}"
        logger.info(f"SRI API → PATCH {url}")
        try:
            response = httpx.patch(url, json=payload, headers=self._headers(), timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            body = {}
            try:
                body = e.response.json()
            except Exception:
                pass
            msg = self._extract_error(body) or str(e)
            logger.error(f"SRI API error {e.response.status_code}: {msg}")
            raise SRIAPIError(f"Error SRI API ({e.response.status_code}): {msg}")
        except httpx.TimeoutException:
            raise SRIAPIError(f"Timeout conectando a la API SRI ({self.timeout}s).")
        except httpx.RequestError as e:
            raise SRIAPIError(f"No se pudo conectar a la API SRI: {e}. URL: {url}")

    # ── Operaciones principales ───────────────────────────────────────────────

    def sign(self, document) -> None:
        """
        En modo B22 emula la fase de firma para conservar el flujo actual
        de vistas, y delega la firma real al momento de emitir.
        En modo legacy usa /firmar.
        """
        if self.mode == "b22":
            StatusEnum = self._get_status_enum(document)
            document.xml_signed = document.xml_unsigned or ""
            document.status = StatusEnum.SIGNED
            document.save(update_fields=["xml_signed", "status"])
            logger.info(
                "Documento %s preparado para emision via B22",
                getattr(document, "full_number", document.pk),
            )
            return

        if not document.xml_unsigned:
            raise SRIAPIError("El documento no tiene XML generado.")

        from .models import CompanyConfig

        config = CompanyConfig.get()
        if not config:
            raise SRIAPIError("Configure los datos de la empresa.")

        result = self._post("/firmar", {
            "xml": document.xml_unsigned,
            "ambiente": config.environment,
            "ruc": config.ruc,
        })

        from .sri_client_helpers import apply_sign_result

        apply_sign_result(document, result)
        logger.info(f"Documento {getattr(document, 'full_number', document.pk)} firmado via API")

    def send(self, document) -> None:
        """
        Envía el documento al servicio externo y aplica la respuesta.
        """
        if self.mode == "b22":
            # Idempotency-Key estable por documento: si Kore reintenta la misma
            # emision, B22 devuelve el comprobante existente en vez de duplicarlo.
            idem = f"{document._meta.model_name}:{document.pk}"
            result = self._post(
                "/v1/comprobantes", self._build_b22_payload(document), idempotency_key=idem
            )
            from .sri_client_helpers import apply_b22_emit_result

            apply_b22_emit_result(document, result)
            return

        if not document.xml_signed:
            raise SRIAPIError("El documento debe estar firmado antes de enviar.")

        result = self._post("/emitir", {
            "xml_firmado": document.xml_signed,
            "clave_acceso": document.access_key,
            "ambiente": self._get_ambiente(document),
        })

        from .sri_client_helpers import apply_send_result
        apply_send_result(document, result)

    def fetch_status(self, document) -> dict:
        """
        Consulta el estado actual de un comprobante previamente enviado.
        Disponible para el gateway B22.
        """
        if self.mode != "b22":
            raise SRIAPIError(
                "La consulta de estado solo esta disponible con SRI_API_MODE=b22."
            )

        access_key = getattr(document, "access_key", "") or ""
        if not access_key:
            raise SRIAPIError("El documento no tiene clave de acceso para consultar en B22.")

        return self._get(f"/v1/comprobantes/{access_key}")

    def retry_pending(self, document) -> dict:
        """
        Solicita a B22 un reintento manual de un comprobante pendiente.
        """
        if self.mode != "b22":
            raise SRIAPIError(
                "El reintento manual solo esta disponible con SRI_API_MODE=b22."
            )

        access_key = getattr(document, "access_key", "") or ""
        if not access_key:
            raise SRIAPIError("El documento no tiene clave de acceso para reintentar en B22.")

        return self._post(f"/v1/comprobantes/{access_key}/retry", {})

    def void(self, document, reason: str = "") -> dict:
        """
        Anula un comprobante ya autorizado.
        """
        result = self._post("/anular", {
            "clave_acceso": document.access_key,
            "motivo": reason,
            "ambiente": self._get_ambiente(document),
        })
        return result

    def verify_ruc(self, ruc: str) -> dict:
        """
        Consulta el estado de un RUC en el SRI.
        Retorna dict con keys: valid (bool), razon_social (str), estado (str)
        """
        if self.mode == "b22":
            return self._get(f"/v1/ruc/{ruc}")
        return self._get(f"/ruc/{ruc}")

    def health(self) -> dict:
        """
        Verifica si la API externa y el SRI están disponibles.
        Retorna dict: { "api": "ok", "sri": "ok"|"degraded"|"down" }
        """
        return self._get("/health")

    def check_contingencia(self) -> bool:
        """
        Retorna True si el SRI está disponible, False si está en contingencia.
        """
        try:
            status = self.health()
            if self.mode == "b22":
                return status.get("status") == "ok"
            return status.get("sri") == "ok"
        except Exception:
            return False

    # ── Integradores: credencial por tenant (requiere scope admin) ────────────
    #
    # Cada tenant de Kore recibe su propia credencial en el gateway, limitada a
    # su RUC (allowed_issuers). Kore crea el integrador con la clave maestra al
    # aprovisionar, de modo que el cliente no toca la GUI del gateway.

    def create_integrator(self, *, name: str, allowed_issuers: list[str],
                          scopes: str = "emit,read") -> dict:
        """
        Crea un integrador acotado a los RUCs indicados.

        Devuelve IntegratorCreated, cuya api_key SOLO viene en esta respuesta:
        hay que guardarla al momento o se pierde (el gateway solo conserva su
        hash). Requiere que este cliente use la clave maestra (scope admin).

        OJO: allowed_issuers vacio significa "sin restriccion" en el gateway,
        es decir, podria emitir con cualquier RUC. Se exige no vacio.
        """
        self._require_b22("Crear la credencial del gateway")
        rucs = [r.strip() for r in allowed_issuers if r and r.strip()]
        if not rucs:
            raise SRIAPIError(
                "Se requiere al menos un RUC en allowed_issuers: una credencial "
                "sin restriccion podria emitir con el RUC de otra empresa."
            )
        return self._post(
            "/v1/integradores",
            {"name": name, "scopes": scopes, "allowed_issuers": rucs},
        )

    def rotate_integrator_key(self, integrator_id: int) -> dict:
        """Genera una credencial nueva para el integrador e invalida la anterior."""
        self._require_b22("Rotar la credencial del gateway")
        return self._post(f"/v1/integradores/{integrator_id}/rotate", {})

    def find_integrator(self, name: str) -> dict | None:
        """
        Busca un integrador por nombre exacto; None si no hay.

        Sirve para recuperarse cuando el gateway ya tiene el integrador pero
        Kore perdio su credencial: crear otro daria 409 y dejaria a la empresa
        sin poder emitir.
        """
        self._require_b22("Consultar los integradores del gateway")
        datos = self._get("/v1/integradores") or {}
        for integrador in datos.get("items") or []:
            if (integrador.get("name") or "") == name:
                return integrador
        return None

    # ── Emisor y certificado (solo B22) ───────────────────────────────────────
    #
    # Permiten que el cliente suba su certificado desde Kore, sin conocer el
    # gateway: Kore valida y registra el .p12 contra B22 por detrás. El .p12
    # queda cifrado en reposo en B22 y NO se guarda en Kore.

    def _require_b22(self, operacion: str) -> None:
        if self.mode != "b22":
            raise SRIAPIError(
                f"{operacion} requiere el gateway fiscal B22. "
                "El modo legacy firma con el certificado local."
            )

    @staticmethod
    def _p12_to_base64(p12) -> str:
        """Acepta bytes, un archivo abierto o un FieldFile de Django."""
        if isinstance(p12, str):
            return p12  # ya viene en base64
        data = p12 if isinstance(p12, (bytes, bytearray)) else p12.read()
        return base64.b64encode(data).decode("ascii")

    def validate_certificate(self, ruc: str, p12, password: str) -> dict:
        """
        Valida un certificado .p12 SIN guardarlo. Sirve para dar feedback
        inmediato al usuario antes de confirmar la carga.

        Retorna: valid, subject, issuer, serial_number, valid_from, valid_to,
                 days_remaining, ruc_match, chain_certificates, warnings.
        """
        self._require_b22("Validar el certificado")
        return self._post(
            "/v1/emisores/validate",
            {
                "ruc": ruc,
                "p12_base64": self._p12_to_base64(p12),
                "password": password,
            },
        )

    def get_issuer(self, ruc: str) -> dict | None:
        """Devuelve el emisor registrado en el gateway, o None si no existe."""
        self._require_b22("Consultar el emisor")
        try:
            return self._get(f"/v1/emisores/{ruc}")
        except SRINotFound:
            return None

    def register_issuer(self, *, ruc: str, legal_name: str, address: str,
                        p12, password: str, trade_name: str = "",
                        special_taxpayer: str = "", obligated_accounting: bool = True,
                        environment: str = "1") -> dict:
        """
        Da de alta el emisor con su certificado. environment: "1"=pruebas, "2"=produccion.
        """
        self._require_b22("Registrar el emisor")
        return self._post(
            "/v1/emisores",
            {
                "ruc": ruc,
                "legal_name": legal_name,
                "trade_name": trade_name or "",
                "address": address,
                "special_taxpayer": special_taxpayer or "",
                "obligated_accounting": obligated_accounting,
                "environment": environment,
                "p12_base64": self._p12_to_base64(p12),
                "password": password,
            },
        )

    def rotate_certificate(self, ruc: str, p12, password: str) -> dict:
        """Reemplaza el certificado de un emisor ya registrado."""
        self._require_b22("Rotar el certificado")
        return self._patch(
            f"/v1/emisores/{ruc}",
            {"p12_base64": self._p12_to_base64(p12), "password": password},
        )

    def upsert_issuer(self, *, ruc: str, legal_name: str, address: str,
                      p12, password: str, **extra) -> dict:
        """
        Registra el emisor si no existe; si ya existe, solo rota su certificado.
        Es lo que necesita la pantalla de Configuración: el usuario sube su .p12
        sin tener que saber si es la primera vez o un reemplazo.
        """
        self._require_b22("Configurar el emisor")
        if self.get_issuer(ruc) is None:
            return self.register_issuer(
                ruc=ruc, legal_name=legal_name, address=address,
                p12=p12, password=password, **extra
            )
        return self.rotate_certificate(ruc, p12, password)

    # ── Helpers privados ──────────────────────────────────────────────────────

    @staticmethod
    def _get_ambiente(document) -> str:
        try:
            from core.models import CompanyConfig
            config = CompanyConfig.get()
            return config.environment if config else "1"
        except Exception:
            return "1"

    @staticmethod
    def _get_status_enum(document):
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

    def _build_b22_payload(self, document) -> dict:
        """
        Arma el cuerpo de /v1/comprobantes.

        Dos formas, segun donde este el certificado:

        - Emisor registrado (lo normal): el .p12 ya vive cifrado en la boveda
          del gateway y aqui solo se lo referencia por RUC. El material de
          firma no viaja en cada factura ni hace falta guardarlo en Kore.
        - Instalacion legada: todavia hay un .p12 local, asi que se manda
          inline. Se mantiene para no romper a quien aun no ha vuelto a subir
          su certificado; deja de usarse en cuanto lo hace.

        Si no hay ninguno de los dos, se avisa aqui: referenciar un emisor que
        el gateway no conoce solo consigue un 422 sin pistas para el usuario.
        """
        from core.models import CompanyConfig

        config = CompanyConfig.get()
        if not config:
            raise SRIAPIError("Configure los datos de la empresa.")

        doc_type, doc_payload = self._build_document_payload(document)
        payload = {
            "type": doc_type,
            "environment": config.environment,
            "document": doc_payload,
        }

        if config.certificate_file:
            payload["certificate"] = self._build_certificate_payload(config)
            payload["issuer"] = self._build_issuer_payload(config)
        elif config.has_b22_credentials:
            # La credencial se crea al registrar el certificado (b22_service),
            # asi que tenerla implica que el emisor ya existe en la boveda.
            payload["issuer_ruc"] = config.ruc
            payload["establishment"] = config.establishment_code
            payload["emission_point"] = config.emission_point
        else:
            raise SRIAPIError(
                "No hay certificado digital registrado. Súbalo en "
                "Configuración › Empresa antes de emitir."
            )

        return payload

    def _build_certificate_payload(self, config) -> dict:
        if not config.certificate_file:
            raise SRIAPIError("No hay certificado digital configurado.")
        if not config.certificate_password:
            raise SRIAPIError("No se ha configurado la contraseña del certificado.")

        try:
            config.certificate_file.open("rb")
            p12_bytes = config.certificate_file.read()
        finally:
            try:
                config.certificate_file.close()
            except Exception:
                pass

        if not p12_bytes:
            raise SRIAPIError("El certificado digital está vacío.")

        return {
            "p12_base64": base64.b64encode(p12_bytes).decode("utf-8"),
            "password": config.certificate_password,
        }

    @staticmethod
    def _build_issuer_payload(config) -> dict:
        return {
            "ruc": config.ruc,
            "legal_name": config.legal_name,
            "trade_name": config.trade_name or "",
            "address": config.address,
            "establishment": config.establishment_code,
            "emission_point": config.emission_point,
            "special_taxpayer": config.special_taxpayer or "",
            "obligated_accounting": bool(config.obligated_accounting),
        }

    def _build_document_payload(self, document) -> tuple[str, dict]:
        model_name = document._meta.model_name
        if model_name == "saleinvoice":
            return "FACTURA", self._build_invoice_document(document)
        if model_name == "creditnote":
            return "NOTA_CREDITO", self._build_credit_note_document(document)
        if model_name == "guiaremision":
            return "GUIA_REMISION", self._build_guia_document(document)
        if model_name == "supplierretention":
            return "RETENCION", self._build_retention_document(document)
        if model_name == "purchaseliquidation":
            return "LIQUIDACION", self._build_liquidation_document(document)
        raise SRIAPIError(f"Tipo de documento no soportado por B22: {model_name}")

    def _build_invoice_document(self, invoice) -> dict:
        lines = []
        for line in invoice.lines.select_related("product").all():
            lines.append({
                "code": line.product.code,
                "description": line.description,
                "quantity": self._decimal_str(line.quantity),
                "unit_price": self._decimal_str(line.unit_price),
                "discount": self._decimal_str(line.discount),
                "taxes": [{
                    "code": line.tax_code,
                    "rate_code": line.tax_rate_code,
                    "rate": self._decimal_str(line.tax_rate),
                    "base": self._decimal_str(line.subtotal),
                    "amount": self._decimal_str(line.tax_amount),
                }],
            })

        return {
            "sequential": invoice.sequential,
            "date": self._format_date(invoice.issue_date),
            "buyer": {
                "identification_type": invoice.buyer_identification_type,
                "identification": invoice.buyer_identification,
                "legal_name": invoice.buyer_legal_name,
                "address": invoice.buyer_address or "",
                "email": invoice.buyer_email or "",
                "phone": invoice.buyer_phone or "",
            },
            "lines": lines,
            "payments": [{
                "method": "20",
                "amount": self._decimal_str(invoice.total_amount),
                "term": 0,
                "time_unit": "dias",
            }],
            "subtotal_0": self._decimal_str(invoice.subtotal_no_tax),
            "subtotal_iva": self._decimal_str(invoice.subtotal_iva),
            "iva_amount": self._decimal_str(invoice.iva_amount),
            "total": self._decimal_str(invoice.total_amount),
        }

    def _build_credit_note_document(self, credit_note) -> dict:
        invoice = credit_note.invoice
        lines = []
        for line in credit_note.lines.select_related("product").all():
            lines.append({
                "code": line.product.code,
                "description": line.description,
                "quantity": self._decimal_str(line.quantity),
                "unit_price": self._decimal_str(line.unit_price),
                "discount": "0.00",
                "taxes": [{
                    "code": "2",
                    "rate_code": self._tax_rate_code(line.tax_rate),
                    "rate": self._decimal_str(line.tax_rate),
                    "base": self._decimal_str(line.subtotal),
                    "amount": self._decimal_str(line.tax_amount),
                }],
            })

        return {
            "sequential": credit_note.sequential,
            "date": self._format_date(credit_note.issue_date),
            "original_invoice": invoice.full_number,
            "original_invoice_date": self._format_date(invoice.issue_date),
            "modified_doc_code": "01",
            "reason": credit_note.reason,
            "buyer": {
                "identification_type": invoice.buyer_identification_type,
                "identification": invoice.buyer_identification,
                "legal_name": invoice.buyer_legal_name,
                "address": invoice.buyer_address or "",
                "email": invoice.buyer_email or "",
                "phone": invoice.buyer_phone or "",
            },
            "lines": lines,
        }

    def _build_guia_document(self, guia) -> dict:
        items = []
        for line in guia.lines.select_related("product").all():
            items.append({
                "code": line.product.code,
                "description": line.description,
                "quantity": self._decimal_str(line.quantity),
                "unit_price": "0.00",
                "discount": "0.00",
                "taxes": [],
            })

        return {
            "sequential": guia.sequential,
            "date": self._format_date(guia.issue_date),
            "transport_name": guia.carrier_legal_name,
            "transport_identification_type": guia.carrier_identification_type,
            "transport_ruc": guia.carrier_identification,
            "transport_plate": guia.vehicle_plate,
            "start_address": guia.origin_address,
            "transport_start_date": self._format_date(guia.transport_start_date),
            "transport_end_date": self._format_date(guia.transport_end_date),
            "end_address": guia.recipient_address,
            "transfer_reason": guia.transfer_reason,
            "route": guia.route or "",
            "buyer": {
                "identification_type": guia.recipient_identification_type,
                "identification": guia.recipient_identification,
                "legal_name": guia.recipient_legal_name,
                "address": guia.recipient_address,
                "email": "",
                "phone": "",
            },
            "items": items,
            "supporting_doc": guia.supporting_doc_number or "",
            "supporting_doc_type": guia.supporting_doc_type or "01",
            "supporting_doc_authorization": guia.supporting_doc_authorization or "",
            "supporting_doc_date": self._format_date(guia.supporting_doc_date) if guia.supporting_doc_date else None,
            "driver_name": guia.driver_name or "",
            "driver_identification": guia.driver_identification or "",
            "reference_order": getattr(guia.order, "code", "") if getattr(guia, "order_id", None) else "",
            "reference_dispatch": getattr(guia.dispatch, "code", "") if getattr(guia, "dispatch_id", None) else "",
        }

    def _build_retention_line(self, line) -> dict:
        """
        Mapea una linea de retencion de Kore al esquema 2.0.0 de B22.

        B22 separa dos bloques dentro del documento de sustento:
        - impuestoDocSustento: el IVA de la factura recibida (informativo).
        - retencion: la retencion aplicada.

        Kore solo guarda los datos de la retencion, asi que el IVA del sustento
        se deriva del monto base asumiendo tarifa 15% (el caso comun: retencion
        de renta sobre la base, o de IVA sobre el valor del impuesto).
        """
        IVA = Decimal("0.15")
        tax_code = (line.tax_code or "1")  # 1=Renta 2=IVA 6=ISD (codigo de la retencion)
        base = Decimal(str(line.base_amount or 0))

        if tax_code == "2":  # retencion de IVA: la base es el valor del IVA de la factura
            doc_tax_value = base
            doc_taxable_base = (base / IVA) if IVA else base
        else:  # renta/ISD: la base es la base imponible de la factura
            doc_taxable_base = base
            doc_tax_value = base * IVA
        doc_taxable_base = doc_taxable_base.quantize(Decimal("0.01"))
        doc_tax_value = doc_tax_value.quantize(Decimal("0.01"))

        return {
            # impuestoDocSustento (IVA de la factura de sustento):
            "code": "2",             # codImpuestoDocSustento: IVA
            "percentage_code": "4",  # 15%
            "base": self._decimal_str(doc_taxable_base),
            "tariff": "15",
            "tax_value": self._decimal_str(doc_tax_value),
            # retenciones (la retencion aplicada):
            "retention_tax_code": tax_code,
            "retention_code": line.retention_code,
            "retention_base": self._decimal_str(base),
            "percentage": self._decimal_str(line.percentage),
            "amount": self._decimal_str(line.retained_amount),
            # documento de sustento:
            "supporting_doc_type": line.supporting_doc_type,
            "supporting_doc_number": line.supporting_doc_number,
            "supporting_doc_date": self._format_date(line.supporting_doc_date),
            "supporting_doc_authorization": getattr(line, "supporting_doc_authorization", "") or "",
            "doc_total_sin_impuestos": self._decimal_str(doc_taxable_base),
            "doc_total": self._decimal_str(doc_taxable_base + doc_tax_value),
            "payment_method": "01",
        }

    def _build_retention_document(self, retention) -> dict:
        retentions = [self._build_retention_line(line) for line in retention.lines.all()]

        return {
            "sequential": retention.sequential,
            "date": self._format_date(retention.issue_date),
            "period": retention.fiscal_period,
            "supplier": {
                "identification_type": retention.supplier_identification_type,
                "identification": retention.supplier_identification,
                "legal_name": retention.supplier_legal_name,
                "address": retention.supplier_address or "",
                "email": retention.supplier_email or "",
                "phone": retention.supplier_phone or "",
            },
            "retentions": retentions,
        }

    def _build_liquidation_document(self, liquidation) -> dict:
        lines = []
        for line in liquidation.lines.all():
            lines.append({
                "code": line.code or "",
                "description": line.description,
                "quantity": self._decimal_str(line.quantity),
                "unit_price": self._decimal_str(line.unit_price),
                "discount": self._decimal_str(line.discount),
                "taxes": [{
                    "code": line.tax_code,
                    "rate_code": line.tax_rate_code,
                    "rate": self._decimal_str(line.tax_rate),
                    "base": self._decimal_str(line.subtotal),
                    "amount": self._decimal_str(line.tax_amount),
                }],
            })

        return {
            "sequential": liquidation.sequential,
            "date": self._format_date(liquidation.issue_date),
            "seller": {
                "identification_type": liquidation.seller_identification_type,
                "identification": liquidation.seller_identification,
                "legal_name": liquidation.seller_legal_name,
                "address": liquidation.seller_address or "",
                "email": liquidation.seller_email or "",
                "phone": liquidation.seller_phone or "",
            },
            "lines": lines,
            "payments": [{
                "method": "20",
                "amount": self._decimal_str(liquidation.total_amount),
                "term": 0,
                "time_unit": "dias",
            }],
        }

    @staticmethod
    def _format_date(value) -> str:
        if hasattr(value, "strftime"):
            return value.strftime("%d/%m/%Y")
        return str(value)

    @staticmethod
    def _decimal_str(value) -> str:
        if isinstance(value, Decimal):
            return format(value, "f")
        return format(Decimal(str(value)), "f")

    @staticmethod
    def _tax_rate_code(rate) -> str:
        rate_map = {
            Decimal("0.00"): "0",
            Decimal("12.00"): "2",
            Decimal("14.00"): "3",
            Decimal("15.00"): "4",
        }
        return rate_map.get(Decimal(str(rate)), "0")


# ── Factory ───────────────────────────────────────────────────────────────────

def _base_url() -> str:
    url = getattr(settings, "SRI_API_URL", None) or ""
    if not url:
        raise SRIAPINotConfigured(
            "SRI_API_URL no está configurado. "
            "Agrégalo en .env: SRI_API_URL=http://sri-api:8001"
        )
    return url


def get_sri_client() -> SRIClient:
    """
    Retorna un SRIClient para el tenant actual.

    La credencial se toma, en este orden:
    1. La del tenant (CompanyConfig.b22_api_key), acotada a su RUC en el
       gateway. Es la vía normal.
    2. SRI_API_KEY del .env, como respaldo para instalaciones de un solo
       emisor y para no romper las que ya existían.

    Preferir la del tenant es lo que garantiza el aislamiento: con una clave
    compartida, un tenant podría emitir con el RUC de otro.

    Lanza SRIAPINotConfigured si SRI_API_URL no está en settings.
    """
    api_key = ""
    try:
        from .models import CompanyConfig

        config = CompanyConfig.get()
        if config:
            api_key = config.b22_api_key
    except Exception:
        # Sin tenant resuelto o sin la tabla aún (p.ej. durante migraciones):
        # se cae al respaldo global.
        pass

    if not api_key:
        api_key = getattr(settings, "SRI_API_KEY", "")

    return SRIClient(
        base_url=_base_url(),
        timeout=getattr(settings, "SRI_API_TIMEOUT", 30),
        api_key=api_key,
        mode=getattr(settings, "SRI_API_MODE", ""),
    )


def get_sri_admin_client() -> SRIClient:
    """
    Cliente con la clave MAESTRA del gateway (scope admin).

    Solo para administrar integradores: crear la credencial de un tenant o
    rotarla. Nunca debe usarse para emitir, porque la clave maestra no está
    acotada a un RUC.

    La clave vive únicamente en el .env del servidor (SRI_API_ADMIN_KEY), no en
    la base de datos ni por tenant.
    """
    admin_key = getattr(settings, "SRI_API_ADMIN_KEY", "")
    if not admin_key:
        raise SRIAPINotConfigured(
            "SRI_API_ADMIN_KEY no está configurado. Es la clave maestra del "
            "gateway fiscal (scope admin) y se necesita para crear la "
            "credencial de cada empresa. Agrégala en .env."
        )
    return SRIClient(
        base_url=_base_url(),
        timeout=getattr(settings, "SRI_API_TIMEOUT", 30),
        api_key=admin_key,
        mode="b22",
    )
