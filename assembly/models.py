from django.db import models

from core.models import AuditModel


class UnitStatus(models.TextChoices):
    REGISTERED = "REGISTERED", "Registrada"
    IN_PROCESS = "IN_PROCESS", "En proceso"
    COMPLETED = "COMPLETED", "Completada"
    ARCHIVED = "ARCHIVED", "Archivada"


class AssembledProduct(AuditModel):
    code = models.CharField("Codigo", max_length=50, unique=True)
    name = models.CharField("Nombre", max_length=180)
    description = models.TextField("Descripcion", blank=True)
    is_active = models.BooleanField("Activo", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Producto ensamblado"
        verbose_name_plural = "Productos ensamblados"

    def __str__(self):
        return f"{self.code} - {self.name}"


class ProductVersion(AuditModel):
    product = models.ForeignKey(
        AssembledProduct,
        on_delete=models.PROTECT,
        related_name="versions",
        verbose_name="Producto ensamblado",
    )
    code = models.CharField("Codigo de version", max_length=50)
    name = models.CharField("Nombre", max_length=180)
    description = models.TextField("Descripcion", blank=True)
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        ordering = ["product__code", "code"]
        verbose_name = "Version de producto"
        verbose_name_plural = "Versiones de producto"
        constraints = [
            models.UniqueConstraint(fields=["product", "code"], name="assembly_version_product_code_uniq"),
        ]

    def __str__(self):
        return f"{self.product.code} - {self.code}"


class SerializedUnit(AuditModel):
    version = models.ForeignKey(
        ProductVersion,
        on_delete=models.PROTECT,
        related_name="units",
        verbose_name="Version",
    )
    serial_number = models.CharField("Numero de serie", max_length=120, unique=True)
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=UnitStatus.choices,
        default=UnitStatus.REGISTERED,
        db_index=True,
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Unidad serializada"
        verbose_name_plural = "Unidades serializadas"

    def __str__(self):
        return self.serial_number
