from django.apps import AppConfig


class AiAssistantConfig(AppConfig):
    name = "apps.ai_assistant"
    label = "ai_assistant"
    verbose_name = "Assistant IA"

    def ready(self) -> None:
        from apps.ai_assistant import services
        from apps.production_plans.services import VALIDATION_GUARDS

        VALIDATION_GUARDS.append(services.pending_suggestions_guard)
