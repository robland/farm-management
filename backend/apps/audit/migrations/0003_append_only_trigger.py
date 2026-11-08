from django.db import migrations

FORBID_FN = """
CREATE OR REPLACE FUNCTION fms_forbid_update_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Table % is append-only', TG_TABLE_NAME USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER audit_event_append_only
BEFORE UPDATE OR DELETE ON audit_auditevent
FOR EACH ROW EXECUTE FUNCTION fms_forbid_update_delete();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0002_initial")]

    operations = [
        migrations.RunSQL(FORBID_FN, "DROP FUNCTION IF EXISTS fms_forbid_update_delete();"),
        migrations.RunSQL(
            TRIGGER, "DROP TRIGGER IF EXISTS audit_event_append_only ON audit_auditevent;"
        ),
    ]
