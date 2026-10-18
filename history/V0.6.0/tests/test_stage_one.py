import hashlib
import importlib.util
import json
from contextlib import closing
from datetime import date,timedelta
from pathlib import Path
import sqlite3
from unittest.mock import patch
from PySide6.QtCore import QTimer,Qt,QDate
from PySide6.QtWidgets import QDialog,QDialogButtonBox,QCalendarWidget,QApplication,QAbstractItemView
import unittest
import test_ui as ui_support
APP=ui_support.APP
from traaduoduo.details import warranty_end,STATES
from traaduoduo.store import ProjectStore,APPLICATION_ID
from traaduoduo.importer import preview_database


class StageOneTests(unittest.TestCase):
    setUp=ui_support.UITests.setUp
    tearDown=ui_support.UITests.tearDown
    wait_io=ui_support.UITests.wait_io
    def test_basic_new_fields_save_undo_and_warranty(self):
        w=self.window
        w.toggle_lock('basic')
        w.fields['description'].setPlainText('工程說明\n第二行\n第三行')
        w.fields['status'].setCurrentText('施工中')
        w.fields['acceptance_actual'].setText('2024-02-29')
        w.fields['warranty_years'].setText('1')
        w.fields['initial_days'].setText('20')
        w.capture_basic()
        self.assertEqual(w.fields['warranty_end'].text(),'2025-02-28')
        self.assertEqual(w.fields['initial_expected'].text(),'')
        w.save()
        self.wait_io()
        p=w.store.load()['pages']['basic']
        self.assertEqual(p['status'],'施工中')
        self.assertIn('第三行',p['description'])
        self.assertEqual(p['warranty_end'],'2025-02-28')
        self.assertEqual(p['initial_days'],'20')
        self.assertTrue(w.fields['workday_finish'].isReadOnly())
        self.assertEqual(w.fields['workday_finish'].text(),'')

    def test_guarantees_manual_preserved_and_project_isolation(self):
        w=self.window
        self.assertEqual([w.basic_tabs.tabText(i) for i in range(5)],['契約執行','工程費用','保證金','招標情形','變更契約'])
        w.basic_tabs.setCurrentIndex(2)
        self.assertEqual(w.current_page(),'guarantees')
        w.toggle_lock('guarantees')
        f=w.guarantee_fields
        self.assertEqual(f['performance_rate'].text(),'10')
        self.assertEqual(f['warranty_rate'].text(),'3')
        self.assertTrue(f['performance_amount'].isReadOnly())
        f['performance_manual'].setChecked(True)
        f['performance_amount'].setText('12,345')
        f['performance_posted'].setText('2026-10-16')
        f['performance_form'].setText('銀行保證書')
        w.capture_form('guarantees')
        w.save()
        self.wait_io()
        self.assertEqual(w.store.load()['pages']['guarantees']['performance_amount'],'12345')
        f['performance_manual'].setChecked(False)
        w.save()
        self.wait_io()
        self.assertEqual(w.store.load()['pages']['guarantees']['performance_amount'],'12345')
        self.assertEqual(f['performance_amount'].text(),'')
        f['performance_manual'].setChecked(True)
        self.assertEqual(f['performance_amount'].text(),'12345')
        first=w.store.project_id
        other=w.store.add_project('隔離乙')['metadata']['project_id']
        w.switch_project(other)
        self.wait_io()
        self.assertEqual(f['performance_amount'].text(),'')
        w.switch_project(first)
        self.wait_io()
        self.assertEqual(f['performance_amount'].text(),'12345')

    def test_locked_table_scroll_sort_copy_without_edit(self):
        w=self.window
        rows=[[(date(2026,1,1)+timedelta(days=i)).isoformat(),str(i)] for i in reversed(range(100))]
        w.store.save({'holidays':rows},0)
        w.adopt(w.store.load())
        w.tabs.setCurrentIndex(1)
        w.calendar_tabs.setCurrentIndex(0)
        table=w.tables['holidays']
        APP.processEvents()
        self.assertTrue(table.isEnabled())
        self.assertEqual(table.editTriggers(),QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assertEqual(table.item(0,0).text(),'2026-01-01')
        table.selectRow(0)
        self.assertEqual(table.copy_selection(),'2026-01-01\t0')
        table.verticalScrollBar().setValue(table.verticalScrollBar().maximum())
        self.assertGreater(table.verticalScrollBar().value(),0)
        before=w.session.pages['holidays'].copy()
        w.add_row('holidays')
        w.remove_row('holidays')
        self.assertEqual(w.session.pages['holidays'],before)
        w.toggle_lock('holidays')
        table.selectRow(0)
        w.remove_row('holidays')
        self.assertNotIn('2026-01-01',[r[0] for r in w.session.pages['holidays']])
        self.assertEqual(len(w.session.pages['holidays']),99)
        w.save()
        self.wait_io()

    def test_calendar_deferred_and_finish_cached(self):
        w=self.window
        pages=w.store.load()['pages']
        pages['basic']['start']='2026-01-01'
        w.store.save({'basic':pages['basic']},0)
        with patch('traaduoduo.ui.calculate_finish',return_value=date(2026,5,1)) as calc:
            w.adopt(w.store.load())
            self.assertEqual(calc.call_count,0)
            w.tabs.setCurrentIndex(1)
            self.assertEqual(calc.call_count,1)
            w.refresh_calendar()
            self.assertEqual(calc.call_count,1)

    def test_date_calendar_cancel_does_not_insert_today(self):
        w=self.window
        w.toggle_lock('basic')
        field=w.fields['signed']
        self.assertEqual(field.text(),'')
        def cancel():
            field.findChild(QDialog).reject()
        QTimer.singleShot(0,cancel)
        field.choose_date()
        self.assertEqual(field.text(),'')
        def choose():
            dialog=field.findChild(QDialog)
            # Prior cancelled dialog is still a child; use the visible dialog.
            dialog=next(d for d in field.findChildren(QDialog) if d.isVisible())
            dialog.findChild(QCalendarWidget).setSelectedDate(QDate(2026,10,16))
            dialog.accept()
        QTimer.singleShot(0,choose)
        field.choose_date()
        self.assertEqual(field.text(),'2026-10-16')
        w.save()
        self.wait_io()

    def test_schema2_readonly_copy_preserves_unknowns_and_defaults(self):
        source=Path(self.temp.name)/'v012.db'
        basic={'name':'舊工程','number':'OLD','contract':'','contractor':'','award':'','signed':'','start':'','finish':'','days':'100','mode':'工作日','custom_legacy':'保留'}
        with closing(sqlite3.connect(source)) as c,c:
            c.executescript('CREATE TABLE projects(project_id TEXT PRIMARY KEY,revision INTEGER,saved_at TEXT,archived INTEGER); CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE pages(project_id TEXT,page_id TEXT,payload TEXT,PRIMARY KEY(project_id,page_id)); CREATE TABLE imports(source_key TEXT PRIMARY KEY,project_id TEXT,report TEXT,raw_payload TEXT);')
            c.execute("INSERT INTO projects VALUES('old',4,'',0)")
            for k,v in dict(basic=basic,holidays=[],makeup=[],railway=[],weather=[]).items():
                c.execute('INSERT INTO pages VALUES(?,?,?)',('old',k,json.dumps(v)))
            c.execute(f'PRAGMA application_id={APPLICATION_ID}')
            c.execute('PRAGMA user_version=2')
        before=hashlib.sha256(source.read_bytes()).hexdigest()
        preview=preview_database(source)
        pid=self.window.store.import_preview(preview)['ids'][0]
        target=ProjectStore(self.path,pid)
        self.window.adopt(target.load())
        self.window.toggle_lock('basic')
        self.window.fields['number'].setText('NEW')
        self.window.capture_basic()
        self.window.save()
        self.wait_io()
        self.assertEqual(target.load()['pages']['basic']['custom_legacy'],'保留')
        self.assertEqual(target.load()['pages']['guarantees']['performance_rate'],'10')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)

    def test_bad_guarantee_amount_rate_rolls_back(self):
        w=self.window
        original=w.store.load()
        for key,value in [('performance_rate','101'),('bid_amount','NaN'),('warranty_amount','-1')]:
            changed=dict(original['pages']['guarantees'],**{key:value})
            with self.assertRaises(ValueError):
                w.store.save({'guarantees':changed},0)
            self.assertEqual(w.store.load()['pages'],original['pages'])
            self.assertEqual(w.store.load()['metadata']['revision'],'0')

    def test_calendar_reference_rows_and_month_jump(self):
        w=self.window
        w.store.save({'holidays':[['2026-10-10','國慶日']]},0)
        w.adopt(w.store.load())
        w.tabs.setCurrentIndex(1)
        w.calendar_tabs.setCurrentIndex(3)
        self.assertEqual(w.calendar_tabs.tabText(3),'施工曆')
        w.month_input.setText('2026-10')
        w.jump_month()
        self.assertEqual((w.calendar.yearShown(),w.calendar.monthShown()),(2026,10))
        detail=w.calendar.day_details['2026-10-10']
        self.assertEqual(detail['holiday'],'國慶日')
        self.assertEqual(detail['daily'],'0')
        self.assertEqual(detail['work'],'')
        self.assertFalse(w.session.unlocked)
        basic=dict(w.store.load()['pages']['basic'],start='2026-09-25',days='2')
        w.store.save({'basic':basic},1)
        w.adopt(w.store.load())
        w.month_input.setText('2026-09')
        w.jump_month()
        self.assertEqual(float(w.calendar.day_details['2026-09-25']['work']),1)
        self.assertEqual(float(w.calendar.day_details['2026-09-28']['work']),2)
        self.assertEqual(float(w.calendar.day_details['2026-09-29']['work']),3)

    def test_extended_export_roundtrip_and_warranty_validation(self):
        w=self.window
        pages=w.store.load()['pages']
        basic=dict(pages['basic'],description='測試說明',status='保固中')
        guarantees=dict(pages['guarantees'],performance_manual=True,performance_amount='30000')
        w.store.save({'basic':basic,'guarantees':guarantees},0)
        path=Path(self.temp.name)/'export-v020.db'
        w.store.export_project(path)
        self.assertEqual(ProjectStore(path).load()['pages'],w.store.load()['pages'])
        preview=preview_database(path)
        self.assertFalse(preview['projects'][0]['errors'])
        self.assertEqual(preview['projects'][0]['pages']['guarantees']['performance_amount'],'30000')
        self.assertEqual(warranty_end('2024-02-29','1'),'2025-02-28')
        with self.assertRaises(ValueError):
            w.store.save({'basic':dict(basic,warranty_years='1.5')},1)
