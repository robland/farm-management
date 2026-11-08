"""Tasks are pulled and their status changed offline by command; reports are append-only."""

from apps.synchronization.registry import EntityHandler, MergeStrategy, register
from apps.tasks import services
from apps.tasks.models import Task, TaskReport
from apps.tasks.serializers import TaskReportSerializer, TaskSerializer

register(
    EntityHandler(
        entity_type=services.TASK_ENTITY,
        model=Task,
        serializer_class=TaskSerializer,
        read_permission=services.VIEW,
        write_permission=services.REPORT,  # finer checks inside change_status
        strategy=MergeStrategy.STRICT,
        commands={"task.change_status": services.sync_change_status},
    )
)

register(
    EntityHandler(
        entity_type=services.REPORT_ENTITY,
        model=TaskReport,
        serializer_class=TaskReportSerializer,
        read_permission=services.VIEW,
        write_permission=services.REPORT,
        strategy=MergeStrategy.APPEND_ONLY,
        create=services.create_report,
    )
)
