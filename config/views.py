from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import RedirectView, TemplateView


class DashboardView(LoginRequiredMixin, RedirectView):
    pattern_name = "assembly:index"


class PublicDashboardView(TemplateView):
    template_name = "public_dashboard.html"
