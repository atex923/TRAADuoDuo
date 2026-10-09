"""Initial schema migration. Caller owns the enclosing transaction.

V0.0.1 does not import legacy databases. Future migrations must register here
and run only after an explicit backup, preserving the application identifier.
"""
SCHEMA_VERSION = 1


def migrate_new(connection):
    current = connection.execute('PRAGMA user_version').fetchone()[0]
    if current != 0:
        raise ValueError('僅可初始化全新資料庫')
    if connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
        raise ValueError('資料庫已有資料，不能初始化')
    connection.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    connection.execute('CREATE TABLE pages(page_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
