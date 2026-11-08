from django.apps import AppConfig


class ProductionPlansConfig(AppConfig):
    name = "apps.production_plans"
    label = "production_plans"
    verbose_name = "Plans de production"

    def ready(self) -> None:
        from apps.production_plans import sync  # noqa: F401  (registers sync handlers)
