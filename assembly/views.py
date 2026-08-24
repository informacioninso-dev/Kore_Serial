from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import ListView

from core.mixins import ModulePermissionMixin

from .models import SerializedUnit, UnitStatus


class SerializedUnitListView(LoginRequiredMixin, ModulePermissionMixin, ListView):
    model = SerializedUnit
    template_name = "assembly/unit_list.html"
    context_object_name = "units"
    permission_required = "assembly.view_serializedunit"

    def get_queryset(self):
        queryset = SerializedUnit.objects.select_related("version__product")
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()

        if q:
            queryset = queryset.filter(
                Q(serial_number__icontains=q)
                | Q(version__code__icontains=q)
                | Q(version__name__icontains=q)
                | Q(version__product__code__icontains=q)
                | Q(version__product__name__icontains=q)
            )
        if status in UnitStatus.values:
            queryset = queryset.filter(status=status)
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset

    def get_paginate_by(self, queryset):
        try:
            per_page = int(self.request.GET.get("per_page", 20))
        except (TypeError, ValueError):
            return 20
        return per_page if per_page in (20, 50, 100) else 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["per_page"] = self.get_paginate_by(None)
        context["status_choices"] = UnitStatus.choices
        return context
