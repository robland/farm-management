from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "apps.tasks"
    label = "tasks"
    verbose_name = "Tâches et interventions"

    def ready(self) -> None:
        from apps.tasks import sync  # noqa: F401  (registers sync handlers)
