from django.apps import AppConfig


class AssemblyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "assembly"
    verbose_name = "Ensamblaje serializado"

    def ready(self):
        from . import signals  # noqa: F401
