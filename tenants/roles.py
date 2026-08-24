from django.contrib.auth.models import Group, Permission
from django.utils.text import slugify

from .auth_backends import tenant_group_name, tenant_group_prefix, tenant_role_label


BASE_ROLE_CHOICES = [
    ("admin", "Administrador"),
    ("operaciones", "Operaciones"),
    ("contabilidad", "Contabilidad"),
    ("comercial", "Comercial"),
    ("calidad", "Calidad"),
]

ROLE_PERMISSION_MODULES = [
    ("partners", "Socios"),
    ("procurement", "Compras"),
    ("inventory", "Inventario"),
    ("quality", "Calidad"),
    ("assembly", "Producción"),
    ("sales", "Ventas"),
    ("finance", "Finanzas"),
    ("core", "Configuración"),
    ("migration_hub", "Migración"),
    ("pos", "Punto de venta"),
    ("design", "Diseño"),
    ("capa", "Gestión QA"),
    ("audit", "Auditorías"),
]

ROLE_PERMISSION_ACTIONS = [
    ("view", "Ver"),
    ("add", "Crear"),
    ("change", "Editar"),
    ("delete", "Eliminar"),
]


def role_permission_choices():
    choices = []
    for app_label, app_name in ROLE_PERMISSION_MODULES:
        for action, action_name in ROLE_PERMISSION_ACTIONS:
            choices.append((f"{app_label}.{action}", f"{app_name} · {action_name}"))
    return choices


def permissions_from_matrix(values):
    permissions = Permission.objects.none()
    for value in values:
        try:
            app_label, action = value.split(".", 1)
        except ValueError:
            continue
        permissions = permissions | Permission.objects.filter(
            content_type__app_label=app_label,
            codename__startswith=f"{action}_",
        )
    return permissions.distinct()


def matrix_from_permissions(permissions):
    values = set()
    for permission in permissions.select_related("content_type"):
        action = permission.codename.split("_", 1)[0]
        value = f"{permission.content_type.app_label}.{action}"
        values.add(value)
    return values


def normalize_role_slug(name):
    return slugify(name or "").strip("-")


def tenant_role_groups(tenant):
    return Group.objects.filter(name__startswith=tenant_group_prefix(tenant.schema_name)).order_by("name")


def tenant_role_choices(tenant):
    choices = list(BASE_ROLE_CHOICES)
    for group in tenant_role_groups(tenant):
        choices.append((group.name, tenant_role_label(group.name)))
    return choices


def is_valid_tenant_role_value(tenant, value):
    return value in {choice[0] for choice in tenant_role_choices(tenant)}


def assign_role_to_user(user, tenant, role_value):
    group, _ = Group.objects.get_or_create(name=role_value)

    tenant_prefix = tenant_group_prefix(tenant.schema_name)
    user.groups.remove(*user.groups.filter(name__startswith=tenant_prefix).exclude(pk=group.pk))

    base_names = {value for value, _label in BASE_ROLE_CHOICES}
    if role_value in base_names:
        from .models import TenantMembership

        has_other_tenants = TenantMembership.objects.filter(
            user=user,
            is_active=True,
        ).exclude(tenant=tenant).exists()
        if not has_other_tenants:
            user.groups.remove(*user.groups.filter(name__in=base_names).exclude(pk=group.pk))

    user.groups.add(group)
    return group


def create_tenant_role(tenant, name, permission_values):
    slug = normalize_role_slug(name)
    group = Group.objects.create(name=tenant_group_name(tenant.schema_name, slug))
    group.permissions.set(permissions_from_matrix(permission_values))
    return group


def update_tenant_role(group, permission_values):
    group.permissions.set(permissions_from_matrix(permission_values))
    return group


def user_primary_role_label(user, tenant):
    value = user_primary_role_value(user, tenant)
    if not value:
        return ""
    if value.startswith(tenant_group_prefix(tenant.schema_name)):
        return tenant_role_label(value)
    for role_value, label in BASE_ROLE_CHOICES:
        if role_value == value:
            return label
    return value


def user_primary_role_value(user, tenant):
    tenant_prefix = tenant_group_prefix(tenant.schema_name)
    custom = user.groups.filter(name__startswith=tenant_prefix).order_by("name").first()
    if custom:
        return custom.name
    for value, label in BASE_ROLE_CHOICES:
        if user.groups.filter(name=value).exists():
            return value
    return ""
