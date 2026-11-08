"""Database-level immutability of validated financial data (defence in depth, FR-076).

The services already refuse these changes; the triggers make sure no code path
(admin, shell, future bug) can alter or delete validated money movements.
"""

from django.db import migrations

TRANSACTION_GUARD = """
CREATE OR REPLACE FUNCTION fms_finance_transaction_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Financial transactions are never deleted (use a reversal)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status IN ('validated', 'reversed') THEN
        IF NEW.amount <> OLD.amount OR NEW.currency <> OLD.currency
           OR NEW.business_date <> OLD.business_date OR NEW.kind <> OLD.kind
           OR NEW.category_id IS DISTINCT FROM OLD.category_id THEN
            RAISE EXCEPTION 'Validated transaction % is immutable', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'reversed' AND NEW.status <> 'reversed' THEN
            RAISE EXCEPTION 'Reversed transaction % cannot change status', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'validated' AND NEW.status NOT IN ('validated', 'reversed') THEN
            RAISE EXCEPTION 'Validated transaction % can only be reversed', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER finance_transaction_guard
BEFORE UPDATE OR DELETE ON finance_financialtransaction
FOR EACH ROW EXECUTE FUNCTION fms_finance_transaction_guard();
"""

ENTRY_GUARD = """
CREATE OR REPLACE FUNCTION fms_finance_entry_guard() RETURNS trigger AS $$
DECLARE
    parent_status varchar;
BEGIN
    SELECT status INTO parent_status FROM finance_financialtransaction
        WHERE id = OLD.transaction_id;
    IF parent_status IN ('validated', 'reversed') THEN
        RAISE EXCEPTION 'Ledger entries of validated transactions are immutable'
            USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER finance_entry_guard
BEFORE UPDATE OR DELETE ON finance_ledgerentry
FOR EACH ROW EXECUTE FUNCTION fms_finance_entry_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]

    operations = [
        migrations.RunSQL(
            TRANSACTION_GUARD,
            "DROP TRIGGER IF EXISTS finance_transaction_guard ON finance_financialtransaction;"
            "DROP FUNCTION IF EXISTS fms_finance_transaction_guard();",
        ),
        migrations.RunSQL(
            ENTRY_GUARD,
            "DROP TRIGGER IF EXISTS finance_entry_guard ON finance_ledgerentry;"
            "DROP FUNCTION IF EXISTS fms_finance_entry_guard();",
        ),
    ]
