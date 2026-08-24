from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import View

from core.mixins import ModulePermissionMixin

from .models import ChangeControl, ChangeControlSignature, ChangeStatus, SignatureDecision
from .models import sumilla_de
from .signing import FirmaInvalida, firmar, significado_de


class ChangeControlListView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "changecontrol.view_changecontrol"
    template_name = "changecontrol/change_control_list.html"

    def get(self, request):
        qs = ChangeControl.objects.prefetch_related("signatures").order_by("-code")
        q = (request.GET.get("q") or "").strip()
        estado = (request.GET.get("estado") or "").strip()
        riesgo = (request.GET.get("riesgo") or "").strip()
        if q:
            qs = qs.filter(models.Q(code__icontains=q) | models.Q(title__icontains=q))
        if estado:
            qs = qs.filter(status=estado)
        if riesgo:
            qs = qs.filter(risk=riesgo)

        cambios = list(qs)
        return render(request, self.template_name, {
            "cambios": cambios,
            "estado_choices": ChangeStatus.choices,
            "riesgo_choices": [("BAJO", "Bajo"), ("MEDIO", "Medio"), ("ALTO", "Alto")],
            "q": q,
            "selected_estado": estado,
            "selected_riesgo": riesgo,
            "total": len(cambios),
            "sin_firmar": sum(1 for c in cambios if not c.esta_completo),
        })


class ChangeControlDetailView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "changecontrol.view_changecontrol"
    template_name = "changecontrol/change_control_detail.html"

    def _contexto(self, cambio, usuario=None):
        decisiones = []
        for decision in SignatureDecision:
            decisiones.append({
                "valor": decision.value,
                "etiqueta": decision.label,
                "significado": significado_de(decision.value),
                "firma": cambio.firma_vigente(decision.value),
            })
        return {
            "cambio": cambio,
            "decisiones": decisiones,
            "mi_sumilla": sumilla_de(usuario) if usuario is not None else "",
            "historial": cambio.signatures.select_related("signed_by", "revoked_by")
                                          .filter(revoked_at__isnull=False),
        }

    def get(self, request, code):
        cambio = get_object_or_404(ChangeControl, code=code)
        return render(request, self.template_name, self._contexto(cambio, request.user))

    def post(self, request, code):
        cambio = get_object_or_404(ChangeControl, code=code)
        destino = reverse("changecontrol:detail", kwargs={"code": cambio.code})
        accion = request.POST.get("action")

        if accion == "firmar":
            if not request.user.has_perm("changecontrol.sign_changecontrol") \
               and not request.user.is_superuser \
               and not request.user.groups.filter(name="admin").exists():
                messages.error(request, "No tienes permiso para firmar controles de cambio.")
                return redirect(destino)
            try:
                firma = firmar(
                    cambio,
                    request.POST.get("decision"),
                    request.user,
                    request.POST.get("password"),
                    comentario=request.POST.get("comment", ""),
                    request=request,
                )
            except FirmaInvalida as error:
                messages.error(request, error.messages[0])
            except (ValidationError, KeyError, ValueError) as error:
                detalle = error.messages[0] if hasattr(error, "messages") else str(error)
                messages.error(request, detalle)
            else:
                messages.success(
                    request,
                    f"Firmado: {firma.get_decision_display()} · {firma.signed_at:%d/%m/%Y %H:%M}",
                )
            return redirect(destino)

        if accion == "revocar":
            if not request.user.has_perm("changecontrol.revoke_changecontrolsignature") \
               and not request.user.is_superuser \
               and not request.user.groups.filter(name="admin").exists():
                messages.error(request, "No tienes permiso para revocar firmas.")
                return redirect(destino)
            firma = get_object_or_404(
                ChangeControlSignature, pk=request.POST.get("signature"), change_control=cambio,
            )
            try:
                firma.revocar(request.user, request.POST.get("reason", ""))
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                messages.success(request, "Firma revocada. La decision vuelve a quedar pendiente.")
            return redirect(destino)

        messages.error(request, "Accion no reconocida.")
        return redirect(destino)
