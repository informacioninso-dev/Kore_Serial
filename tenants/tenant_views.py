"""
Vistas de gestión de usuarios dentro del tenant.
Accesibles por el admin del tenant (is_admin=True en TenantMembership),
sin necesidad de ser superadmin global.
"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.shortcuts import redirect, render
from django.views.generic import View

from .forms import TenantRoleForm, TenantUserCreateForm, TenantUserPasswordResetForm
from .models import TenantMembership, UserProfile, identidad_completa
from .auth_backends import tenant_group_name, tenant_group_prefix, tenant_role_label
from .roles import (
    BASE_ROLE_CHOICES,
    ROLE_PERMISSION_ACTIONS,
    ROLE_PERMISSION_MODULES,
    assign_role_to_user,
    create_tenant_role,
    is_valid_tenant_role_value,
    matrix_from_permissions,
    normalize_role_slug,
    tenant_role_choices,
    tenant_role_groups,
    update_tenant_role,
    user_primary_role_label,
    user_primary_role_value,
)
from .user_accounts import (
    TenantGlobalUserProtectedError,
    TenantUserAccountError,
    save_tenant_user_account,
)


class TenantAdminRequiredMixin(LoginRequiredMixin):
    """Permite acceso solo a admins del tenant actual (o superadmins globales)."""

    def dispatch(self, request, *args, **kwargs):
        tenant = getattr(request, 'tenant', None)
        if not tenant or tenant.schema_name == settings.PUBLIC_SCHEMA_NAME:
            messages.error(request, "Acceso no permitido.")
            return redirect(settings.LOGIN_URL)

        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)

        is_tenant_admin = TenantMembership.objects.filter(
            tenant=tenant,
            user=request.user,
            is_admin=True,
            is_active=True,
        ).exists()

        if not is_tenant_admin:
            messages.error(request, "Se requieren permisos de administrador de empresa.")
            return redirect('dashboard')

        return super().dispatch(request, *args, **kwargs)


def _tenant_users_context(request, *, form=None, role_form=None, show_user_form=False, show_role_form=False):
    tenant = request.tenant
    memberships = list(
        TenantMembership.objects
        .filter(tenant=tenant, user__is_superuser=False)
        .select_related('user', 'user__profile')
        .prefetch_related('user__groups')
        .order_by('-is_active', 'user__username')
    )
    for membership in memberships:
        membership.role_label = user_primary_role_label(membership.user, tenant)
        membership.role_value = user_primary_role_value(membership.user, tenant)
        # Quien no tiene identidad completa no puede firmar; se marca en el
        # listado en vez de esperar a que lo descubra al intentarlo.
        membership.identidad_completa = identidad_completa(membership.user)

    active_count = sum(1 for membership in memberships if membership.is_active)
    max_users = tenant.max_users

    tenant_roles = []
    for group in tenant_role_groups(tenant).prefetch_related("permissions__content_type"):
        tenant_roles.append({
            "group": group,
            "label": tenant_role_label(group.name),
            "permission_values": matrix_from_permissions(group.permissions.all()),
        })

    permission_grid = [
        {
            "app_label": app_label,
            "app_name": app_name,
            "actions": [
                {"action": action, "label": action_label, "value": f"{app_label}.{action}"}
                for action, action_label in ROLE_PERMISSION_ACTIONS
            ],
        }
        for app_label, app_name in ROLE_PERMISSION_MODULES
    ]

    return {
        'memberships': memberships,
        'active_count': active_count,
        'max_users': max_users,
        'at_limit': max_users is not None and active_count >= max_users,
        'form': form or TenantUserCreateForm(tenant=tenant),
        'reset_form': TenantUserPasswordResetForm(),
        'role_form': role_form or TenantRoleForm(),
        'show_user_form': show_user_form,
        'show_role_form': show_role_form,
        'tenant_roles': tenant_roles,
        'base_roles': BASE_ROLE_CHOICES,
        'role_choices': tenant_role_choices(tenant),
        'permission_grid': permission_grid,
    }


class TenantUserListView(TenantAdminRequiredMixin, View):
    template_name = "tenants/tenant_users.html"

    def get(self, request):
        return render(request, self.template_name, _tenant_users_context(request))


class TenantUserCreateView(TenantAdminRequiredMixin, View):
    template_name = "tenants/tenant_users.html"

    def post(self, request):
        tenant = request.tenant
        memberships = (
            TenantMembership.objects
            .filter(tenant=tenant, user__is_superuser=False)
            .select_related('user')
            .order_by('-is_active', 'user__username')
        )
        active_count = memberships.filter(is_active=True, user__is_superuser=False).count()
        max_users = tenant.max_users

        form = TenantUserCreateForm(request.POST, tenant=tenant)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                _tenant_users_context(request, form=form, show_user_form=True),
            )

        User = get_user_model()
        username = form.cleaned_data['username']
        email = form.cleaned_data.get('email', '')
        password = form.cleaned_data.get('password', '')
        role = form.cleaned_data['role']
        is_admin = form.cleaned_data.get('is_admin', False)

        existing_user = User.objects.filter(username=username).first()
        existing_membership = None
        if existing_user:
            existing_membership = TenantMembership.objects.filter(
                tenant=tenant,
                user=existing_user,
            ).first()

        adds_active_user = (
            existing_user is None
            or (
                not existing_user.is_superuser
                and (existing_membership is None or not existing_membership.is_active)
            )
        )
        if max_users is not None and active_count >= max_users and adds_active_user:
            messages.error(request, f"Límite de usuarios alcanzado ({active_count}/{max_users}). Actualiza el plan para agregar más.")
            return redirect('tenant_users')

        try:
            result = save_tenant_user_account(
                tenant,
                username=username,
                email=email,
                password=password,
                group_name=role,
                is_admin=is_admin,
                allow_create=True,
                allow_global_user_updates=False,
            )
        except TenantGlobalUserProtectedError as exc:
            messages.error(request, str(exc))
            return redirect('tenant_users')
        except TenantUserAccountError as exc:
            messages.error(request, str(exc))
            return redirect('tenant_users')

        # Identidad de la persona (CC-2026-028). Sin esto los registros dicen
        # una cuenta y no una persona, y no se puede firmar nada.
        persona = result.user
        persona.first_name = form.cleaned_data["first_name"].strip()
        persona.last_name = form.cleaned_data["last_name"].strip()
        persona.save(update_fields=["first_name", "last_name"])
        UserProfile.objects.update_or_create(
            user=persona,
            defaults={
                "identification": form.cleaned_data["identification"],
                "phone": form.cleaned_data["phone"].strip(),
                "position": (form.cleaned_data.get("position") or "").strip(),
            },
        )

        if result.user_created and result.membership_created:
            messages.success(request, f"Usuario '{username}' creado y agregado a la empresa.")
        elif result.membership_created:
            messages.success(request, f"Usuario existente '{username}' vinculado a esta empresa.")
        elif result.membership_reactivated:
            messages.success(request, f"Usuario '{username}' reactivado en esta empresa.")
        elif result.password_updated:
            messages.success(request, f"Contraseña de '{username}' actualizada.")
        elif result.membership_admin_updated:
            messages.success(request, f"Permisos de '{username}' actualizados.")
        else:
            messages.info(request, f"'{username}' ya era miembro de esta empresa.")

        return redirect('tenant_users')


class TenantUserToggleView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = request.tenant
        membership = TenantMembership.objects.filter(pk=pk, tenant=tenant).select_related('user').first()
        if not membership:
            messages.error(request, "Usuario no encontrado.")
            return redirect('tenant_users')

        # No permitir desactivarse a sí mismo
        if membership.user == request.user:
            messages.error(request, "No puedes desactivar tu propia cuenta.")
            return redirect('tenant_users')

        if membership.user.is_superuser:
            messages.error(request, "Las cuentas globales se gestionan desde el panel superadmin.")
            return redirect('tenant_users')

        # Verificar límite si se va a activar
        if not membership.is_active:
            tenant_obj = request.tenant
            max_users = tenant_obj.max_users
            active_count = TenantMembership.objects.filter(
                tenant=tenant_obj,
                is_active=True,
                user__is_superuser=False,
            ).count()
            if max_users is not None and active_count >= max_users:
                messages.error(request, f"Límite de usuarios alcanzado ({active_count}/{max_users}).")
                return redirect('tenant_users')

        membership.is_active = not membership.is_active
        membership.save(update_fields=['is_active'])
        estado = "activado" if membership.is_active else "desactivado"
        messages.success(request, f"Usuario '{membership.user.username}' {estado}.")
        return redirect('tenant_users')


class TenantUserDeleteView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = request.tenant
        membership = TenantMembership.objects.filter(pk=pk, tenant=tenant).select_related('user').first()
        if not membership:
            messages.error(request, "Usuario no encontrado.")
            return redirect('tenant_users')

        if membership.user == request.user:
            messages.error(request, "No puedes removerte a ti mismo.")
            return redirect('tenant_users')

        if membership.user.is_superuser:
            messages.error(request, "Las cuentas globales se gestionan desde el panel superadmin.")
            return redirect('tenant_users')

        username = membership.user.username
        membership.delete()
        messages.success(request, f"Usuario '{username}' removido de la empresa.")
        return redirect('tenant_users')


class TenantUserPasswordResetView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = request.tenant
        membership = (
            TenantMembership.objects
            .filter(pk=pk, tenant=tenant, user__is_superuser=False)
            .select_related('user')
            .first()
        )
        if not membership:
            messages.error(request, "Usuario no encontrado.")
            return redirect('tenant_users')

        if membership.user == request.user:
            messages.error(request, "Usa cambio de contraseña para actualizar tu propia cuenta.")
            return redirect('tenant_users')

        form = TenantUserPasswordResetForm(request.POST, user=membership.user)
        if not form.is_valid():
            messages.error(request, "Revisa la nueva contraseña. Debe coincidir en ambos campos.")
            return redirect('tenant_users')

        user = membership.user
        user.set_password(form.cleaned_data["password1"])
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["password", "is_active"])
        else:
            user.save(update_fields=["password"])

        messages.success(request, f"Contraseña de '{user.username}' actualizada.")
        return redirect('tenant_users')


class TenantUserRoleUpdateView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = request.tenant
        membership = (
            TenantMembership.objects
            .filter(pk=pk, tenant=tenant, user__is_superuser=False)
            .select_related('user')
            .first()
        )
        if not membership:
            messages.error(request, "Usuario no encontrado.")
            return redirect('tenant_users')

        if membership.user == request.user:
            messages.error(request, "No puedes cambiar tu propio rol desde esta pantalla.")
            return redirect('tenant_users')

        role_value = request.POST.get("role") or ""
        if not is_valid_tenant_role_value(tenant, role_value):
            messages.error(request, "Rol no válido para esta empresa.")
            return redirect('tenant_users')

        assign_role_to_user(membership.user, tenant, role_value)
        if role_value == "admin" and not membership.is_admin:
            membership.is_admin = True
            membership.save(update_fields=["is_admin"])

        messages.success(request, f"Rol de '{membership.user.username}' actualizado.")
        return redirect('tenant_users')


class TenantRoleCreateView(TenantAdminRequiredMixin, View):
    template_name = "tenants/tenant_users.html"

    def post(self, request):
        tenant = request.tenant
        form = TenantRoleForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                _tenant_users_context(request, role_form=form, show_role_form=True),
            )

        slug = normalize_role_slug(form.cleaned_data["name"])
        group_name = tenant_group_name(tenant.schema_name, slug)
        if Group.objects.filter(name=group_name).exists():
            form.add_error("name", "Ya existe un rol con ese nombre en esta empresa.")
            return render(
                request,
                self.template_name,
                _tenant_users_context(request, role_form=form, show_role_form=True),
            )

        group = create_tenant_role(tenant, form.cleaned_data["name"], form.cleaned_data["permissions"])
        messages.success(request, f"Rol '{tenant_role_label(group.name)}' creado.")
        return redirect('tenant_users')


class TenantRoleUpdateView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = request.tenant
        group = Group.objects.filter(pk=pk, name__startswith=tenant_group_prefix(tenant.schema_name)).first()
        if not group:
            messages.error(request, "Rol no encontrado.")
            return redirect('tenant_users')

        update_tenant_role(group, request.POST.getlist("permissions"))
        messages.success(request, f"Accesos de '{tenant_role_label(group.name)}' actualizados.")
        return redirect('tenant_users')


class TenantRoleDeleteView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = request.tenant
        group = Group.objects.filter(pk=pk, name__startswith=tenant_group_prefix(tenant.schema_name)).first()
        if not group:
            messages.error(request, "Rol no encontrado.")
            return redirect('tenant_users')

        if group.user_set.exists():
            messages.error(request, "No puedes eliminar un rol con usuarios asignados.")
            return redirect('tenant_users')

        label = tenant_role_label(group.name)
        group.delete()
        messages.success(request, f"Rol '{label}' eliminado.")
        return redirect('tenant_users')


# Módulos que el admin del tenant puede activar/desactivar por sí mismo.
TENANT_SELF_TOGGLE_MODULES = {
    "wms_putaway",
    "wms_replenishment",
    "wms_tasks",
    "wms_zone_picking",
    "after_sales_service",
}


class TenantSelfModuleToggleView(TenantAdminRequiredMixin, View):
    """
    Permite al admin del tenant activar/desactivar sus módulos WMS opcionales
    desde la página de configuración, sin acceso al super-admin panel.
    Solo opera sobre TENANT_SELF_TOGGLE_MODULES.
    """

    def post(self, request, module):
        if module not in TENANT_SELF_TOGGLE_MODULES:
            messages.error(request, "No tienes permiso para modificar ese módulo.")
            return redirect("core:settings")

        from .models import TenantModule
        tenant = request.tenant

        # Los sub-módulos WMS requieren el WMS base activo. Otros módulos
        # self-service (p. ej. post-venta) son independientes.
        if module.startswith("wms_") and not TenantModule.is_enabled(tenant, "wms"):
            messages.error(
                request,
                "El módulo WMS no está disponible en tu plan. "
                "Contacta a soporte para habilitarlo."
            )
            return redirect("core:settings")

        flag, _ = TenantModule.objects.get_or_create(
            tenant=tenant,
            module=module,
            defaults={"enabled": False},
        )
        flag.enabled = not flag.enabled
        flag.save(update_fields=["enabled", "updated_at"])
        estado = "activado" if flag.enabled else "desactivado"
        messages.success(request, f"'{flag.get_module_display()}' {estado}.")
        return redirect("core:settings")
