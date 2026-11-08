from django.apps import AppConfig


class FieldsConfig(AppConfig):
    name = "apps.fields"
    label = "fields"
    verbose_name = "Champs et parcelles"

    def ready(self) -> None:
        from apps.fields import sync  # noqa: F401  (registers sync handlers)
