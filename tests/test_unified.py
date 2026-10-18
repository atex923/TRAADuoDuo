import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from traaduoduo.store import ProjectStore, APPLICATION_ID
from traaduoduo.importer import preview_database
from traaduoduo.session import EditSession
from traaduoduo.domain import calculate_day
from datetime import date


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'unified.db'
        self.first = ProjectStore.create(self.path, '甲工程')
        self.a = ProjectStore(self.path, self.first['metadata']['project_id'])
        other = self.a.add_project('乙工程')
        self.b = ProjectStore(self.path, other['metadata']['project_id'])

    def legacy(self):
        source = self.root / 'legacy.db'
        with closing(sqlite3.connect(source)) as c, c:
            c.executescript('''
            CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT,exec_no TEXT,budget_no TEXT,
                award_date TEXT,planned_start TEXT,actual_start TEXT,contract_days INTEGER,day_type TEXT,password_hash TEXT);
            CREATE TABLE holidays(id INTEGER,project_id INTEGER,day TEXT,name TEXT);
            CREATE TABLE workdays(id INTEGER,project_id INTEGER,day TEXT,name TEXT);
            CREATE TABLE railway(id INTEGER,project_id INTEGER,day TEXT,note TEXT);
            CREATE TABLE weather(id INTEGER,project_id INTEGER,day TEXT,morning REAL,afternoon REAL,typhoon REAL,site REAL,note TEXT);
            CREATE TABLE holiday_project_excludes(project_id INTEGER,day TEXT,excluded INTEGER);
            CREATE TABLE budget_books(project_id INTEGER,area TEXT,rows_json TEXT);
            INSERT INTO projects VALUES(1,'舊甲','E-1','B-1','2026-09-01','2026-09-02','2026-09-03',20,'工作日','');
            INSERT INTO projects VALUES(2,'舊乙','E-2','B-2','','2026-09-02','',30,'日曆天','');
            INSERT INTO holidays VALUES(1,1,'2026-09-04','假期');
            INSERT INTO holidays VALUES(2,2,'2026-09-04','另名');
            INSERT INTO holiday_project_excludes VALUES(2,'2026-09-04',1);
            INSERT INTO weather VALUES(1,1,'2026-09-07',0,0.5,1,0,'雨');
            INSERT INTO budget_books VALUES(1,'budget','[{"amount":123}]');
            ''')
        return source

    def test_shared_database_isolation_and_revision(self):
        self.a.save({'holidays': [['2026-09-04', '甲假期']]}, 0)
        self.b.save({'weather': [['2026-09-04','0','.5','雨']]}, 0)
        self.assertEqual(self.b.load()['pages']['holidays'], [])
        self.assertEqual(self.a.load()['pages']['weather'], [])
        with self.assertRaises(ValueError):
            self.a.save({}, 0)
        self.assertEqual(self.b.load()['metadata']['revision'], '1')

    def test_last_project_archive_restore_and_whole_backup(self):
        self.b.remember()
        self.assertEqual(ProjectStore(self.path).load()['metadata']['project_id'], self.b.project_id)
        self.a.archive(self.b.project_id)
        with self.assertRaises(ValueError):
            self.b.save({}, 0)
        self.a.archive(self.b.project_id, False)
        self.b.save({}, 0)
        backup = self.root / 'backup.db'
        self.a.backup(backup)
        self.assertEqual(len(ProjectStore(backup).list_projects()), 2)

    def test_fxwork_preview_shared_excludes_raw_and_readonly(self):
        source = self.legacy()
        before = source.read_bytes()
        preview = preview_database(source)
        self.assertEqual(source.read_bytes(), before)

        a,b = preview['projects']
        self.assertEqual(a['pages']['basic']['start'], '2026-09-03')
        self.assertEqual(a['pages']['basic']['number'], 'E-1')
        self.assertEqual(len(a['pages']['holidays']), 1)
        self.assertEqual(b['pages']['holidays'], [])
        self.assertEqual(calculate_day(date(2026,9,7), EditSession(a['pages']).calendar())[0], 0.5)
        result = self.a.import_preview(preview)
        self.assertEqual(len(result['ids']), 2)
        self.assertTrue(Path(result['backup']).exists())
        imported = ProjectStore(self.path, result['ids'][0])
        report = self.root / 'report.json'
        imported.export_report(report)
        self.assertEqual(json.loads(report.read_text())[0]['raw']['budget_books'][0]['rows_json'], '[{"amount":123}]')
        self.assertEqual(source.read_bytes(), before)

    def test_zero_days_unconfigured_project_imports_without_substitution(self):
        source = self.legacy()
        with closing(sqlite3.connect(source)) as c, c:
            c.execute('UPDATE projects SET contract_days=0 WHERE id=1')
        preview = preview_database(source)
        self.assertFalse(preview['projects'][0]['errors'])
        self.assertEqual(preview['projects'][0]['pages']['basic']['days'],'0')
        result = self.a.import_preview(preview)
        self.assertEqual(ProjectStore(self.path,result['ids'][0]).load()['pages']['basic']['days'],'0')

    def test_invalid_batch_rolls_back_all_projects(self):
        preview = preview_database(self.legacy())
        preview['projects'][1]['pages']['basic']['days'] = 'NaN'
        before = self.a.list_projects()
        with self.assertRaises(ValueError):
            self.a.import_preview(preview)
        self.assertEqual(self.a.list_projects(), before)
        with self.a.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM imports').fetchone()[0], 0)

    def test_duplicate_batch_rolls_back_first_insert(self):
        preview = preview_database(self.legacy())
        self.a.import_preview(preview)
        before = len(self.a.list_projects())
        fresh = deepcopy(preview['projects'][0])
        fresh['source_key'] = 'new-source'
        with self.assertRaises(ValueError):
            self.a.import_preview(dict(preview, projects=[fresh, preview['projects'][1]]))
        self.assertEqual(len(self.a.list_projects()), before)

    def test_old_schema_conversion_source_unchanged(self):
        source = self.root / 'schema1.db'
        with closing(sqlite3.connect(source)) as c, c:
            c.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
            c.execute('CREATE TABLE pages(page_id TEXT PRIMARY KEY,payload TEXT)')
            c.execute('INSERT INTO metadata VALUES (?,?)', ('project_id','legacy-uuid'))
            c.executemany('INSERT INTO pages VALUES (?,?)', [(k,json.dumps(v)) for k,v in self.first['pages'].items()])
            c.execute(f'PRAGMA application_id={APPLICATION_ID}')
            c.execute('PRAGMA user_version=1')
        before = source.read_bytes()
        preview = preview_database(source)
        ids = self.a.import_preview(preview)['ids']
        self.assertEqual(ProjectStore(self.path,ids[0]).load()['pages'], self.first['pages'])
        self.assertEqual(source.read_bytes(), before)

    def test_export_one_project_and_no_overwrite(self):
        source = self.legacy()
        pid = self.a.import_preview(preview_database(source))['ids'][0]
        imported = ProjectStore(self.path,pid)
        dest = self.root / 'one.db'
        imported.export_project(dest)
        self.assertEqual(len(ProjectStore(dest).list_projects()), 1)
        self.assertEqual(ProjectStore(dest).load()['pages'], imported.load()['pages'])
        before = dest.read_bytes()
        with self.assertRaises(FileExistsError):
            imported.export_project(dest)
        self.assertEqual(before,dest.read_bytes())

    def test_invalid_dates_duplicates_password_and_unknown_sources(self):
        source = self.legacy()
        for sql in ["UPDATE projects SET password_hash='protected' WHERE id=1",
                    "UPDATE holidays SET day='not-date'",
                    "INSERT INTO weather VALUES(2,1,'2026-09-07',0,0,0,0,'duplicate')"]:
            with closing(sqlite3.connect(source)) as c, c:
                c.execute(sql)
            if 'password_hash' in sql:
                with self.assertRaises(ValueError):
                    preview_database(source)
            else:
                self.assertTrue(preview_database(source)['projects'][0]['errors'])
            source.unlink()
            source = self.legacy()
        unrelated = self.root / 'unknown.db'
        with closing(sqlite3.connect(unrelated)) as c:
            c.execute('CREATE TABLE user_data(value)')
        with self.assertRaises(ValueError):
            preview_database(unrelated)
