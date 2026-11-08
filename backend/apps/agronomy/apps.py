from django.apps import AppConfig


class AgronomyConfig(AppConfig):
    name = "apps.agronomy"
    label = "agronomy"
    verbose_name = "Programme agronomique"

    def ready(self) -> None:
        from apps.agronomy import services, sync  # noqa: F401  (sync handlers, version hook)
        from apps.production_plans.services import VERSION_COPY_HOOKS

        VERSION_COPY_HOOKS.append(services.copy_program)
