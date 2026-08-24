from django.contrib.auth import get_user_model
from django_tenants.test.cases import TenantTestCase

from tenants.models import TenantMembership


class ConfigurationAndUsersScreensTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Empresa de prueba"

    @staticmethod
    def get_test_tenant_domain():
        return "config.test.com"

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        self.user = get_user_model().objects.create_user(
            username="tenant.admin",
            password="StrongPass.2026",
            first_name="Tenant",
            last_name="Admin",
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.user,
            is_admin=True,
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_configuration_and_users_modules_render_for_tenant_admin(self):
        for url in [
            "/configuracion/",
            "/configuracion/empresa/",
            "/configuracion/unidades/",
            "/configuracion/bodegas/",
            "/configuracion/ubicaciones/",
            "/configuracion/sistema/",
            "/produccion/productos/",
            "/produccion/versiones/",
            "/produccion/lineas/",
            "/produccion/estaciones/",
            "/produccion/rutas/",
            "/produccion/pasos/",
            "/produccion/requerimientos/",
            "/produccion/equipos/",
            "/usuarios/",
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_configuration_dashboard_contains_mes_master_data(self):
        response = self.client.get("/configuracion/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Maestros de produccion")
        self.assertContains(response, "Productos")
        self.assertContains(response, "Versiones")
        self.assertContains(response, "Lineas")
        self.assertContains(response, "Estaciones")
        self.assertContains(response, "Rutas")
        self.assertContains(response, "Pasos")
        self.assertContains(response, "Requerimientos")
        self.assertContains(response, "Equipos")
