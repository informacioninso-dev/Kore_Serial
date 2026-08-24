from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "assembly/dashboard.html"


class PublicDashboardView(TemplateView):
    template_name = "public_dashboard.html"
