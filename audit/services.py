from django.utils import timezone
from .models import AuditSchedule, AuditScheduleStatus, AuditFinding, FindingType


def auto_create_nc_from_finding(finding: AuditFinding, user) -> "capa.NonConformity":
    """
    Crea una NonConformity en capa a partir de un hallazgo NC Mayor o Menor.
    """
    from capa.models import NonConformity, NonConformitySource, NCseverity

    severity_map = {
        FindingType.MAJOR_NC: NCseverity.HIGH,
        FindingType.MINOR_NC: NCseverity.MEDIUM,
    }
    execution = finding.execution
    schedule = execution.schedule
    process_label = schedule.get_process_display()

    nc = NonConformity.objects.create(
        title=f"[Auditoría {schedule.plan.year}] {process_label} — {finding.description[:120]}",
        description=(
            f"Hallazgo de auditoría interna — {finding.get_finding_type_display()}\n"
            f"Cláusula: {finding.iso_clause or 'N/A'}\n\n"
            f"Evidencia: {finding.evidence or '—'}\n\n"
            f"Recomendación: {finding.recommendation or '—'}"
        ),
        severity=severity_map.get(finding.finding_type, NCseverity.MEDIUM),
        source=NonConformitySource.INTERNAL_AUDIT,
        immediate_action="Pendiente de definir acción de contención.",
        discovered_by=user,
        discovered_at=timezone.now(),
        created_by=user,
        updated_by=user,
    )
    return nc


def mark_schedule_in_progress(schedule: AuditSchedule, user) -> None:
    if schedule.status == AuditScheduleStatus.PLANNED:
        schedule.status = AuditScheduleStatus.IN_PROGRESS
        schedule.updated_by = user
        schedule.save(update_fields=["status", "updated_by", "updated_at"])


def mark_schedule_completed(schedule: AuditSchedule, user) -> None:
    schedule.status = AuditScheduleStatus.COMPLETED
    schedule.updated_by = user
    schedule.save(update_fields=["status", "updated_by", "updated_at"])
