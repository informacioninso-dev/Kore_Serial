"""
Verificacion de identidad para actos firmados (CC-2026-031).

Nacio dentro del control de cambios (CC-2026-027) y se extrajo aqui cuando la
FMA necesito lo mismo. Dos implementaciones de la misma comprobacion de
seguridad divergen: alguien corrige una y la otra se queda atras, y nadie se
entera hasta que importa.

Reglas que sostienen el mecanismo:

- Se autentica **al usuario de la sesion**, nunca a un usuario tecleado. La
  contrasena confirma identidad, no la sustituye; aceptar credenciales ajenas
  convertiria la pantalla en un modo de suplantacion consentida.
- Sin identidad completa no se firma. Un registro que diga "kore.dev aprobo" no
  identifica a nadie.
- La contrasena no se registra, no se guarda y no aparece en ningun mensaje.
"""
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError


class FirmaInvalida(ValidationError):
    """La identidad de quien firma no pudo verificarse."""


def ip_de(request):
    """IP de origen del acto, para el rastro de la firma."""
    if request is None:
        return None
    reenviada = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def verificar_identidad(usuario, password, exigir_identidad=True):
    """
    Comprueba que quien dice firmar es quien esta en la sesion.

    Devuelve el usuario verificado. Levanta `FirmaInvalida` si la sesion no es
    valida, si la contrasena no corresponde, o si la persona no tiene la
    identidad completa que un registro necesita para identificarla.
    """
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        raise FirmaInvalida("Debe iniciar sesion para firmar.")

    if exigir_identidad:
        from tenants.models import identidad_completa

        if not identidad_completa(usuario):
            raise FirmaInvalida(
                "Tu usuario no tiene la identidad completa (nombre, apellido, cedula "
                "y celular), asi que la firma no identificaria a nadie. Completala "
                "antes de firmar."
            )

    verificado = authenticate(username=usuario.get_username(), password=password or "")
    if verificado is None or verificado.pk != usuario.pk:
        raise FirmaInvalida("La contrasena no es correcta. No se registro ninguna firma.")

    return verificado


def sumilla_de(user):
    """
    Sumilla de una persona: inicial del primer nombre y primer apellido.

    "Francisco Bravo" -> "F. Bravo"
    "Francisco Javier Bravo Perez" -> "F. Bravo"

    Se toma el *primer* apellido a proposito: en Ecuador el apellido paterno va
    primero y es el que identifica.
    """
    nombre = (getattr(user, "first_name", "") or "").strip()
    apellido = (getattr(user, "last_name", "") or "").strip()
    if nombre and apellido:
        return f"{nombre.split()[0][0].upper()}. {apellido.split()[0]}"
    completo = (user.get_full_name() if hasattr(user, "get_full_name") else "") or ""
    partes = completo.split()
    if len(partes) >= 2:
        return f"{partes[0][0].upper()}. {partes[1]}"
    if partes:
        return partes[0]
    return ""
