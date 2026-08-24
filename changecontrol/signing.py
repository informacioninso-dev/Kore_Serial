"""
Estampado de firmas (CC-2026-027).

La regla que sostiene todo el mecanismo esta en `firmar`: se autentica **al
usuario de la sesion**, nunca a un usuario tecleado. La contrasena confirma
identidad, no la sustituye; aceptar credenciales ajenas convertiria la pantalla
de firma en un modo de suplantacion consentida.

La contrasena no se registra, no se guarda y no aparece en ningun mensaje.
"""
from django.core.exceptions import ValidationError

# La verificacion de identidad vive en core desde CC-2026-031: la comparten el
# control de cambios y la FMA, y dos copias de la misma comprobacion divergen.
from core.signatures import FirmaInvalida, ip_de as _ip_de, verificar_identidad

from .models import (ChangeControlSignature, SIGNATURE_MEANINGS, SignatureDecision,
                     sumilla_de)

__all__ = ["FirmaInvalida", "firmar", "significado_de"]


def significado_de(decision):
    """Texto que la persona declara al firmar esa decision."""
    return SIGNATURE_MEANINGS[SignatureDecision(decision)]


def firmar(change_control, decision, usuario, password, comentario="", request=None):
    """
    Estampa una firma sobre una decision, verificando identidad.

    Levanta `FirmaInvalida` si la contrasena no corresponde al usuario de la
    sesion. Levanta `ValidationError` si esa decision ya tiene firma vigente.
    """
    # Identidad y contrasena: una sola comprobacion, compartida con la FMA.
    verificar_identidad(usuario, password)

    sumilla = sumilla_de(usuario)
    nombre_completo = (usuario.get_full_name() or "").strip()
    cedula = usuario.profile.identification

    if change_control.firma_vigente(decision) is not None:
        raise ValidationError(
            "Esa decision ya tiene una firma vigente. Revoquela antes de firmar de nuevo."
        )

    return ChangeControlSignature.objects.create(
        change_control=change_control,
        decision=decision,
        signed_by=usuario,
        signed_name=nombre_completo,
        signed_initials=sumilla,
        signed_identification=cedula,
        meaning=significado_de(decision),
        comment=(comentario or "").strip(),
        source_ip=_ip_de(request),
    )
