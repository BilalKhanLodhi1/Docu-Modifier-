from django.apps import AppConfig


class SplittingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.splitting"
    label = "splitting"
