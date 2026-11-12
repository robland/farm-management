"""Financial data offline (OFFLINE_SYNC.md §7): append-only creation, no merge, ever."""

from apps.finance import services
from apps.finance.models import FinancialTransaction, TreasuryAccount
from apps.finance.serializers import (
    TransactionInputSerializer,
    TransactionSerializer,
    TreasuryAccountSerializer,
)
from apps.synchronization.registry import EntityHandler, MergeStrategy, register


class _TransactionSyncSerializer(TransactionInputSerializer):
    """Accepts offline creations; represents with the full read serializer."""

    def to_representation(self, instance: FinancialTransaction) -> dict:
        return dict(TransactionSerializer(instance).data)


register(
    EntityHandler(
        entity_type=services.TX_ENTITY,
        model=FinancialTransaction,
        serializer_class=_TransactionSyncSerializer,
        read_permission=services.VIEW,
        write_permission=services.CREATE,
        strategy=MergeStrategy.APPEND_ONLY,
        # Offline entry by a storekeeper (no finance.view) or a contributor (FR-112, Q35);
        # the recording services enforce who may record what.
        create_permissions=(services.CREATE, services.FUND),
        create=services.sync_create,
        commands={"finance.reverse": services.sync_reverse},
        prefetch=("entries", "attachments"),
    )
)

register(
    EntityHandler(
        entity_type=services.ACCOUNT_ENTITY,
        model=TreasuryAccount,
        serializer_class=TreasuryAccountSerializer,
        read_permission=services.VIEW,
        write_permission=services.ACCOUNTS,
        strategy=MergeStrategy.STRICT,
    )
)
