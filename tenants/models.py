from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django_tenants.models import TenantMixin, DomainMixin


class Plan(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    min_users = models.PositiveIntegerField(default=1)
    max_users = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['max_users']
        verbose_name = 'Plan'
        verbose_name_plural = 'Planes'

    def __str__(self):
        return f"{self.name} ({self.min_users}–{self.max_users} usuarios)"


class Client(TenantMixin):
    name = models.CharField(max_length=120)
    plan = models.ForeignKey(
        Plan,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='clients',
    )
    is_active = models.BooleanField(default=True)
    created_on = models.DateField(auto_now_add=True)

    auto_create_schema = True

    def __str__(self):
        return f"{self.name} ({self.schema_name})"

    def get_absolute_url(self):
        return reverse("tenants:detail", kwargs={"pk": self.pk})

    @property
    def max_users(self):
        return self.plan.max_users if self.plan else None

    @property
    def active_member_count(self):
        return self.memberships.filter(is_active=True, user__is_superuser=False).count()


class Domain(DomainMixin):
    pass


class TenantMembership(models.Model):
    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tenant_memberships')
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('tenant', 'user')
        verbose_name = 'Membres\u00eda de empresa'
        verbose_name_plural = 'Membres\u00edas de empresa'

    def __str__(self):
        return f"{self.user} -> {self.tenant}"


# ─── Módulos opcionales por tenant ───────────────────────────────────────────

AVAILABLE_MODULES = [
    # ── Operacionales ─────────────────────────────────────────────────────────
    ("pos",               "Punto de venta"),
    ("wms",               "Gesti\u00f3n de bodegas"),
    ("migration_hub",     "Migraci\u00f3n masiva"),

    # ── Capacidades regulatorias atómicas ─────────────────────────────────────
    ("qa_reception",      "Control de calidad en recepci\u00f3n"),
    ("qa_returns",        "Control de calidad en devoluciones"),
    ("qa_dispatch",       "Trazabilidad de lotes en salidas"),
    ("arcsa_enforcement", "Control de dispositivos m\u00e9dicos"),
    ("manufacturing_qa",  "Control de calidad en producci\u00f3n"),
    ("recall_module",     "Retiros de mercado"),

    # ── WMS avanzado (sub-módulos activables independientemente) ─────────────
    ("wms_putaway",       "Bodegas - ubicaci\u00f3n dirigida"),
    ("wms_replenishment", "Bodegas - alertas de reabastecimiento"),
    ("wms_tasks",         "Bodegas - tareas operativas"),
    ("wms_zone_picking",  "Bodegas - preparaci\u00f3n por zona"),

    # ── Módulos especializados ─────────────────────────────────────────────────
    ("technovigilance",   "Tecnovigilancia (ISO 14971 / ARCSA)"),
    ("after_sales_service", "Servicio post-venta / instalaciones"),

    # ── Legacy — mantener para compatibilidad, reemplazado por capacidades ────
    ("iso_13485",         "ISO 13485 - Dispositivos m\u00e9dicos (compatibilidad)"),
]

# Perfiles regulatorios predefinidos
# La ausencia de arcsa_enforcement en un tenant con qa_reception activa
# el modo strict_bpadt=True (lote obligatorio para TODOS los productos).
TENANT_EDITIONS = {
    "sin_regulacion": {
        "label": "Distribuidor no regulado",
        "description": "Distribución general sin requisitos QA obligatorios. "
                       "Multi-bodega, trazabilidad de inventario basica.",
        "icon": "package",
        "modules": ["wms", "migration_hub"],
        "badge": "gray",
    },
    "distribuidor": {
        "label": "Distribuidor BPADT",
        "description": "Distribuidor de productos regulados sin fabricacion propia. "
                       "Aplica BPADT Ecuador: lote y caducidad obligatorios en recepcion "
                       "y despacho para TODOS los productos, retiros de mercado.",
        "icon": "truck",
        "modules": [
            "wms", "migration_hub", "qa_reception", "qa_returns",
            "qa_dispatch", "recall_module",
        ],
        "badge": "blue",
    },
    "manufactura": {
        "label": "Fabricante ISO 13485",
        "description": "Fabricante o distribuidor autorizado de dispositivos medicos. "
                       "ISO 13485 completo: ARCSA, QA de produccion, tecnovigilancia, "
                       "trazabilidad de lotes regulados, retiros de mercado.",
        "icon": "shield",
        "modules": [
            "wms", "migration_hub", "qa_reception", "qa_returns", "qa_dispatch",
            "arcsa_enforcement", "manufacturing_qa", "recall_module",
            "iso_13485", "technovigilance",
        ],
        "badge": "purple",
    },
}


class TenantModule(models.Model):
    """
    Módulos opcionales habilitados por tenant.
    Vive en el esquema público — gestionable desde el super admin sin entrar al tenant.
    """
    tenant  = models.ForeignKey(
        Client, on_delete=models.CASCADE,
        related_name="modules", verbose_name="Cliente",
    )
    module  = models.CharField(
        "Módulo", max_length=50,
        choices=AVAILABLE_MODULES,
    )
    enabled = models.BooleanField("Habilitado", default=False)
    updated_at = models.DateTimeField("Actualizado", auto_now=True)

    class Meta:
        unique_together = ("tenant", "module")
        verbose_name = "Módulo del tenant"
        verbose_name_plural = "Módulos del tenant"
        ordering = ["tenant", "module"]

    def __str__(self):
        status = "ON" if self.enabled else "OFF"
        return f"{self.tenant.name} · {self.get_module_display()} [{status}]"

    @classmethod
    def is_enabled(cls, tenant, module: str) -> bool:
        """Consulta rápida — el resultado viene del esquema público."""
        return cls.objects.filter(
            tenant=tenant, module=module, enabled=True
        ).exists()

    @classmethod
    def get_enabled_set(cls, tenant) -> set:
        """Devuelve el conjunto de módulos habilitados para un tenant."""
        return set(
            cls.objects.filter(tenant=tenant, enabled=True)
            .values_list("module", flat=True)
        )

    @classmethod
    def ensure_all_exist(cls, tenant):
        """Crea registros (deshabilitados) para módulos que aún no existen."""
        for module, _ in AVAILABLE_MODULES:
            cls.objects.get_or_create(
                tenant=tenant, module=module,
                defaults={"enabled": False},
            )


class TenantHealthState(models.TextChoices):
    UP = "up", "Disponible"
    DOWN = "down", "Con error"
    UNKNOWN = "unknown", "Desconocido"
    SKIPPED = "skipped", "Omitido"


class TenantHealthCheck(models.Model):
    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="health_checks")
    domain = models.CharField(max_length=255, blank=True)
    url = models.CharField(max_length=500, blank=True)
    state = models.CharField(max_length=20, choices=TenantHealthState.choices, default=TenantHealthState.UNKNOWN)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    schema_name = models.CharField(max_length=63, blank=True)
    status_value = models.CharField(max_length=32, blank=True)
    error = models.TextField(blank=True)
    checked_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Chequeo de salud de tenant"
        verbose_name_plural = "Chequeos de salud de tenant"
        ordering = ("-checked_at",)
        indexes = [
            models.Index(fields=["tenant", "-checked_at"], name="tenants_ten_tenant__370f96_idx"),
            models.Index(fields=["state", "-checked_at"], name="tenants_ten_state_429132_idx"),
        ]

    def __str__(self):
        return f"{self.tenant.schema_name} {self.state} ({self.checked_at:%Y-%m-%d %H:%M:%S})"


def normalizar_identificacion(valor):
    """
    Deja la cedula comparable: sin espacios, guiones ni puntos.

    "171234567-8", " 1712345678 " y "1712345678" son la misma persona. Sin esto
    la unicidad no sirve de nada: bastaria un guion para duplicar a alguien.
    """
    return "".join(ch for ch in (valor or "") if ch.isalnum()).upper()


class UserProfile(models.Model):
    """
    Identidad de una persona detras de una cuenta (CC-2026-028).

    Un ERP regulado registra quien recibio, quien inspecciono, quien libero y
    quien firmo. Si esos registros dicen "kore.dev" no identifican a una
    persona: identifican una cuenta, y una cuenta no responde ante nadie.

    Vive en la aplicacion compartida porque los usuarios lo son: una persona
    tiene una sola cedula, no una por empresa.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="Usuario",
    )
    identification = models.CharField(
        "Cedula o documento",
        max_length=30,
        unique=True,
        help_text="Documento de identidad. Se guarda sin guiones ni espacios.",
    )
    phone = models.CharField("Celular", max_length=30)
    position = models.CharField("Cargo", max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Perfil de usuario"
        verbose_name_plural = "Perfiles de usuario"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.identification})"

    def save(self, *args, **kwargs):
        self.identification = normalizar_identificacion(self.identification)
        return super().save(*args, **kwargs)


def identidad_completa(user):
    """
    True si esta persona puede aparecer en un registro y ser identificada.

    Hacen falta las cuatro cosas: nombre, apellido, cedula y celular. Con menos,
    el registro dice una cuenta, no una persona.
    """
    if user is None or not getattr(user, "is_authenticated", True):
        return False
    if not (user.first_name or "").strip() or not (user.last_name or "").strip():
        return False
    perfil = getattr(user, "profile", None)
    if perfil is None:
        return False
    return bool((perfil.identification or "").strip() and (perfil.phone or "").strip())
