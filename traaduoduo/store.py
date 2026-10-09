"""Connection-per-operation SQLite repository; safe to use on a worker thread."""
import json
import sqlite3
import uuid
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from .migrations import migrate_new, SCHEMA_VERSION

APPLICATION_ID = 0x54524141
DEFAULT_BASIC = {'name': '未命名工程', 'number': '', 'contract': '', 'contractor': '',
                 'award': '', 'signed': '', 'start': '', 'finish': '', 'days': '100', 'mode': '工作日'}


class ProjectStore:
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=5)
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @classmethod
    def create(cls, path, name='未命名工程'):
        path = Path(path).resolve()
        # Exclusive creation: never overwrite an existing user database.
        with path.open('xb'):
            pass
        store = cls(path)
        try:
            with store.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                migrate_new(conn)
                conn.executemany('INSERT INTO metadata VALUES (?,?)', [
                    ('project_id', str(uuid.uuid4())), ('schema_version', '1'), ('revision', '0'), ('saved_at', '')])
                basic = dict(DEFAULT_BASIC, name=name)
                conn.execute('INSERT INTO pages VALUES (?,?)', ('basic', json.dumps(basic, ensure_ascii=False)))
                for page in ('holidays', 'makeup', 'railway', 'weather'):
                    conn.execute('INSERT INTO pages VALUES (?,?)', (page, '[]'))
                conn.execute(f'PRAGMA application_id={APPLICATION_ID}')
                conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        except Exception:
            # Retain failed creation for diagnosis; never touch existing files.
            raise
        return store.load()

    def validate(self, conn):
        if conn.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
            raise ValueError('這不是 TRAADuoDuo 資料庫；舊程式資料需另行遷移')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version != SCHEMA_VERSION:
            raise ValueError(f'不支援資料庫版本 {version}；未修改原檔')
        if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('資料庫完整性檢查失敗')

    def load(self):
        with self.connect() as conn:
            self.validate(conn)
            conn.execute('BEGIN')
            metadata = dict(conn.execute('SELECT key,value FROM metadata'))
            pages = {key: json.loads(value) for key, value in conn.execute('SELECT page_id,payload FROM pages')}
        if set(pages) != {'basic', 'holidays', 'makeup', 'railway', 'weather'}:
            raise ValueError('工程資料頁不完整')
        return {'path': str(self.path), 'metadata': metadata, 'pages': pages}

    def save(self, pages, expected_revision):
        with self.connect() as conn:
            self.validate(conn)
            conn.execute('BEGIN IMMEDIATE')
            revision = int(conn.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
            if revision != expected_revision:
                raise ValueError('資料已被其他視窗更新；請保留目前內容並重新開啟資料庫')
            for key, value in pages.items():
                if key not in {'basic', 'holidays', 'makeup', 'railway', 'weather'}:
                    raise ValueError('未知資料頁')
                conn.execute('UPDATE pages SET payload=? WHERE page_id=?', (json.dumps(value, ensure_ascii=False), key))
            stamp = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE metadata SET value=? WHERE key='revision'", (str(revision + 1),))
            conn.execute("UPDATE metadata SET value=? WHERE key='saved_at'", (stamp,))
        return revision + 1, stamp

    def backup(self, destination):
        target = Path(destination).resolve()
        with target.open('xb'):
            pass
        with self.connect() as source, closing(sqlite3.connect(target)) as dest:
            self.validate(source)
            source.backup(dest)
            self.validate(dest)
        return str(target)
