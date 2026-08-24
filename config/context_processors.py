def module_access(request):
    """Expose only installed product modules to the copied shared shell."""
    user = getattr(request, "user", None)
    allowed = bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.has_perm("assembly.view_serializedunit"))
    )
    # The copied shell contains links for modules intentionally absent here.
    # Keep their administrative links hidden until their own UI is introduced.
    return {"modules": {"assembly": allowed}, "is_tenant_admin": False}
