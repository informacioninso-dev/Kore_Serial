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
    # The copied shell contains links for modules intentionally absent here.
    # Keep their administrative links hidden until their own UI is introduced.
    return {
        "modules": {
            "assembly": production_allowed,
            "production": production_allowed,
            "core": is_tenant_admin,
        },
        "is_tenant_admin": is_tenant_admin,
    }
