from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.documents"
    label = "documents"

    def ready(self):
        # Register job task functions and file-cleanup signals.
        from . import signals, tasks  # noqa: F401
        from apps.rewriting import tasks as _r  # noqa: F401
        from apps.templates_manager import tasks as _t  # noqa: F401
        from apps.image_tools import tasks as _i  # noqa: F401
        from apps.splitting import tasks as _s  # noqa: F401
        from apps.converters import tasks as _c  # noqa: F401
