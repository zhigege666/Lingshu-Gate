"""Latest audit identity lookup keeps historical semantics and an indexed plan."""
from pathlib import Path

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.persistence.audit_lookup_migration import AUDIT_LOOKUP_MIGRATION_ID


def test_latest_user_snapshot_preserves_deleted_users_and_timestamp_ties(tmp_path: Path) -> None:
    database = SQLiteDatabase('', tmp_path)
    store = AccessControlStore(database)
    with database.session() as connection:
        connection.executemany(
            "INSERT INTO invocation_audits(id,correlation_id,user_id,username,auth_type,server_id,"
            "tool_id,tool_access,required_access,granted_access,decision,reason,outcome,created_at) "
            "VALUES(?,? ,?,?,'session','retired','mcp.retired.tool','read','read','read',"
            "'allow','test','success',?)",
            [(audit_id, audit_id, user, name, timestamp) for audit_id, user, name, timestamp in [
                ('old', 'deleted-user', 'Old name', '2026-09-01T00:00:00+00:00'),
                ('a', 'deleted-user', 'Wrong tie', '2026-10-01T00:00:00+00:00'),
                ('z', 'deleted-user', 'Zed', '2026-10-01T00:00:00+00:00'),
                ('other', 'other-user', 'alice', '2026-09-01T00:00:00+00:00'),
            ]],
        )
    result = store.list_invocation_audit_filter_options()
    assert result['users'] == [
        {'id': 'other-user', 'username': 'alice'},
        {'id': 'deleted-user', 'username': 'Zed'},
    ]
    assert result['tools'] == [{'server_id': 'retired', 'tool_id': 'mcp.retired.tool'}]


def test_existing_database_receives_index_once_without_changing_audits(tmp_path: Path) -> None:
    database = SQLiteDatabase('', tmp_path)
    with database.session() as connection:
        connection.execute('DROP INDEX idx_invocation_audits_user_latest')
        connection.execute('DELETE FROM schema_migrations WHERE id=?', (AUDIT_LOOKUP_MIGRATION_ID,))
    database.initialize()
    database.initialize()
    with database.session() as connection:
        plan = connection.execute(
            'EXPLAIN QUERY PLAN SELECT username FROM invocation_audits '
            'WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 1', ('user',),
        ).fetchall()
        detail = ' '.join(str(row['detail']) for row in plan)
        assert 'idx_invocation_audits_user_latest' in detail
        assert 'TEMP B-TREE' not in detail
        assert connection.execute('SELECT count(*) FROM schema_migrations WHERE id=?',
                                  (AUDIT_LOOKUP_MIGRATION_ID,)).fetchone()[0] == 1
    assert AccessControlStore(database).list_invocation_audit_filter_options() == {
        'users': [], 'servers': [], 'tools': [],
    }
