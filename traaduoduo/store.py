"""Unified repository. Every page/revision belongs to an explicit project ID."""
import json
import sqlite3
import uuid
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from .migrations import migrate_new, SCHEMA_VERSION
from .details import normalize_pages
from .billing import PAYMENT_KEYS

APPLICATION_ID = 0x54524141
PAGE_KEYS = {'basic', 'guarantees', 'costs', 'bids', 'holidays', 'makeup', 'railway', 'weather', *PAYMENT_KEYS,'details','diary','documents','photos','deadline_tracking'}
DEFAULT_BASIC = {'name': '未命名工程', 'number': '', 'contract': '', 'contractor': '',
                 'award': '', 'signed': '', 'start': '', 'finish': '', 'days': '100', 'mode': '工作日'}


def default_pages(name):
    return normalize_pages(dict(basic=dict(DEFAULT_BASIC, name=name), holidays=[], makeup=[], railway=[], weather=[]))


class ProjectStore:
    def __init__(self, path, project_id=None):
        self.path = Path(path).resolve()
        self.project_id = project_id

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=5)
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @classmethod
    def create(cls, path, name='未命名工程'):
        store = cls.create_library(path)
        result = store.add_project(name)
        cls(path, result['metadata']['project_id']).remember()
        return result

    @classmethod
    def create_library(cls, path):
        path = Path(path).resolve()
        with path.open('xb'):
            pass
        store = cls(path)
        with store.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            migrate_new(conn)
            conn.execute(f'PRAGMA application_id={APPLICATION_ID}')
        return store

    def open_result(self, preferred=None):
        with self.connect() as conn:
            self.validate(conn, full=True)
        projects = self.list_projects()
        ids = {p['project_id'] for p in projects}
        if not ids:
            return {'path': str(self.path), 'metadata': {'project_id': None}, 'pages': None}
        if preferred not in ids:
            with self.connect() as conn:
                row = conn.execute("SELECT value FROM metadata WHERE key='last_project_id'").fetchone()
            preferred = row[0] if row and row[0] in ids else projects[0]['project_id']
        return ProjectStore(self.path, preferred).load()

    def validate(self, conn, full=False):
        if conn.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
            raise ValueError('這不是 TRAADuoDuo 統一資料庫；請使用匯入功能')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version != SCHEMA_VERSION:
            raise ValueError(f'不支援資料庫版本 {version}；舊版請匯入新資料庫，原檔不變')
        if full and conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('資料庫完整性檢查失敗')

    def _id(self, conn):
        if self.project_id:
            return self.project_id
        row = conn.execute("SELECT value FROM metadata WHERE key='last_project_id'").fetchone()
        if not row:
            raise ValueError('請選擇工程')
        return row[0]

    @staticmethod
    def _insert(conn, pages):
        from .session import EditSession
        if set(pages) != PAGE_KEYS:
            raise ValueError('工程資料頁不完整')
        session=EditSession(pages)
        session.validate()
        session.reconcile()
        pages=session.pages
        pid = str(uuid.uuid4())
        conn.execute('INSERT INTO projects(project_id) VALUES (?)', (pid,))
        conn.executemany('INSERT INTO pages VALUES (?,?,?)',
                         [(pid, key, json.dumps(value, ensure_ascii=False)) for key, value in pages.items() if key not in ('bids',*PAYMENT_KEYS)])
        conn.execute('INSERT INTO pages VALUES(?,?,?)',(pid,'billing_settings',json.dumps({'available_basis':pages['admin_payments']['available_basis']})))
        ProjectStore._write_bids(conn,pid,pages['bids'])
        ProjectStore._write_billing(conn,pid,pages)
        return pid

    @staticmethod
    def _write_bids(conn,pid,rows):
        conn.execute('DELETE FROM bids WHERE project_id=?',(pid,))
        conn.executemany('INSERT INTO bids VALUES(?,?,?,?)',[(pid,row['id'],int(row['awarded']),json.dumps(row,ensure_ascii=False)) for row in rows])

    @staticmethod
    def _read_pages(conn,pid,schema_version=SCHEMA_VERSION):
        pages={k:json.loads(v) for k,v in conn.execute('SELECT page_id,payload FROM pages WHERE project_id=?',(pid,))}
        pages['bids']=[dict(json.loads(payload),id=rid,awarded=bool(awarded)) for rid,awarded,payload in conn.execute('SELECT record_id,awarded,payload FROM bids WHERE project_id=? ORDER BY rowid',(pid,))]
        settings=pages.pop('billing_settings')
        for key,table in [('contract_payments','contract_payments'),('other_payments','other_payments'),('admin_payments','admin_expenses')]:
            rows=[dict(json.loads(payload),id=rid,period=period) for rid,period,payload in conn.execute(f'SELECT record_id,period,payload FROM {table} WHERE project_id=? ORDER BY rowid',(pid,))]
            if key=='other_payments' and schema_version>=6:
                stages=dict(conn.execute('SELECT record_id,stage_id FROM other_payments WHERE project_id=?',(pid,)))
                rows=[dict(r,stage=stages[r['id']] or '',**({'item':'transfer'} if stages[r['id']] is not None else {})) for r in rows]
            pages[key]=rows if key!='admin_payments' else dict(rows=rows,allocations=[dict(json.loads(payload),stage=stage) for stage,payload in conn.execute("SELECT stage_id,payload FROM admin_allocations WHERE project_id=? ORDER BY CASE stage_id WHEN 'first' THEN 0 WHEN 'second' THEN 1 WHEN 'third' THEN 2 ELSE 3 END",(pid,))],**settings)
        return pages

    @staticmethod
    def _write_billing(conn,pid,pages):
        for key,table in [('contract_payments','contract_payments'),('other_payments','other_payments'),('admin_payments','admin_expenses')]:
            rows=pages[key]['rows'] if key=='admin_payments' else pages[key]
            conn.execute(f'DELETE FROM {table} WHERE project_id=?',(pid,))
            if key=='other_payments':
                conn.executemany('INSERT INTO other_payments VALUES(?,?,?,?,?)',[(pid,r['id'],r['period'],r['stage'] if r['item']=='transfer' and r['stage'] else None,json.dumps(r,ensure_ascii=False)) for r in rows])
            else:
                conn.executemany(f'INSERT INTO {table} VALUES(?,?,?,?)',[(pid,r['id'],r['period'],json.dumps(r,ensure_ascii=False)) for r in rows])
        conn.execute('DELETE FROM admin_allocations WHERE project_id=?',(pid,))
        conn.executemany('INSERT INTO admin_allocations VALUES(?,?,?)',[(pid,a['stage'],json.dumps(a,ensure_ascii=False)) for a in pages['admin_payments']['allocations']])
        conn.execute('UPDATE pages SET payload=? WHERE project_id=? AND page_id=?',(json.dumps({'available_basis':pages['admin_payments']['available_basis'],'allocation_revision':2}),pid,'billing_settings'))

    def add_project(self, name):
        with self.connect() as conn:
            self.validate(conn)
            conn.execute('BEGIN IMMEDIATE')
            pid = self._insert(conn, default_pages(name))
        return ProjectStore(self.path, pid).load()

    def load(self):
        with self.connect() as conn:
            self.validate(conn)
            conn.execute('BEGIN')
            pid = self._id(conn)
            row = conn.execute('SELECT revision,saved_at,archived FROM projects WHERE project_id=?', (pid,)).fetchone()
            if not row:
                raise ValueError('工程不存在')
            pages = self._read_pages(conn,pid)
        if set(pages) != PAGE_KEYS:
            raise ValueError('工程資料頁不完整')
        return {'path': str(self.path), 'projects': self.list_projects(), 'metadata': {'project_id': pid, 'revision': str(row[0]),
                 'saved_at': row[1], 'schema_version': str(SCHEMA_VERSION), 'archived': str(row[2])}, 'pages': pages}

    def remember(self):
        with self.connect() as conn:
            self.validate(conn)
            pid = self._id(conn)
            if not conn.execute('SELECT 1 FROM projects WHERE project_id=?', (pid,)).fetchone():
                raise ValueError('工程不存在')
            conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('last_project_id', pid))

    def list_projects(self):
        with self.connect() as conn:
            self.validate(conn)
            return [dict(project_id=pid, saved_at=stamp, archived=bool(archived), **json.loads(payload))
                    for pid, stamp, archived, payload in conn.execute('SELECT p.project_id,p.saved_at,p.archived,g.payload FROM projects p JOIN pages g ON p.project_id=g.project_id AND g.page_id="basic" ORDER BY p.rowid DESC')]

    def archive(self, project_id, archived=True):
        with self.connect() as conn:
            self.validate(conn)
            conn.execute('UPDATE projects SET archived=? WHERE project_id=?', (int(archived), project_id))

    def save(self, pages, expected_revision):
        with self.connect() as conn:
            self.validate(conn)
            conn.execute('BEGIN IMMEDIATE')
            pid = self._id(conn)
            row = conn.execute('SELECT revision,archived FROM projects WHERE project_id=?', (pid,)).fetchone()
            if not row or row[1]:
                raise ValueError('工程不存在或已封存')
            revision = row[0]
            if revision != expected_revision:
                raise ValueError('資料已被其他視窗更新；請保留目前內容並重新開啟資料庫')
            merged=self._read_pages(conn,pid)
            for key, value in pages.items():
                if key not in PAGE_KEYS:
                    raise ValueError('未知資料頁')
                merged[key]=value
            from .session import EditSession
            session=EditSession(merged)
            session.validate()
            session.reconcile()
            for key,value in session.pages.items():
                if key not in ('bids',*PAYMENT_KEYS):
                    conn.execute('UPDATE pages SET payload=? WHERE project_id=? AND page_id=?',(json.dumps(value,ensure_ascii=False),pid,key))
            self._write_bids(conn,pid,session.pages['bids'])
            self._write_billing(conn,pid,session.pages)
            stamp = datetime.now(timezone.utc).isoformat()
            conn.execute('UPDATE projects SET revision=?,saved_at=? WHERE project_id=?', (revision + 1, stamp, pid))
        return revision + 1, stamp

    def backup(self, destination):
        target = Path(destination).resolve()
        with target.open('xb'):
            pass
        with self.connect() as source, closing(sqlite3.connect(target)) as dest:
            self.validate(source, full=True)
            source.backup(dest)
            self.validate(dest, full=True)
        return str(target)

    def import_preview(self, preview):
        """Backup before one all-or-nothing transaction; never reread changed source."""
        backup = self.path.with_name(self.path.stem + '_before_import_' + uuid.uuid4().hex + '.db')
        self.backup(backup)
        ids = []
        with self.connect() as conn:
            self.validate(conn)
            conn.execute('BEGIN IMMEDIATE')
            for item in preview['projects']:
                if conn.execute('SELECT 1 FROM imports WHERE source_key=?', (item['source_key'],)).fetchone():
                    raise ValueError('此來源工程已匯入；整批未寫入')
                pid = self._insert(conn, item['pages'])
                conn.execute('INSERT INTO imports VALUES (?,?,?,?)', (item['source_key'], pid,
                             json.dumps(item['report'], ensure_ascii=False), json.dumps(item['raw'], ensure_ascii=False)))
                ids.append(pid)
        return {'ids': ids, 'backup': str(backup)}

    def export_project(self, destination):
        payload = self.load()
        if any(r.get('managed') for key in ('documents','photos') for r in payload['pages'][key]['rows']):
            raise ValueError('此工程含 Docstore 庫存檔；請使用文件庫／照片庫的「完整備份」，避免只匯出資料庫而遺漏檔案')
        ProjectStore.create(destination, payload['pages']['basic']['name'])
        target = ProjectStore(destination)
        target.save(payload['pages'], 0)
        # Preserve source evidence for re-import and future mapping.
        with self.connect() as source, target.connect() as dest:
            pid = self._id(source)
            new_pid = target._id(dest)
            for key, report, raw in source.execute('SELECT source_key,report,raw_payload FROM imports WHERE project_id=?', (pid,)):
                dest.execute('INSERT INTO imports VALUES (?,?,?,?)', (key, new_pid, report, raw))
        return str(destination)

    def export_report(self, destination):
        with self.connect() as conn:
            self.validate(conn)
            rows = [dict(source_key=k, report=json.loads(r), raw=json.loads(v)) for k,r,v in
                    conn.execute('SELECT source_key,report,raw_payload FROM imports WHERE project_id=?', (self._id(conn),))]
        with Path(destination).open('x', encoding='utf-8') as output:
            json.dump(rows, output, ensure_ascii=False, indent=2)
        return str(destination)
