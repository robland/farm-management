from django.apps import AppConfig


class FinanceConfig(AppConfig):
    name = "apps.finance"
    label = "finance"
    verbose_name = "Trésorerie"

    def ready(self) -> None:
        from apps.finance import sync  # noqa: F401  (registers sync handlers)
