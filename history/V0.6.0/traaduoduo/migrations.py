"""Initialize schema 8 only in a new database; caller owns the transaction.
Legacy sources are read-only and copied by importer, never upgraded in place.
"""
SCHEMA_VERSION = 8


def migrate_new(connection):
    current = connection.execute('PRAGMA user_version').fetchone()[0]
    if current != 0:
        raise ValueError('僅可初始化全新資料庫')
    if connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
        raise ValueError('資料庫已有資料，不能初始化')
    connection.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    connection.execute('CREATE TABLE projects(project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0, saved_at TEXT NOT NULL DEFAULT "", archived INTEGER NOT NULL DEFAULT 0)')
    connection.execute('CREATE TABLE pages(project_id TEXT NOT NULL REFERENCES projects(project_id), page_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(project_id,page_id))')
    connection.execute('CREATE TABLE imports(source_key TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id), report TEXT NOT NULL, raw_payload TEXT NOT NULL)')
    connection.execute('CREATE TABLE bids(project_id TEXT NOT NULL REFERENCES projects(project_id), record_id TEXT NOT NULL, awarded INTEGER NOT NULL CHECK(awarded IN (0,1)), payload TEXT NOT NULL, PRIMARY KEY(project_id,record_id))')
    connection.execute('CREATE UNIQUE INDEX one_awarded_bid ON bids(project_id) WHERE awarded=1')
    for table in ('contract_payments','admin_expenses'):
        connection.execute(f'CREATE TABLE {table}(project_id TEXT NOT NULL REFERENCES projects(project_id), record_id TEXT NOT NULL, period INTEGER NOT NULL CHECK(period>0), payload TEXT NOT NULL, PRIMARY KEY(project_id,record_id))')
    connection.execute("CREATE TABLE other_payments(project_id TEXT NOT NULL REFERENCES projects(project_id), record_id TEXT NOT NULL, period INTEGER NOT NULL CHECK(period>0), stage_id TEXT CHECK(stage_id IN ('first','second','third','final')), payload TEXT NOT NULL, PRIMARY KEY(project_id,record_id))")
    connection.execute('CREATE UNIQUE INDEX one_transfer_per_stage ON other_payments(project_id,stage_id) WHERE stage_id IS NOT NULL')
    connection.execute("CREATE TABLE admin_allocations(project_id TEXT NOT NULL REFERENCES projects(project_id), stage_id TEXT NOT NULL CHECK(stage_id IN ('first','second','third','final')), payload TEXT NOT NULL, PRIMARY KEY(project_id,stage_id))")
    connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
