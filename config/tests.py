from django.test import RequestFactory, SimpleTestCase

from .views import PublicDashboardView


class PublicDashboardViewTests(SimpleTestCase):
    def test_public_dashboard_disables_tenant_navigation_modules(self):
        request = RequestFactory().get("/")
        response = PublicDashboardView.as_view()(request)

        self.assertFalse(response.context_data["modules"]["production"])
        self.assertFalse(response.context_data["modules"]["core"])
        self.assertFalse(response.context_data["is_tenant_admin"])
