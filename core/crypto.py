"""
core/crypto.py

Cifrado en reposo de secretos del tenant (hoy: la API key de B22).

Usa Fernet (AES-128-CBC + HMAC) con una clave derivada de KORE_SECRET_KEY, o
de SECRET_KEY si aquella no esta definida. Es el mismo enfoque que usa B22 en
su modulo crypto, para no tener dos criterios distintos en el mismo sistema.

Cambiar la clave invalida los secretos ya cifrados: habria que volver a
guardarlos. Por eso conviene definir KORE_SECRET_KEY aparte de SECRET_KEY, que
si suele rotarse.
"""
import base64
import hashlib
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class SecretKeyNotConfigured(RuntimeError):
    """No hay clave para cifrar/descifrar."""


def _fernet():
    from cryptography.fernet import Fernet

    raw = (getattr(settings, "KORE_SECRET_KEY", "") or getattr(settings, "SECRET_KEY", "")).strip()
    if not raw:
        raise SecretKeyNotConfigured(
            "Configure KORE_SECRET_KEY (o SECRET_KEY) para cifrar secretos."
        )
    # Aceptamos una clave Fernet valida tal cual; si no, la derivamos del
    # secreto (sha256 -> 32 bytes -> base64 url-safe).
    try:
        return Fernet(raw.encode("utf-8"))
    except Exception:
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
        return Fernet(derived)


def encrypt(texto: str) -> str:
    """Cifra un secreto. Cadena vacia entra y sale vacia."""
    if not texto:
        return ""
    return _fernet().encrypt(texto.encode("utf-8")).decode("ascii")


def decrypt(cifrado: str) -> str:
    """
    Descifra un secreto. Devuelve "" si el valor esta vacio o no se puede
    descifrar (p.ej. si cambio la clave), sin tumbar la peticion: el llamador
    lo tratara como "no configurado".
    """
    if not cifrado:
        return ""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(cifrado.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception):
        logger.warning(
            "No se pudo descifrar un secreto: la clave de cifrado cambio o el "
            "dato esta corrupto. Se tratara como no configurado."
        )
        return ""


def mask(secreto: str, visibles: int = 4) -> str:
    """Version enmascarada para mostrar en pantalla: 'b22_live_1a2b...ef90'."""
    if not secreto:
        return ""
    if len(secreto) <= visibles * 2:
        return "•" * len(secreto)
    return f"{secreto[:visibles]}{'•' * 8}{secreto[-visibles:]}"
