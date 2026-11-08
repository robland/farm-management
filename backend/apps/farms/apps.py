from django.apps import AppConfig


class FarmsConfig(AppConfig):
    name = "apps.farms"
    label = "farms"
    verbose_name = "Exploitations"

    def ready(self) -> None:
        from apps.farms import sync  # noqa: F401  (registers sync handlers)
