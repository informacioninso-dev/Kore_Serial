"""
core/b22_service.py

Orquesta el alta del emisor en el gateway fiscal desde Kore.

El objetivo es que el cliente de Kore suba su certificado desde su propia
pantalla y no sepa que existe un gateway detras. Aqui se resuelve lo que de
otro modo tendria que hacer a mano en la GUI de B22:

  1. Crear su credencial en el gateway, acotada a su RUC.
  2. Validar el .p12 y registrarlo (o rotarlo si ya habia uno).

Reparto de credenciales (verificado contra el gateway):

- /v1/emisores y /v1/integradores exigen scope 'admin'. Gestionar certificados
  es una operacion de administracion: la hace Kore con la clave maestra, en
  nombre del cliente. Por eso el cliente no necesita —ni debe tener— permisos
  de admin en el gateway.
- /v1/comprobantes exige scope 'emit' y ahi si se aplica allowed_issuers. Esa
  es la credencial del tenant: solo puede emitir, y solo con SU RUC.

Aislamiento: cada empresa recibe su propia credencial limitada a su RUC. Con
una credencial compartida, un tenant podria emitir con el RUC de otro.
"""
import logging

from django.core.exceptions import ValidationError

from .sri_client import (
    SRIAPIError,
    SRIAPINotConfigured,
    SRIConflict,
    get_sri_admin_client,
)

logger = logging.getLogger(__name__)


def _config_valida(config):
    faltan = [
        etiqueta
        for campo, etiqueta in (
            ("ruc", "RUC"),
            ("legal_name", "razón social"),
            ("address", "dirección"),
        )
        if not (getattr(config, campo, "") or "").strip()
    ]
    if faltan:
        raise ValidationError(
            "Complete los datos de la empresa antes de subir el certificado: "
            + ", ".join(faltan) + "."
        )


def validar_certificado(config, p12, password: str) -> dict:
    """
    Valida el certificado contra el gateway SIN guardarlo, para dar respuesta
    inmediata al usuario: vigencia, dias restantes y si el RUC coincide.
    """
    _config_valida(config)
    # /v1/emisores exige scope admin: lo hace Kore por el cliente.
    return get_sri_admin_client().validate_certificate(config.ruc, p12, password)


def _nombre_integrador(config) -> str:
    """
    Nombre del integrador en el gateway. Lleva el RUC porque el gateway exige
    nombre unico y dos empresas distintas pueden llamarse igual: sin el RUC, la
    segunda choca con un 409 y se queda sin poder facturar.
    """
    etiqueta = (config.trade_name or config.legal_name or "").strip()[:60]
    return f"Kore · {etiqueta} ({config.ruc})" if etiqueta else f"Kore · {config.ruc}"


def _guardar_credencial(config, respuesta) -> str:
    api_key = (respuesta or {}).get("api_key") or ""
    if not api_key:
        raise SRIAPIError("El gateway no devolvió la credencial del integrador.")

    config.b22_api_key = api_key                       # el setter la cifra
    config.b22_integrator_id = respuesta.get("id")
    config.save(update_fields=["b22_api_key_encrypted", "b22_integrator_id", "updated_at"])
    return api_key


def asegurar_credencial(config) -> str:
    """
    Devuelve la credencial del tenant en el gateway, creandola si aun no tiene.

    Se crea con la clave maestra y queda acotada al RUC de la empresa. La
    credencial solo viaja en la respuesta de creacion, asi que se cifra y se
    guarda de inmediato.

    Si el gateway ya tenia el integrador pero Kore no tiene la credencial
    (restauracion de un respaldo anterior al alta, por ejemplo), crear otro
    daria 409 y la empresa quedaria sin poder emitir para siempre. En ese caso
    se recupera el integrador y se le rota la clave: la anterior, que Kore ya
    no tiene, deja de servir.
    """
    if config.has_b22_credentials:
        return config.b22_api_key

    _config_valida(config)
    admin = get_sri_admin_client()
    nombre = _nombre_integrador(config)

    try:
        creado = admin.create_integrator(
            name=nombre,
            allowed_issuers=[config.ruc],   # acotado: solo puede emitir con SU RUC
            scopes="emit,read",             # sin admin: no puede tocar otros integradores
        )
    except SRIConflict:
        existente = admin.find_integrator(nombre)
        if not existente:
            raise
        logger.warning(
            "El integrador de %s ya existia en el gateway (id %s): se rota su "
            "credencial porque Kore no la conserva.",
            config.ruc, existente.get("id"),
        )
        creado = admin.rotate_integrator_key(existente["id"])

    api_key = _guardar_credencial(config, creado)
    logger.info(
        "Credencial de gateway lista para RUC %s (integrador %s)",
        config.ruc, creado.get("id"),
    )
    return api_key


def configurar_certificado(config, p12, password: str) -> dict:
    """
    Flujo completo de la pantalla de Configuracion: deja el certificado listo
    para emitir. Idempotente — el usuario sube su archivo sin tener que saber
    si es la primera vez o un reemplazo.

    Devuelve el resultado de la validacion, para mostrarle vigencia y RUC.
    """
    _config_valida(config)

    # 1. Validar primero: si el .p12 o la clave estan mal, no se toca nada.
    validacion = validar_certificado(config, p12, password)
    if not validacion.get("valid"):
        raise ValidationError("El certificado no es válido.")
    if validacion.get("ruc_match") is False:
        raise ValidationError(
            f"El certificado no corresponde al RUC {config.ruc} de la empresa."
        )

    # 2. Asegurar que la empresa tenga su credencial propia.
    asegurar_credencial(config)

    # 3. Registrar o rotar el certificado. Va con la clave maestra: el router
    #    de emisores exige scope admin, y la credencial del tenant solo emite.
    get_sri_admin_client().upsert_issuer(
        ruc=config.ruc,
        legal_name=config.legal_name,
        address=config.address or "",
        p12=p12,
        password=password,
        trade_name=config.trade_name or "",
        special_taxpayer=config.special_taxpayer or "",
        obligated_accounting=bool(config.obligated_accounting),
        environment=config.environment or "1",
    )
    logger.info("Certificado configurado en el gateway para RUC %s", config.ruc)
    return validacion


def estado_certificado(config) -> dict:
    """
    Estado que muestra la pantalla de Configuracion. Nunca lanza: si el gateway
    no responde, lo informa como parte del estado.

    Devuelve: configurado (bool), mensaje (str), detalle (dict|None).
    """
    if not (config and (config.ruc or "").strip()):
        return {"configurado": False, "mensaje": "Configure el RUC de la empresa.", "detalle": None}
    try:
        emisor = get_sri_admin_client().get_issuer(config.ruc)
    except SRIAPINotConfigured:
        return {"configurado": False, "mensaje": "El gateway fiscal no está configurado.", "detalle": None}
    except SRIAPIError as e:
        return {"configurado": False, "mensaje": f"No se pudo consultar el gateway: {e}", "detalle": None}

    if not emisor:
        return {"configurado": False, "mensaje": "Aún no ha subido su certificado.", "detalle": None}
    if not emisor.get("has_certificate"):
        return {"configurado": False, "mensaje": "La empresa está registrada, pero sin certificado.", "detalle": emisor}
    return {"configurado": True, "mensaje": "Certificado activo.", "detalle": emisor}
