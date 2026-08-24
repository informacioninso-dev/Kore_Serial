from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Permission

from .threadlocals import get_current_tenant


TENANT_GROUP_PREFIX = "tenant:"


def tenant_group_name(schema_name, role_slug):
    return f"{TENANT_GROUP_PREFIX}{schema_name}:{role_slug}"


def tenant_group_prefix(schema_name):
    return f"{TENANT_GROUP_PREFIX}{schema_name}:"


def tenant_role_label(group_name):
    if group_name.startswith(TENANT_GROUP_PREFIX):
        return group_name.split(":", 2)[-1].replace("-", " ").title()
    return group_name


class TenantAwareModelBackend(ModelBackend):
    """
    Django groups are stored in the shared public schema. Global groups keep the
    existing behavior; groups named tenant:<schema>:<role> are only considered
    when permissions are checked inside that tenant.
    """

    def _get_group_permissions(self, user_obj):
        tenant = get_current_tenant()
        groups = user_obj.groups.all()

        if tenant is not None and getattr(tenant, "schema_name", None) != getattr(settings, "PUBLIC_SCHEMA_NAME", "public"):
            prefix = tenant_group_prefix(tenant.schema_name)
            groups = groups.filter(name__startswith=prefix) | groups.exclude(name__startswith=TENANT_GROUP_PREFIX)
        else:
            groups = groups.exclude(name__startswith=TENANT_GROUP_PREFIX)

        return Permission.objects.filter(group__in=groups)
