def module_access(request):
    """Expose only installed product modules to the copied shared shell."""
    user = getattr(request, "user", None)
    is_authenticated = bool(user and user.is_authenticated)
    production_allowed = bool(
        is_authenticated
        and (user.is_superuser or user.has_perm("assembly.view_serializedunit"))
    )
    is_tenant_admin = False
    if is_authenticated:
        if user.is_superuser or user.groups.filter(name="admin").exists():
            is_tenant_admin = True
        else:
            tenant = getattr(request, "tenant", None)
            if tenant is not None:
                from tenants.models import TenantMembership

                is_tenant_admin = TenantMembership.objects.filter(
                    tenant=tenant,
                    user=user,
                    is_admin=True,
                    is_active=True,
                ).exists()
    resolver_match = getattr(request, "resolver_match", None)
    namespace = getattr(resolver_match, "namespace", "") if resolver_match else ""
    url_name = getattr(resolver_match, "url_name", "") if resolver_match else ""
    configuration_url_names = {
        "product_list",
        "product_create",
        "product_update",
        "version_list",
        "version_create",
        "version_update",
        "plant_list",
        "plant_create",
        "plant_update",
        "area_list",
        "area_create",
        "area_update",
        "line_list",
        "line_create",
        "line_update",
        "station_list",
        "station_create",
        "station_update",
        "route_list",
        "route_create",
        "route_update",
        "step_list",
        "step_create",
        "step_update",
        "parameter_list",
        "parameter_create",
        "parameter_update",
        "requirement_list",
        "requirement_create",
        "requirement_update",
        "equipment_list",
        "equipment_create",
        "equipment_update",
    }
    is_configuration_area = namespace == "core" or url_name in configuration_url_names
    is_production_area = namespace == "assembly" and not is_configuration_area

    # The copied shell contains links for modules intentionally absent here.
    # Keep their administrative links hidden until their own UI is introduced.
    return {
        "modules": {
            "assembly": production_allowed,
            "production": production_allowed,
            "core": is_tenant_admin,
        },
        "is_tenant_admin": is_tenant_admin,
        "is_configuration_area": is_configuration_area,
        "is_production_area": is_production_area,
    }
