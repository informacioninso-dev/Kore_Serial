"""
Módulo de Auditorías Internas — ISO 13485 §8.2.2

Flujo:
  AuditPlan → AuditSchedule → AuditExecution → AuditFinding(s) → AuditClosure
  Hallazgo tipo NC Mayor/Menor → crea NonConformity en capa automáticamente
"""
from django.conf import settings
from django.db import models
from django.utils import timezone
from core.models import AuditModel


class AuditedProcess(models.TextChoices):
    QUALITY      = "QUALITY",      "Calidad (inspecciones, planes QA, liberación de lote)"
    PRODUCTION   = "PRODUCTION",   "Producción (OP, BOM, rutas, batch record)"
    PROCUREMENT  = "PROCUREMENT",  "Adquisición y Recepción de MP"
    SALES        = "SALES",        "Ventas, Despacho y Facturación"
    RETURNS      = "RETURNS",      "Devoluciones y Logística Inversa"
    DESIGN       = "DESIGN",       "Diseño y Desarrollo"
    INVENTORY    = "INVENTORY",    "Inventario y Almacenamiento"
    CAPA         = "CAPA",         "NC/CAPA — No Conformidades y Acciones"
    GENERAL      = "GENERAL",      "SGC General"


class AuditPlanStatus(models.TextChoices):
    DRAFT    = "DRAFT",    "Borrador"
    APPROVED = "APPROVED", "Aprobado"
    CLOSED   = "CLOSED",   "Cerrado"


class AuditScheduleStatus(models.TextChoices):
    PLANNED     = "PLANNED",     "Planificada"
    IN_PROGRESS = "IN_PROGRESS", "En ejecución"
    COMPLETED   = "COMPLETED",   "Completada"
    CANCELLED   = "CANCELLED",   "Cancelada"


class FindingType(models.TextChoices):
    CONFORMANT  = "CONFORMANT",  "Conforme"
    OBSERVATION = "OBSERVATION", "Observación"
    MINOR_NC    = "MINOR_NC",    "No Conformidad Menor"
    MAJOR_NC    = "MAJOR_NC",    "No Conformidad Mayor"


# ─── Plan Anual de Auditorías ─────────────────────────────────────────────────

class AuditPlan(AuditModel):
    """
    Plan anual de auditorías internas.
    ISO 13485 §8.2.2 — debe cubrir todos los procesos del SGC al menos una vez al año.
    """
    name        = models.CharField("Nombre del plan", max_length=150)
    year        = models.PositiveSmallIntegerField("Año")
    scope       = models.TextField("Alcance general", help_text="Procesos y áreas incluidos en el plan.")
    status      = models.CharField("Estado", max_length=10, choices=AuditPlanStatus.choices, default=AuditPlanStatus.DRAFT)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_audit_plans", verbose_name="Aprobado por")
    approved_at = models.DateTimeField("Fecha de aprobación", null=True, blank=True)
    notes       = models.TextField("Notas", blank=True)

    class Meta:
        verbose_name = "Plan de auditoría"
        verbose_name_plural = "Planes de auditoría"
        ordering = ["-year", "name"]

    def __str__(self):
        return f"{self.name} ({self.year})"

    @property
    def total_schedules(self):
        return self.schedules.count()

    @property
    def completed_schedules(self):
        return self.schedules.filter(status=AuditScheduleStatus.COMPLETED).count()


# ─── Auditoría Programada ────────────────────────────────────────────────────

class AuditSchedule(AuditModel):
    """
    Auditoría individual programada dentro de un plan.
    """
    plan             = models.ForeignKey(AuditPlan, on_delete=models.CASCADE, related_name="schedules", verbose_name="Plan")
    process          = models.CharField("Proceso auditado", max_length=20, choices=AuditedProcess.choices)
    auditor          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="scheduled_audits", verbose_name="Auditor")
    area_responsible = models.CharField("Responsable del área", max_length=150, help_text="Nombre o cargo del responsable del área auditada.")
    planned_date     = models.DateField("Fecha planificada", db_index=True)
    objective        = models.TextField("Objetivo de la auditoría", help_text="Qué se busca verificar en esta auditoría.")
    iso_clauses      = models.CharField("Cláusulas ISO a verificar", max_length=200, blank=True, help_text="Ej: §7.5.1, §8.2.4")
    status           = models.CharField("Estado", max_length=15, choices=AuditScheduleStatus.choices, default=AuditScheduleStatus.PLANNED, db_index=True)
    notes            = models.TextField("Notas previas", blank=True)

    class Meta:
        verbose_name = "Auditoría programada"
        verbose_name_plural = "Auditorías programadas"
        ordering = ["planned_date"]

    def __str__(self):
        return f"{self.get_process_display()} — {self.planned_date} ({self.plan})"

    @property
    def has_execution(self):
        return hasattr(self, "execution")


# ─── Ejecución de Auditoría ───────────────────────────────────────────────────

class AuditExecution(AuditModel):
    """
    Registro de la ejecución real de la auditoría.
    """
    schedule      = models.OneToOneField(AuditSchedule, on_delete=models.CASCADE, related_name="execution", verbose_name="Auditoría programada")
    actual_date   = models.DateField("Fecha de ejecución")
    auditor       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="executed_audits", verbose_name="Auditor")
    auditee       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="audited_as", verbose_name="Auditado (responsable del área)")
    opening_notes = models.TextField("Notas de apertura", blank=True, help_text="Resumen de la reunión de apertura.")
    closing_notes = models.TextField("Notas de cierre", blank=True, help_text="Resumen de la reunión de cierre con el auditado.")

    class Meta:
        verbose_name = "Ejecución de auditoría"
        verbose_name_plural = "Ejecuciones de auditoría"

    def __str__(self):
        return f"Ejecución {self.schedule}"

    @property
    def has_closure(self):
        return hasattr(self, "closure")

    @property
    def finding_summary(self):
        findings = self.findings.all()
        return {
            "conformant":  findings.filter(finding_type=FindingType.CONFORMANT).count(),
            "observation": findings.filter(finding_type=FindingType.OBSERVATION).count(),
            "minor_nc":    findings.filter(finding_type=FindingType.MINOR_NC).count(),
            "major_nc":    findings.filter(finding_type=FindingType.MAJOR_NC).count(),
        }


# ─── Hallazgo ─────────────────────────────────────────────────────────────────

class AuditFinding(AuditModel):
    """
    Hallazgo individual de la auditoría.
    MAJOR_NC y MINOR_NC generan automáticamente una NonConformity en capa.
    """
    execution      = models.ForeignKey(AuditExecution, on_delete=models.CASCADE, related_name="findings", verbose_name="Ejecución")
    finding_type   = models.CharField("Tipo de hallazgo", max_length=15, choices=FindingType.choices)
    iso_clause     = models.CharField("Cláusula ISO referenciada", max_length=50, blank=True, help_text="Ej: ISO 13485 §7.5.3")
    description    = models.TextField("Descripción del hallazgo")
    evidence       = models.TextField("Evidencia objetiva", blank=True, help_text="Qué se observó, registros revisados, entrevistas realizadas.")
    recommendation = models.TextField("Recomendación", blank=True)
    nc             = models.ForeignKey("capa.NonConformity", on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_findings", verbose_name="NC vinculada")

    class Meta:
        verbose_name = "Hallazgo de auditoría"
        verbose_name_plural = "Hallazgos de auditoría"
        ordering = ["finding_type", "created_at"]

    def __str__(self):
        return f"{self.get_finding_type_display()} — {self.description[:60]}"


# ─── Cierre de Auditoría ──────────────────────────────────────────────────────

class AuditClosure(AuditModel):
    """
    Cierre formal de la auditoría.
    Requiere firma del auditor y del responsable del área.
    """
    execution        = models.OneToOneField(AuditExecution, on_delete=models.CASCADE, related_name="closure", verbose_name="Ejecución")
    summary          = models.TextField("Resumen ejecutivo", help_text="Conclusión general de la auditoría.")
    auditor_sign     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="audit_closures_signed", verbose_name="Firmado por auditor")
    auditee_sign     = models.CharField("Firma del auditado", max_length=150, help_text="Nombre completo del responsable del área que acepta los hallazgos.")
    signed_at        = models.DateTimeField("Fecha de cierre", default=timezone.now)
    follow_up_date   = models.DateField("Fecha de seguimiento", null=True, blank=True, help_text="Próxima verificación si quedaron hallazgos abiertos.")

    class Meta:
        verbose_name = "Cierre de auditoría"
        verbose_name_plural = "Cierres de auditoría"

    def __str__(self):
        return f"Cierre {self.execution}"
