# core/mixins.py
"""
Mixins de control de acceso reutilizables.
"""
from django.conf import settings
from django.contrib.auth.mixins import PermissionRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


def get_tenant_feature(request, feature: str) -> bool:
    """
    Devuelve True si el módulo `feature` está habilitado para el tenant actual.
    Fail-open: retorna True si el tenant no se puede determinar (esquema público, tests, etc.).
    """
    from tenants.models import TenantModule
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return True
    schema = getattr(tenant, 'schema_name', None)
    if schema == getattr(settings, 'PUBLIC_SCHEMA_NAME', 'public'):
        return True
    return TenantModule.is_enabled(tenant, feature)


class WMSRequiredMixin:
    """Bloquea la vista con 403 si el módulo 'wms' está desactivado para el tenant."""
    def dispatch(self, request, *args, **kwargs):
        if not get_tenant_feature(request, 'wms'):
            raise PermissionDenied("Módulo WMS no habilitado para esta empresa.")
        return super().dispatch(request, *args, **kwargs)


class RecallModuleRequiredMixin:
    """Bloquea la vista con 403 si recall_module está desactivado para el tenant."""
    def dispatch(self, request, *args, **kwargs):
        if not get_tenant_feature(request, 'recall_module'):
            raise PermissionDenied("Módulo de retiros de mercado no habilitado para esta empresa.")
        return super().dispatch(request, *args, **kwargs)


class ISORequiredMixin:
    """Bloquea la vista con 403 si manufacturing_qa está desactivado para el tenant."""
    def dispatch(self, request, *args, **kwargs):
        if not get_tenant_feature(request, 'manufacturing_qa'):
            raise PermissionDenied("Módulo de QA de producción no habilitado para esta empresa.")
        return super().dispatch(request, *args, **kwargs)


class MigrationHubRequiredMixin:
    """Bloquea la vista si el hub de migración no está habilitado."""

    def dispatch(self, request, *args, **kwargs):
        if not get_tenant_feature(request, "migration_hub"):
            raise PermissionDenied("Hub de migración no habilitado para esta empresa.")
        return super().dispatch(request, *args, **kwargs)


class ModulePermissionMixin(PermissionRequiredMixin):
    """
    Extiende PermissionRequiredMixin para redirigir con un mensaje
    cuando el usuario no tiene permisos en vez de mostrar 403.
    Los superusuarios y miembros del grupo 'admin' tienen acceso total.
    """
    raise_exception = True

    def has_permission(self):
        user = self.request.user
        if user.is_superuser or user.groups.filter(name="admin").exists():
            return True
        tenant = getattr(self.request, "tenant", None)
        if tenant is not None:
            from tenants.models import TenantMembership

            if TenantMembership.objects.filter(
                tenant=tenant,
                user=user,
                is_admin=True,
                is_active=True,
            ).exists():
                return True
        return super().has_permission()


class TenantAdminRequiredMixin(UserPassesTestMixin):
    """Allow technical system information only to tenant administrators."""

    raise_exception = True

    def test_func(self):
        user = self.request.user
        if user.is_superuser or user.groups.filter(name="admin").exists():
            return True

        from tenants.models import TenantMembership

        tenant = getattr(self.request, "tenant", None)
        return bool(
            tenant
            and TenantMembership.objects.filter(
                tenant=tenant,
                user=user,
                is_admin=True,
                is_active=True,
            ).exists()
        )
