import re

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError

from .models import Client, Plan, TenantMembership
from .roles import BASE_ROLE_CHOICES, normalize_role_slug, role_permission_choices, tenant_role_choices


_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

_INPUT = {"class": "w-full rounded-lg border px-3 py-2"}


ROLE_CHOICES = BASE_ROLE_CHOICES


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ('name', 'description', 'min_users', 'max_users', 'is_active')
        widgets = {
            'name': forms.TextInput(attrs=_INPUT),
            'description': forms.Textarea(attrs={**_INPUT, 'rows': 2}),
            'min_users': forms.NumberInput(attrs=_INPUT),
            'max_users': forms.NumberInput(attrs=_INPUT),
            'is_active': forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def clean(self):
        cleaned = super().clean()
        min_u = cleaned.get('min_users')
        max_u = cleaned.get('max_users')
        if min_u is not None and max_u is not None and min_u > max_u:
            self.add_error('min_users', 'El mínimo no puede ser mayor al máximo.')
        return cleaned


class TenantCreateForm(forms.Form):
    name = forms.CharField(label="Nombre", max_length=120, widget=forms.TextInput(attrs=_INPUT))
    schema_name = forms.CharField(label="Schema", max_length=63, widget=forms.TextInput(attrs=_INPUT))
    subdomain = forms.CharField(
        label="Subdominio",
        max_length=63,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "acme"}),
        help_text=f"Se convertirá en subdominio.{settings.TENANT_BASE_DOMAIN}"
    )
    plan = forms.ModelChoiceField(
        label="Plan",
        queryset=Plan.objects.filter(is_active=True).order_by('max_users'),
        empty_label="Sin plan",
        required=False,
        widget=forms.Select(attrs=_INPUT),
    )

    admin_username = forms.CharField(label="Usuario admin", max_length=150, required=False, widget=forms.TextInput(attrs=_INPUT))
    admin_email = forms.EmailField(label="Email admin", required=False, widget=forms.EmailInput(attrs=_INPUT))
    admin_password = forms.CharField(
        label="Password admin",
        required=False,
        widget=forms.PasswordInput(attrs=_INPUT),
    )

    def clean_schema_name(self):
        value = (self.cleaned_data.get("schema_name") or "").strip().lower()
        if value == "public":
            raise ValidationError("El schema 'public' esta reservado.")
        if not _SCHEMA_RE.match(value):
            raise ValidationError("Schema invalido. Usa letras, numeros y guion bajo; min 3 caracteres.")
        return value

    def clean_subdomain(self):
        value = (self.cleaned_data.get("subdomain") or "").strip().lower()
        value = value.replace("https://", "").replace("http://", "").strip("/")
        base_domain = settings.TENANT_BASE_DOMAIN
        if value.endswith(f".{base_domain}"):
            value = value[: -(len(base_domain) + 1)]

        if not re.match(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", value):
            raise ValidationError("Subdominio inválido. Solo letras, números y guiones.")

        full_domain = f"{value}.{base_domain}"
        return full_domain

    def clean(self):
        cleaned = super().clean()
        username = (cleaned.get("admin_username") or "").strip()
        password = (cleaned.get("admin_password") or "").strip()
        email = (cleaned.get("admin_email") or "").strip()

        any_admin = any([username, password, email])
        if any_admin and not username:
            self.add_error("admin_username", "Requerido si vas a crear/usar admin.")
        if any_admin and not password:
            self.add_error("admin_password", "Requerido si vas a crear/usar admin.")
        return cleaned


class TenantEditForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ("name", "plan", "is_active")
        widgets = {
            "name": forms.TextInput(attrs=_INPUT),
            "plan": forms.Select(attrs=_INPUT),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plan'].queryset = Plan.objects.filter(is_active=True).order_by('max_users')
        self.fields['plan'].required = False
        self.fields['plan'].empty_label = "Sin plan"


class AddMemberForm(forms.Form):
    username = forms.CharField(
        label="Usuario",
        max_length=150,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "username"}),
    )
    password = forms.CharField(
        label="Nueva contraseña",
        required=False,
        widget=forms.PasswordInput(
            attrs={**_INPUT, "placeholder": "Opcional para resetear acceso"}
        ),
        help_text="Si el usuario existe y escribes una contraseña, se actualiza su acceso.",
    )
    is_admin = forms.BooleanField(
        label="Es administrador",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
    )


class TenantUserCreateForm(forms.Form):
    username = forms.CharField(
        label="Usuario",
        max_length=150,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "nombre.apellido"}),
    )
    first_name = forms.CharField(
        label="Nombres",
        max_length=150,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "Francisco Javier"}),
    )
    last_name = forms.CharField(
        label="Apellidos",
        max_length=150,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "Bravo Perez"}),
    )
    identification = forms.CharField(
        label="Cedula o documento",
        max_length=30,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "1712345678"}),
        help_text="Identifica a la persona en registros y firmas. No se repite entre usuarios.",
    )
    phone = forms.CharField(
        label="Celular",
        max_length=30,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "0991234567"}),
    )
    position = forms.CharField(
        label="Cargo",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs=_INPUT),
    )
    email = forms.EmailField(
        label="Email",
        required=False,
        widget=forms.EmailInput(attrs=_INPUT),
    )
    password = forms.CharField(
        label="Contraseña",
        required=False,
        widget=forms.PasswordInput(
            attrs={**_INPUT, "placeholder": "Opcional; si existe, actualiza la contraseña"}
        ),
        help_text="Requerida para usuarios nuevos. Opcional para resetear usuarios existentes.",
    )
    role = forms.ChoiceField(
        label="Rol",
        choices=ROLE_CHOICES,
        widget=forms.Select(attrs=_INPUT),
    )
    is_admin = forms.BooleanField(
        label="Administrador de la empresa",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300"}),
        help_text="Puede gestionar usuarios, configuracion y modulos de esta empresa.",
    )

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant is not None:
            self.fields["role"].choices = tenant_role_choices(tenant)

    def clean_identification(self):
        from .models import UserProfile, normalizar_identificacion

        valor = normalizar_identificacion(self.cleaned_data.get("identification"))
        if not valor:
            raise forms.ValidationError("La cedula o documento es obligatoria.")
        # Dos cuentas con la misma cedula son un duplicado o una cuenta
        # compartida. Las dos rompen la trazabilidad de quien hizo que.
        username = (self.data.get(self.add_prefix("username")) or "").strip()
        choque = UserProfile.objects.filter(identification=valor)
        if username:
            choque = choque.exclude(user__username=username)
        if choque.exists():
            duenio = choque.first().user
            raise forms.ValidationError(
                f"Esa cedula ya esta registrada para el usuario '{duenio.username}'."
            )
        return valor

    def clean_password(self):
        password = self.cleaned_data.get("password") or ""
        if password:
            User = get_user_model()
            username = self.cleaned_data.get("username") or ""
            user = User.objects.filter(username=username).first()
            password_validation.validate_password(password, user=user)
        return password


class TenantUserPasswordResetForm(forms.Form):
    password1 = forms.CharField(
        label="Nueva contraseña",
        widget=forms.PasswordInput(
            attrs={**_INPUT, "placeholder": "Nueva contraseña"}
        ),
    )
    password2 = forms.CharField(
        label="Confirmar contraseña",
        widget=forms.PasswordInput(
            attrs={**_INPUT, "placeholder": "Confirmar contraseña"}
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        if password1 and password2 and password1 == password2:
            password_validation.validate_password(password1, user=self.user)
        return cleaned


class TenantRoleForm(forms.Form):
    name = forms.CharField(
        label="Nombre del rol",
        max_length=80,
        widget=forms.TextInput(attrs={**_INPUT, "placeholder": "Ej. Bodega"}),
    )
    permissions = forms.MultipleChoiceField(
        label="Accesos",
        choices=role_permission_choices(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        slug = normalize_role_slug(name)
        if not slug:
            raise ValidationError("Ingresa un nombre de rol válido.")
        if slug == "admin":
            raise ValidationError("El rol admin está reservado.")
        return name
