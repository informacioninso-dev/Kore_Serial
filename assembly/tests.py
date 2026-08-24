from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django_tenants.test.cases import TenantTestCase

from core.models import OperationalAuditEvent
from tenants.models import TenantMembership

from .models import AssembledProduct, ProductVersion, SerializedUnit, UnitStatus


class SerializedUnitTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Empresa de prueba"

    @staticmethod
    def get_test_tenant_domain():
        return "serial.test.com"

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        self.user = get_user_model().objects.create_user(username="operator", password="StrongPass.2026")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        permission = Permission.objects.get(codename="view_serializedunit", content_type__app_label="assembly")
        self.user.user_permissions.add(permission)
        self.product = AssembledProduct.objects.create(code="MODEL-X", name="Modelo X", created_by=self.user, updated_by=self.user)
        self.version = ProductVersion.objects.create(product=self.product, code="BASE", name="Base", created_by=self.user, updated_by=self.user)
        self.client.force_login(self.user)

    def create_unit(self, serial_number, status=UnitStatus.REGISTERED):
        return SerializedUnit.objects.create(
            version=self.version,
            serial_number=serial_number,
            status=status,
            created_by=self.user,
            updated_by=self.user,
        )

    def test_unit_is_individual_and_logs_its_registration(self):
        unit = self.create_unit("SER-0001")

        self.assertEqual(unit.serial_number, "SER-0001")
        self.assertEqual(unit.version.product, self.product)
        self.assertIsNotNone(unit.created_at)
        self.assertEqual(unit.created_by, self.user)
        event = OperationalAuditEvent.objects.get(document_code="SER-0001")
        self.assertEqual(event.action, "CREATE")
        self.assertEqual(event.actor, self.user)

    def test_list_requires_the_module_permission(self):
        self.create_unit("SER-0001")
        anonymous = Client()
        anonymous.defaults["HTTP_HOST"] = self.get_test_tenant_domain()
        response = anonymous.get("/ensamblaje/unidades/")
        self.assertEqual(response.status_code, 302)

        unprivileged = get_user_model().objects.create_user(username="viewer", password="StrongPass.2026")
        TenantMembership.objects.create(tenant=self.tenant, user=unprivileged, is_active=True)
        anonymous.force_login(unprivileged)
        response = anonymous.get("/ensamblaje/unidades/")
        self.assertEqual(response.status_code, 403)

    def test_list_filters_and_preserves_filters_in_pagination(self):
        self.create_unit("SER-0001", UnitStatus.COMPLETED)
        self.create_unit("SER-0002", UnitStatus.IN_PROCESS)

        response = self.client.get("/ensamblaje/unidades/", {"q": "0001", "status": UnitStatus.COMPLETED, "per_page": 50})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SER-0001")
        self.assertNotContains(response, "SER-0002")
        self.assertContains(response, 'name="q" value="0001"', html=False)
        self.assertContains(response, 'name="status" value="COMPLETED"', html=False)
        self.assertContains(response, 'value="50" selected', html=False)

    def test_pagination_preserves_all_list_filters(self):
        for index in range(21):
            self.create_unit(f"SER-{index:04}", UnitStatus.IN_PROCESS)

        response = self.client.get(
            "/ensamblaje/unidades/",
            {"q": "SER", "status": UnitStatus.IN_PROCESS, "per_page": 20},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pagina 1 de 2")
        self.assertContains(
            response,
            "?page=2&q=SER&status=IN_PROCESS&per_page=20",
            html=False,
        )
