"""
Firma electronica del control de cambios (CC-2026-027).

El expediente tecnico de cada cambio vive en git: versionado, inmutable y
validado por el CI. Lo que a git le falta es identidad verificada en el momento
de aprobar — cualquiera puede escribir "Aprobado por: Fulano" en un markdown.

Aqui se guarda lo otro: quien firmo, cuando, que significaba lo que firmaba y
desde donde. El expediente cita la referencia y las dos mitades se sostienen.

Vive en el esquema publico: un cambio del software se firma una vez, no una vez
por empresa cliente.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ChangeStatus(models.TextChoices):
    """Estados del SOP-SW-001 seccion 4."""
    PROPUESTO = "PROPUESTO", "Propuesto"
    APROBADO = "APROBADO", "Aprobado"
    EN_DESARROLLO = "EN_DESARROLLO", "En desarrollo"
    EN_PRUEBAS = "EN_PRUEBAS", "En pruebas"
    LISTO_PARA_DEPLOY = "LISTO_PARA_DEPLOY", "Listo para deploy"
    DESPLEGADO = "DESPLEGADO", "Desplegado"
    CERRADO = "CERRADO", "Cerrado"
    RECHAZADO = "RECHAZADO", "Rechazado"


class ChangeRisk(models.TextChoices):
    BAJO = "BAJO", "Bajo"
    MEDIO = "MEDIO", "Medio"
    ALTO = "ALTO", "Alto"


class SignatureDecision(models.TextChoices):
    """
    Las cuatro decisiones de la plantilla de expediente.

    El texto largo de cada una es el *significado* de la firma: lo que la
    persona declara al firmar. Se congela en cada firma, porque si manana se
    reescribe aqui, las firmas viejas no pueden cambiar de sentido solas.
    """
    REQUISITO = "REQUISITO", "Requisito aprobado"
    RIESGO_PRUEBAS = "RIESGO_PRUEBAS", "Riesgo y pruebas aprobados"
    RESULTADO = "RESULTADO", "Resultado funcional aceptado"
    DEPLOY = "DEPLOY", "Autorizacion de deploy"


SIGNATURE_MEANINGS = {
    SignatureDecision.REQUISITO: (
        "Declaro que el requisito y el alcance del cambio son correctos y estan "
        "autorizados para desarrollarse."
    ),
    SignatureDecision.RIESGO_PRUEBAS: (
        "Declaro que revise la clasificacion de riesgo, la suficiencia de las "
        "pruebas y las desviaciones registradas, y que las acepto."
    ),
    SignatureDecision.RESULTADO: (
        "Declaro que probe el resultado funcional del cambio y que cumple lo "
        "solicitado."
    ),
    SignatureDecision.DEPLOY: (
        "Autorizo el despliegue de este cambio al ambiente objetivo."
    ),
}


class ChangeControl(models.Model):
    """
    Un cambio del registro maestro, reflejado en Kore para poder firmarlo.

    No es la fuente de verdad del expediente: se alimenta de `register.csv` con
    el comando `sync_change_controls`. Capturarlo a mano aqui garantizaria que
    se desincronice del repositorio el primer dia.
    """
    code = models.CharField("Codigo", max_length=15, unique=True)
    title = models.CharField("Titulo", max_length=200)
    areas = models.CharField("Areas", max_length=200, blank=True)
    risk = models.CharField("Riesgo", max_length=10, choices=ChangeRisk.choices)
    status = models.CharField(
        "Estado", max_length=20, choices=ChangeStatus.choices, db_index=True,
    )
    opened_on = models.DateField("Fecha de apertura")
    document_path = models.CharField("Expediente", max_length=300, blank=True)
    synced_at = models.DateTimeField("Ultima sincronizacion", auto_now=True)

    class Meta:
        verbose_name = "Control de cambio"
        verbose_name_plural = "Controles de cambio"
        ordering = ["-code"]
        permissions = [
            ("sign_changecontrol", "Puede firmar controles de cambio"),
            ("revoke_changecontrolsignature", "Puede revocar firmas"),
        ]

    def __str__(self):
        return f"{self.code} - {self.title}"

    def firma_vigente(self, decision):
        """Firma vigente de una decision, o None."""
        return self.signatures.filter(decision=decision, revoked_at__isnull=True).first()

    @property
    def firmas_vigentes(self):
        return self.signatures.filter(revoked_at__isnull=True)

    @property
    def esta_completo(self):
        """True cuando las cuatro decisiones tienen firma vigente."""
        firmadas = set(self.firmas_vigentes.values_list("decision", flat=True))
        return firmadas == {d.value for d in SignatureDecision}

    @property
    def decisiones_pendientes(self):
        firmadas = set(self.firmas_vigentes.values_list("decision", flat=True))
        return [d for d in SignatureDecision if d.value not in firmadas]


def sumilla_de(user):
    """
    Sumilla de una persona: inicial del primer nombre y primer apellido.

    "Francisco Bravo" -> "F. Bravo"
    "Francisco Javier Bravo Perez" -> "F. Bravo"

    Se toma el *primer* apellido a proposito: en Ecuador el apellido paterno va
    primero y es el que identifica. Si la persona no tiene nombre cargado
    devuelve vacio, y de eso se encarga quien firma: sin nombre no hay firma.
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


class ChangeControlSignature(models.Model):
    """
    Una firma electronica sobre una decision de un cambio.

    No se edita ni se borra. Corregir se hace revocando con motivo y firmando de
    nuevo: asi la historia queda completa en vez de reescrita. `save()` bloquea
    cualquier intento de alterar quien, cuando, que decision y con que
    significado se firmo.

    La contrasena que se pide al firmar no llega hasta aqui: se usa para
    verificar identidad contra el backend de autenticacion y se descarta.
    """
    change_control = models.ForeignKey(
        ChangeControl,
        on_delete=models.PROTECT,
        related_name="signatures",
        verbose_name="Cambio",
    )
    decision = models.CharField(
        "Decision", max_length=20, choices=SignatureDecision.choices,
    )
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="change_control_signatures",
        verbose_name="Firmado por",
    )
    signed_at = models.DateTimeField("Fecha de firma", default=timezone.now)
    # Identidad congelada en el momento de firmar. Si la persona cambia de
    # nombre despues, la firma tiene que seguir diciendo quien firmo, igual que
    # el significado.
    # El default vacio existe solo para migrar filas anteriores a este campo:
    # `signing.firmar` no deja crear una firma sin nombre ni sumilla.
    signed_name = models.CharField("Nombre al firmar", max_length=150, default="")
    signed_initials = models.CharField("Sumilla", max_length=60, default="")
    # El nombre puede repetirse entre dos personas; la cedula no. Es lo que
    # vuelve la firma indiscutible.
    signed_identification = models.CharField("Cedula al firmar", max_length=30, default="")
    meaning = models.TextField(
        "Significado",
        help_text="Lo que la persona declaro al firmar, congelado en ese momento.",
    )
    comment = models.TextField("Comentario", blank=True)
    source_ip = models.GenericIPAddressField("Origen", null=True, blank=True)

    revoked_at = models.DateTimeField("Fecha de revocacion", null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="change_control_revocations",
        verbose_name="Revocada por",
    )
    revoke_reason = models.TextField("Motivo de la revocacion", blank=True)

    # Campos que una vez creada la firma no pueden cambiar nunca.
    _INMUTABLES = (
        "change_control_id", "decision", "signed_by_id", "signed_at", "meaning",
        "signed_name", "signed_initials", "signed_identification",
    )

    class Meta:
        verbose_name = "Firma de control de cambio"
        verbose_name_plural = "Firmas de control de cambio"
        ordering = ["change_control__code", "decision", "-signed_at"]
        constraints = [
            # Una sola firma vigente por decision. Las revocadas pueden ser
            # varias: son el historial.
            models.UniqueConstraint(
                fields=["change_control", "decision"],
                condition=models.Q(revoked_at__isnull=True),
                name="uniq_firma_vigente_por_decision",
            ),
        ]

    def __str__(self):
        estado = "revocada" if self.revoked_at else "vigente"
        return f"{self.change_control.code} · {self.get_decision_display()} ({estado})"

    @property
    def esta_vigente(self):
        return self.revoked_at is None

    def clean(self):
        super().clean()
        if self.revoked_at and not (self.revoke_reason or "").strip():
            raise ValidationError(
                {"revoke_reason": "Revocar una firma exige indicar el motivo."}
            )

    def save(self, *args, **kwargs):
        if self.pk:
            anterior = ChangeControlSignature.objects.get(pk=self.pk)
            for campo in self._INMUTABLES:
                if getattr(anterior, campo) != getattr(self, campo):
                    raise ValidationError(
                        f"Una firma no se modifica: se intento cambiar '{campo}'. "
                        "Para corregir, revoque con motivo y firme de nuevo."
                    )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Una firma no se borra. Revoquela con motivo para dejar rastro."
        )

    def revocar(self, usuario, motivo):
        """Deja la firma sin efecto, conservandola como historial."""
        if not self.esta_vigente:
            raise ValidationError("Esta firma ya estaba revocada.")
        if not (motivo or "").strip():
            raise ValidationError("Revocar una firma exige indicar el motivo.")
        self.revoked_at = timezone.now()
        self.revoked_by = usuario
        self.revoke_reason = motivo.strip()
        self.save(update_fields=["revoked_at", "revoked_by", "revoke_reason"])
        return self
