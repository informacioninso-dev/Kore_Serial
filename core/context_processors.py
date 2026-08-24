# core/context_processors.py
"""
Inyecta flags de acceso por modulo para controlar la visibilidad del sidebar
y otros elementos de la UI segun los permisos del usuario.
"""
from django.conf import settings
from tenants.models import TenantMembership
from core.system_info import get_system_release_info

# Mapeo: clave del modulo -> app_label(s) que se revisan
MODULE_APP_MAP = {
    "partners":    ["partners"],
    "procurement": ["procurement"],
    "production":  ["production"],
    "quality":     ["quality"],
    "sales":       ["sales"],
    "inventory":   ["inventory"],
    "finance":     ["finance"],
    "billing":     ["billing"],
    "core":        ["core"],
    "migration_hub": ["migration_hub"],
}


def system_release(request):
    """Expose the installed release identity in every rendered page."""
    return {"kore_system": get_system_release_info()}


def tenant_modules(request):
    """
    Inyecta `tenant_modules` — set de módulos opcionales habilitados para el tenant actual.
    Ejemplo de uso en template: {% if 'pos' in tenant_modules %}
    """
    user = getattr(request, "user", None)
    tenant = getattr(request, "tenant", None)

    if not user or not user.is_authenticated or tenant is None:
        return {"tenant_modules": set()}

    if tenant.schema_name == settings.PUBLIC_SCHEMA_NAME:
        return {"tenant_modules": set()}

    try:
        from tenants.models import TenantModule
        return {"tenant_modules": TenantModule.get_enabled_set(tenant)}
    except Exception:
        return {"tenant_modules": set()}


def module_access(request):
    """
    Devuelve un dict ``modules`` donde cada clave es un nombre de modulo
y el valor es True/False indicando si el usuario tiene al menos un
permiso en alguna de las apps asociadas.

    Superusuarios y miembros del grupo 'admin' ven todo.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"modules": {k: False for k in MODULE_APP_MAP}, "is_tenant_admin": False}

    tenant = getattr(request, "tenant", None)
    if tenant is not None and tenant.schema_name == settings.PUBLIC_SCHEMA_NAME:
        return {"modules": {k: False for k in MODULE_APP_MAP}, "is_tenant_admin": False}

    # Superusuarios o miembros del grupo admin ven todo
    if user.is_superuser or user.groups.filter(name="admin").exists():
        return {"modules": {k: True for k in MODULE_APP_MAP}, "is_tenant_admin": True}

    # Obtener todos los permisos del usuario (directos + de grupo)
    user_perms = user.get_all_permissions()  # set de "app_label.codename"
    app_labels_with_access = {p.split(".")[0] for p in user_perms}

    modules = {}
    for module, apps in MODULE_APP_MAP.items():
        modules[module] = any(app in app_labels_with_access for app in apps)

    is_tenant_admin = TenantMembership.objects.filter(
        tenant=tenant,
        user=user,
        is_admin=True,
        is_active=True,
    ).exists()

    return {"modules": modules, "is_tenant_admin": is_tenant_admin}


def regulatory_agency(request):
    """
    Expone el nombre del ente regulador sanitario a todas las plantillas.

    El nombre NO debe escribirse a mano en los templates: las instituciones
    cambian de nombre (en Ecuador ha ocurrido) y Kore puede operar en otros
    paises. Se define una vez en CompanyConfig y se usa como {{ regulator }}.

    Cae a "ARCSA" si no hay configuracion todavia (instalacion nueva) o si el
    esquema del tenant aun no existe.
    """
    fallback = {"regulator": "ARCSA", "regulator_full": ""}
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return fallback
    try:
        from core.models import CompanyConfig
        config = CompanyConfig.get()
        if not config:
            return fallback
        return {
            "regulator": config.regulatory_agency or "ARCSA",
            "regulator_full": config.regulatory_agency_full or "",
        }
    except Exception:
        # Sin tenant resuelto o tabla inexistente: no romper el render.
        return fallback
