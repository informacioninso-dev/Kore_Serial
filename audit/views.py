from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView, View

from core.mixins import ModulePermissionMixin

from .models import (
    AuditClosure, AuditExecution, AuditFinding, AuditPlan, AuditPlanStatus,
    AuditSchedule, AuditScheduleStatus, AuditedProcess, FindingType,
)
from .services import auto_create_nc_from_finding, mark_schedule_completed, mark_schedule_in_progress


# ─── Dashboard ────────────────────────────────────────────────────────────────

class AuditDashboardView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    permission_required = "audit.view_auditplan"
    template_name = "audit/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()

        # ── 1 query por tabla en vez de múltiples .count() ────────────
        plan_stats = AuditPlan.objects.aggregate(
            total_plans=Count("id"),
            active_plans=Count("id", filter=Q(status=AuditPlanStatus.APPROVED)),
        )
        ctx.update(plan_stats)

        schedules = AuditSchedule.objects.all()
        sched_stats = schedules.aggregate(
            total_scheduled=Count("id"),
            completed=Count("id", filter=Q(status=AuditScheduleStatus.COMPLETED)),
            in_progress=Count("id", filter=Q(status=AuditScheduleStatus.IN_PROGRESS)),
            overdue=Count("id", filter=Q(
                planned_date__lt=today,
                status__in=[AuditScheduleStatus.PLANNED, AuditScheduleStatus.IN_PROGRESS],
            )),
        )
        ctx.update(sched_stats)

        findings = AuditFinding.objects.all()
        finding_stats = findings.aggregate(
            total_findings=Count("id"),
            major_nc=Count("id", filter=Q(finding_type=FindingType.MAJOR_NC)),
            minor_nc=Count("id", filter=Q(finding_type=FindingType.MINOR_NC)),
            observations=Count("id", filter=Q(finding_type=FindingType.OBSERVATION)),
        )
        ctx.update(finding_stats)

        ctx["recent_schedules"] = (
            schedules
            .select_related("plan", "auditor")
            .order_by("-planned_date")[:8]
        )
        ctx["overdue_list"] = (
            schedules.filter(
                planned_date__lt=today,
                status__in=[AuditScheduleStatus.PLANNED, AuditScheduleStatus.IN_PROGRESS],
            )
            .select_related("plan", "auditor")
            .order_by("planned_date")[:5]
        )
        ctx["plans"] = AuditPlan.objects.order_by("-year")[:5]
        return ctx


# ─── Planes ───────────────────────────────────────────────────────────────────

class AuditPlanListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    permission_required = "audit.view_auditplan"
    model = AuditPlan
    template_name = "audit/plan_list.html"
    context_object_name = "plans"
    paginate_by = 20
    ordering = ["-year", "name"]

    def get_paginate_by(self, queryset):
        try:
            per_page = int(self.request.GET.get("per_page", 20))
            if per_page in (20, 50, 100):
                return per_page
        except (ValueError, TypeError):
            pass
        return 20

    def get_queryset(self):
        qs = AuditPlan.objects.select_related("approved_by").order_by("-year", "name")
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        year = self.request.GET.get("year", "").strip()

        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(scope__icontains=q))
        if status:
            qs = qs.filter(status=status)
        if year:
            try:
                qs = qs.filter(year=int(year))
            except (TypeError, ValueError):
                pass
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = AuditPlanStatus.choices
        ctx["q"] = self.request.GET.get("q", "")
        ctx["sel_status"] = self.request.GET.get("status", "")
        ctx["sel_year"] = self.request.GET.get("year", "")
        ctx["per_page"] = self.get_paginate_by(None)
        return ctx


class AuditPlanCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "audit.add_auditplan"
    template_name = "audit/plan_form.html"

    def get(self, request):
        return render(request, self.template_name, {
            "process_choices": AuditedProcess.choices,
            "current_year": timezone.now().year,
        })

    def post(self, request):
        name = request.POST.get("name", "").strip()
        year = request.POST.get("year", "").strip()
        scope = request.POST.get("scope", "").strip()
        if not name or not year:
            messages.error(request, "Nombre y año son obligatorios.")
            return redirect("audit:plan_create")
        plan = AuditPlan.objects.create(
            name=name,
            year=int(year),
            scope=scope,
            notes=request.POST.get("notes", ""),
            created_by=request.user,
            updated_by=request.user,
        )
        messages.success(request, f"Plan '{plan.name}' creado.")
        return redirect("audit:plan_detail", pk=plan.pk)


class AuditPlanDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "audit.view_auditplan"
    model = AuditPlan
    template_name = "audit/plan_detail.html"
    context_object_name = "plan"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["schedules"] = (
            self.object.schedules
            .select_related("auditor")
            .order_by("planned_date")
        )
        ctx["process_choices"] = AuditedProcess.choices
        return ctx


class AuditPlanApproveView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "audit.change_auditplan"

    def post(self, request, pk):
        plan = get_object_or_404(AuditPlan, pk=pk)
        if plan.status != AuditPlanStatus.DRAFT:
            messages.warning(request, "El plan ya fue aprobado.")
        else:
            plan.status = AuditPlanStatus.APPROVED
            plan.approved_by = request.user
            plan.approved_at = timezone.now()
            plan.updated_by = request.user
            plan.save(update_fields=["status", "approved_by", "approved_at", "updated_by", "updated_at"])
            messages.success(request, f"Plan '{plan.name}' aprobado.")
        return redirect("audit:plan_detail", pk=pk)


# ─── Auditoría Programada ────────────────────────────────────────────────────

class AuditScheduleCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "audit.add_auditschedule"
    template_name = "audit/schedule_form.html"

    def get(self, request, plan_pk):
        plan = get_object_or_404(AuditPlan, pk=plan_pk)
        from django.contrib.auth import get_user_model
        users = get_user_model().objects.filter(is_active=True).order_by("first_name", "last_name")
        return render(request, self.template_name, {
            "plan": plan,
            "process_choices": AuditedProcess.choices,
            "users": users,
        })

    def post(self, request, plan_pk):
        plan = get_object_or_404(AuditPlan, pk=plan_pk)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        auditor_id = request.POST.get("auditor")
        try:
            auditor = User.objects.get(pk=auditor_id)
        except User.DoesNotExist:
            auditor = request.user
        schedule = AuditSchedule.objects.create(
            plan=plan,
            process=request.POST.get("process", AuditedProcess.GENERAL),
            auditor=auditor,
            area_responsible=request.POST.get("area_responsible", ""),
            planned_date=request.POST.get("planned_date"),
            objective=request.POST.get("objective", ""),
            iso_clauses=request.POST.get("iso_clauses", ""),
            notes=request.POST.get("notes", ""),
            created_by=request.user,
            updated_by=request.user,
        )
        messages.success(request, f"Auditoría programada: {schedule.get_process_display()} — {schedule.planned_date}")
        return redirect("audit:plan_detail", pk=plan_pk)


class AuditScheduleDetailView(LoginRequiredMixin, ModulePermissionMixin, DetailView):
    permission_required = "audit.view_auditschedule"
    model = AuditSchedule
    template_name = "audit/schedule_detail.html"
    context_object_name = "schedule"

    def get_queryset(self):
        return AuditSchedule.objects.select_related("plan", "auditor")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.contrib.auth import get_user_model
        ctx["users"] = get_user_model().objects.filter(is_active=True).order_by("first_name", "last_name")
        return ctx


# ─── Ejecución ────────────────────────────────────────────────────────────────

class AuditExecutionCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "audit.add_auditexecution"

    def post(self, request, pk):
        schedule = get_object_or_404(AuditSchedule, pk=pk)
        if schedule.has_execution:
            return redirect("audit:execution_detail", pk=schedule.execution.pk)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        auditee_id = request.POST.get("auditee")
        try:
            auditee = User.objects.get(pk=auditee_id)
        except (User.DoesNotExist, TypeError, ValueError):
            auditee = request.user
        execution = AuditExecution.objects.create(
            schedule=schedule,
            actual_date=request.POST.get("actual_date") or timezone.localdate(),
            auditor=request.user,
            auditee=auditee,
            opening_notes=request.POST.get("opening_notes", ""),
            created_by=request.user,
            updated_by=request.user,
        )
        mark_schedule_in_progress(schedule, request.user)
        messages.success(request, "Auditoría iniciada. Registra los hallazgos.")
        return redirect("audit:execution_detail", pk=execution.pk)


class AuditExecutionDetailView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "audit.view_auditexecution"

    def get(self, request, pk):
        execution = get_object_or_404(
            AuditExecution.objects.select_related(
                "schedule", "schedule__plan", "auditor", "auditee"
            ),
            pk=pk,
        )
        findings = execution.findings.select_related("nc").order_by("finding_type", "created_at")
        try:
            closure = execution.closure
        except AuditClosure.DoesNotExist:
            closure = None
        from django.contrib.auth import get_user_model
        users = get_user_model().objects.filter(is_active=True).order_by("first_name", "last_name")
        return render(request, "audit/execution_detail.html", {
            "execution": execution,
            "findings": findings,
            "closure": closure,
            "finding_type_choices": FindingType.choices,
            "summary": execution.finding_summary,
            "users": users,
        })

    def post(self, request, pk):
        execution = get_object_or_404(AuditExecution, pk=pk)
        closing_notes = request.POST.get("closing_notes", "").strip()
        if closing_notes:
            execution.closing_notes = closing_notes
            execution.updated_by = request.user
            execution.save(update_fields=["closing_notes", "updated_by", "updated_at"])
            messages.success(request, "Notas de cierre guardadas.")
        return redirect("audit:execution_detail", pk=pk)


# ─── Hallazgo ─────────────────────────────────────────────────────────────────

class AuditFindingCreateView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "audit.add_auditfinding"

    def post(self, request, pk):
        execution = get_object_or_404(AuditExecution, pk=pk)
        finding_type = request.POST.get("finding_type", FindingType.OBSERVATION)
        description = request.POST.get("description", "").strip()
        if not description:
            messages.error(request, "La descripción del hallazgo es obligatoria.")
            return redirect("audit:execution_detail", pk=pk)

        finding = AuditFinding.objects.create(
            execution=execution,
            finding_type=finding_type,
            iso_clause=request.POST.get("iso_clause", ""),
            description=description,
            evidence=request.POST.get("evidence", ""),
            recommendation=request.POST.get("recommendation", ""),
            created_by=request.user,
            updated_by=request.user,
        )

        # Auto-crear NC si el hallazgo es NC Mayor o Menor
        if finding_type in (FindingType.MAJOR_NC, FindingType.MINOR_NC):
            try:
                nc = auto_create_nc_from_finding(finding, request.user)
                finding.nc = nc
                finding.save(update_fields=["nc", "updated_by", "updated_at"])
                messages.info(request, f"NC {nc.code} creada automáticamente desde el hallazgo.")
            except Exception as e:
                messages.warning(request, f"Hallazgo guardado, pero no se pudo crear NC automáticamente: {e}")

        messages.success(request, f"Hallazgo registrado: {finding.get_finding_type_display()}")
        return redirect("audit:execution_detail", pk=pk)


# ─── Cierre ───────────────────────────────────────────────────────────────────

class AuditClosureView(LoginRequiredMixin, ModulePermissionMixin, View):
    permission_required = "audit.add_auditclosure"

    def post(self, request, pk):
        execution = get_object_or_404(AuditExecution, pk=pk)
        if execution.has_closure:
            messages.warning(request, "Esta auditoría ya tiene un cierre registrado.")
            return redirect("audit:execution_detail", pk=pk)
        summary = request.POST.get("summary", "").strip()
        auditee_sign = request.POST.get("auditee_sign", "").strip()
        if not summary or not auditee_sign:
            messages.error(request, "El resumen y la firma del auditado son obligatorios.")
            return redirect("audit:execution_detail", pk=pk)
        follow_up = request.POST.get("follow_up_date") or None
        AuditClosure.objects.create(
            execution=execution,
            summary=summary,
            auditor_sign=request.user,
            auditee_sign=auditee_sign,
            signed_at=timezone.now(),
            follow_up_date=follow_up,
            created_by=request.user,
            updated_by=request.user,
        )
        mark_schedule_completed(execution.schedule, request.user)
        messages.success(request, "Auditoría cerrada formalmente. ISO 13485 §8.2.2 cumplido.")
        return redirect("audit:execution_detail", pk=pk)


# ─── Cancelar Auditoría ───────────────────────────────────────────────────────

class AuditScheduleCancelView(LoginRequiredMixin, ModulePermissionMixin, View):
    """Cancela una auditoría planificada que aún no haya iniciado."""
    permission_required = "audit.change_auditschedule"

    def post(self, request, pk):
        schedule = get_object_or_404(AuditSchedule, pk=pk)
        if schedule.status not in (AuditScheduleStatus.PLANNED,):
            messages.error(request, "Solo se pueden cancelar auditorías en estado Planificada.")
            return redirect("audit:schedule_detail", pk=pk)
        reason = request.POST.get("reason", "").strip()
        schedule.status = AuditScheduleStatus.CANCELLED
        schedule.updated_by = request.user
        schedule.save(update_fields=["status", "updated_by", "updated_at"])
        messages.success(request, f"Auditoría '{schedule.process}' cancelada. {reason}")
        return redirect("audit:dashboard")
