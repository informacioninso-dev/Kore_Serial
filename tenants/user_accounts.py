from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from .models import TenantMembership
from .roles import assign_role_to_user


class TenantUserAccountError(ValueError):
    pass


class TenantUserNotFoundError(TenantUserAccountError):
    pass


class TenantUserPasswordRequiredError(TenantUserAccountError):
    pass


class TenantGlobalUserProtectedError(TenantUserAccountError):
    pass


@dataclass
class TenantUserAccountResult:
    user: object
    user_created: bool
    membership_created: bool
    membership_reactivated: bool
    membership_admin_updated: bool
    password_updated: bool
    email_updated: bool


def save_tenant_user_account(
    tenant,
    *,
    username,
    email="",
    password="",
    group_name=None,
    is_admin=False,
    allow_create=True,
    allow_global_user_updates=False,
):
    username = (username or "").strip()
    email = (email or "").strip()
    password = (password or "").strip()
    is_admin = bool(is_admin)

    User = get_user_model()
    user = User.objects.filter(username=username).first()
    user_created = False
    password_updated = False
    email_updated = False

    if user is None:
        if not allow_create:
            raise TenantUserNotFoundError("Usuario no encontrado.")
        if not password:
            raise TenantUserPasswordRequiredError("La contraseña es requerida para usuarios nuevos.")
        validate_password(password)
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            is_staff=False,
            is_superuser=False,
            is_active=True,
        )
        user_created = True
        password_updated = True
    else:
        if user.is_superuser and not allow_global_user_updates:
            raise TenantGlobalUserProtectedError(
                "Las cuentas globales se gestionan desde el panel superadmin."
            )

        update_fields = []

        if email and user.email != email:
            user.email = email
            update_fields.append("email")
            email_updated = True

        if password:
            validate_password(password, user=user)
            user.set_password(password)
            update_fields.append("password")
            password_updated = True

        if not user.has_usable_password() and not password:
            raise TenantUserPasswordRequiredError(
                "El usuario existe, pero no tiene contraseña usable. Ingresa una contraseña nueva."
            )

        if not user.is_active:
            user.is_active = True
            update_fields.append("is_active")

        if update_fields:
            user.save(update_fields=update_fields)

    if group_name:
        assign_role_to_user(user, tenant, group_name)

    membership, membership_created = TenantMembership.objects.get_or_create(
        tenant=tenant,
        user=user,
        defaults={"is_admin": is_admin, "is_active": True},
    )

    membership_reactivated = False
    membership_admin_updated = False
    if not membership_created:
        update_fields = []
        if not membership.is_active:
            membership.is_active = True
            update_fields.append("is_active")
            membership_reactivated = True
        if is_admin and not membership.is_admin:
            membership.is_admin = True
            update_fields.append("is_admin")
            membership_admin_updated = True
        if update_fields:
            membership.save(update_fields=update_fields)

    return TenantUserAccountResult(
        user=user,
        user_created=user_created,
        membership_created=membership_created,
        membership_reactivated=membership_reactivated,
        membership_admin_updated=membership_admin_updated,
        password_updated=password_updated,
        email_updated=email_updated,
    )
