from core.navigation import build_module_nav, is_configuration_path


def module_access(request):
    """Expose only installed product modules to the copied shared shell."""
    user = getattr(request, "user", None)
    is_authenticated = bool(user and user.is_authenticated)
    production_allowed = bool(
        is_authenticated
        and (user.is_superuser or user.has_perm("assembly.view_serializedunit"))
    )
    warehouse_allowed = bool(
        is_authenticated
        and (user.is_superuser or user.has_perm("wms.view_material"))
    )
    edge_allowed = bool(
        is_authenticated
        and (user.is_superuser or user.has_perm("edge.view_edgegateway"))
    )
    events_allowed = bool(
        is_authenticated
        and (user.is_superuser or user.has_perm("eventbus.view_domainevent"))
    )
    connect_allowed = bool(
        is_authenticated
        and (user.is_superuser or user.has_perm("connect.view_connector"))
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
    # Una sola fuente de verdad: la misma definicion que dibuja la barra.
    is_configuration_area = is_configuration_path(request)
    # Una pantalla de configuracion resalta Configuracion en la barra lateral,
    # no el modulo donde vive su codigo: si no, se resaltarian los dos.
    is_production_area = namespace == "assembly" and not is_configuration_area
    is_warehouse_area = namespace == "wms" and not is_configuration_area
    is_edge_area = namespace == "edge" and not is_configuration_area
    is_events_area = namespace == "eventbus" and not is_configuration_area
    is_connect_area = namespace == "connect" and not is_configuration_area

    # The copied shell contains links for modules intentionally absent here.
    # Keep their administrative links hidden until their own UI is introduced.
    return {
        "modules": {
            "assembly": production_allowed,
            "production": production_allowed,
            "wms": warehouse_allowed,
            "warehouse": warehouse_allowed,
            "edge": edge_allowed,
            "eventbus": events_allowed,
            "connect": connect_allowed,
            "core": is_tenant_admin,
        },
        "is_tenant_admin": is_tenant_admin,
        "is_configuration_area": is_configuration_area,
        "is_production_area": is_production_area,
        "is_warehouse_area": is_warehouse_area,
        "is_edge_area": is_edge_area,
        "is_events_area": is_events_area,
        "is_connect_area": is_connect_area,
        # La barra del modulo se arma sola segun donde este el usuario: ninguna
        # vista tiene que acordarse de pasarla.
        "module_nav": build_module_nav(request),
    }
