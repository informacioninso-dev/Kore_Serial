from django.apps import AppConfig


class EventBusConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "eventbus"
    verbose_name = "Eventos"

    def ready(self):
        from . import signals  # noqa: F401
