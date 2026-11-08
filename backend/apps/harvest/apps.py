from django.apps import AppConfig


class HarvestConfig(AppConfig):
    name = "apps.harvest"
    label = "harvest"
    verbose_name = "Récoltes"

    def ready(self) -> None:
        from apps.harvest import sync  # noqa: F401  (registers sync handlers)
