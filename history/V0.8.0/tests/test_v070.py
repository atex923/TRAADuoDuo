"""V0.7.0 acceptance: isolated data, no user library changes."""
from copy import deepcopy
from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3,tempfile,unittest
from unittest.mock import patch
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QDialog,QDialogButtonBox,QLineEdit,QPlainTextEdit,QMessageBox
import test_ui as support
from traaduoduo.tracking import deadline_status,upcoming,validate_tracking,normalize_documents,document_order
from traaduoduo.store import ProjectStore
from traaduoduo.asset_store import new_asset,sha,portable_backup,restore_backup
from traaduoduo.importer import preview_database

def task(number=1,**kwargs):
    return dict(dict(id='t'+str(number),number=number,issued_at='2026-10-18',document_no='文001',due_date='2026-10-20',work='限期改善',completed_date=''),**kwargs)

class Rules(unittest.TestCase):
    def test_first_overdue_day_and_colors(self):
        row=task()
        for day,state,days,color in [(19,'pending',0,'#FFF2CC'),(20,'due',0,'#FFA500'),(21,'overdue',1,'#D32F2F'),(22,'overdue',2,'#D32F2F')]:
            s=deadline_status(row,date(2026,10,day));self.assertEqual((s['state'],s['days'],s['color']),(state,days,color));self.assertEqual(s['overdue_date'],'2026-10-21')
        self.assertTrue(deadline_status(row,date(2026,10,21))['bold']);self.assertEqual(deadline_status(row,date(2026,10,21))['foreground'],'#FFFFFF')
    def test_completed_freezes_lateness(self):
        row=task(completed_date='2026-10-22');s=deadline_status(row,date(2027,1,1));self.assertEqual((s['state'],s['days']),('completed',2));self.assertFalse(s['bold']);self.assertEqual(upcoming([row],date(2026,10,18)),[])
    def test_five_days_inclusive_and_no_overdue(self):
        rows=[task(i+1,due_date=f'2026-10-{d:02}') for i,d in enumerate([17,18,23,24])]
        self.assertEqual([r['number'] for r in upcoming(rows,date(2026,10,18))],[2,3])
    def test_leap_and_year_boundaries_calendar_days(self):
        self.assertEqual(deadline_status(task(due_date='2024-02-28'),date(2024,2,29))['days'],1)
        self.assertEqual(deadline_status(task(due_date='2026-12-31'),date(2027,1,1))['days'],1)
    def test_validation_and_precision(self):
        for issued in ['','2026-10-18','2026-10-18 08:05']:validate_tracking([task(issued_at=issued)])
        for kwargs in [dict(due_date=''),dict(due_date='2026-02-30'),dict(issued_at='2026-10-18 25:00'),dict(work=' '),dict(number=0),dict(completed_date='bad')]:
            with self.assertRaises(ValueError):validate_tracking([task(**kwargs)])
        with self.assertRaises(ValueError):validate_tracking([task(),task()])
    def test_document_default_numeric_sort_preserves_identity(self):
        original=dict(categories=[],rows=[dict(id=str(i),name=str(i)) for i in range(3)])
        value=normalize_documents(original);self.assertNotIn('number',original['rows'][0]);self.assertEqual([r['number'] for r in value['rows']],[1,2,3])
        for row,n in zip(value['rows'],[10,1,2]):row['number']=n
        self.assertEqual([r['number'] for r in document_order(value['rows'],3)],[1,2,10]);self.assertEqual([r['number'] for r in document_order(value['rows'],4)],[10,2,1]);self.assertEqual(value['rows'][0]['number'],10)

class TrackingUI(support.UITests):
    # Inherit fixture only, not baseline tests.
    def test_new_tabs_and_lock(self):
        w=self.window;w.tabs.setCurrentIndex(4);self.assertEqual([w.diary_tabs.tabText(i) for i in range(2)],['事記本','期限追蹤']);w.diary_tabs.setCurrentIndex(1);self.assertEqual(w.current_page(),'deadline_tracking')
        with self.assertRaises(ValueError):w.commit_extra('deadline_tracking',[task()])
        w.toggle_lock('deadline_tracking');w.commit_extra('deadline_tracking',[task()]);self.assertEqual(w.tracking_table.rowCount(),1)
    def test_refresh_no_dirty_and_locate_after_filter(self):
        w=self.window;w.session.unlocked.add('deadline_tracking');w.commit_extra('deadline_tracking',[task(10),task(2,due_date='2026-10-23'),task(3,completed_date='2026-10-19')]);w.session.saved=deepcopy(w.session.pages)
        w.refresh_tracking(today=date(2026,10,18));self.assertEqual(w.upcoming_table.rowCount(),2);w.tracking_filter.setCurrentIndex(2);w.refresh_tracking(today=date(2026,10,18));w.locate_tracking(1)
        self.assertEqual(w.tracking_table.currentItem().data(Qt.ItemDataRole.UserRole),'t2');self.assertFalse(w.session.dirty())
        w.refresh_tracking(today=date(2026,10,21));self.assertEqual(w.tracking_table.item(2,1).text(),'1 天');self.assertFalse(w.session.dirty())
    def test_document_renumber_undo_filter_and_columns(self):
        w=self.window;w.session.unlocked.add('documents');source=Path(self.temp.name)/'x.txt';source.write_text('demo')
        rows=[dict(new_asset(source),number=n,document_no='文'+str(n),document_date='2026-10-18') for n in [10,1,2]];w.commit_extra('documents',dict(categories=[],rows=rows));ui=w.asset_ui['documents'];ui['sort'].setCurrentIndex(3)
        self.assertEqual([ui['table'].item(i,0).text() for i in range(3)],['1','2','10']);ids=[ui['table'].item(i,0).data(Qt.ItemDataRole.UserRole) for i in range(3)]
        original=deepcopy(w.session.pages['documents']);w.apply_document_numbering(ids);self.assertEqual({r['id']:r['number'] for r in w.session.pages['documents']['rows']},{rid:i+1 for i,rid in enumerate(ids)});w.session.undo('documents');self.assertEqual(w.session.pages['documents'],original)
        ui['filter']='category'
        with self.assertRaises(ValueError):w.apply_document_numbering(ids)
        ui['filter']='';w.set_document_columns(['number','document_no']);self.assertTrue(ui['table'].isColumnHidden(0));self.assertTrue(w.settings.value('documents/hidden/document_no',False,type=bool))
        with self.assertRaises(ValueError):w.set_document_columns(['number','name'])
    def test_actual_tracking_dialog_cancel_save_and_undo(self):
        w=self.window;w.session.unlocked.add('deadline_tracking')
        def cancel():
            dialog=next(d for d in w.findChildren(QDialog) if d.isVisible());dialog.reject()
        QTimer.singleShot(0,cancel);w.edit_tracking(True);self.assertEqual(w.session.pages['deadline_tracking'],[])
        def save():
            dialog=next(d for d in w.findChildren(QDialog) if d.isVisible());dialog.findChild(QLineEdit,'tracking-due_date').setText('2026-10-20');dialog.findChild(QPlainTextEdit,'tracking-work').setPlainText('完成文件');dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(0,save);w.edit_tracking(True);self.assertEqual(w.session.pages['deadline_tracking'][0]['work'],'完成文件');w.session.undo('deadline_tracking');self.assertEqual(w.session.pages['deadline_tracking'],[])
    def test_save_reopen_backup_project_isolation(self):
        w=self.window;w.session.unlocked.add('deadline_tracking');w.commit_extra('deadline_tracking',[task()]);w.store.save(w.session.pages,0);payload=w.store.load();self.assertEqual(payload['pages']['deadline_tracking'][0],task())
        second=w.store.add_project('乙')['metadata']['project_id'];self.assertEqual(ProjectStore(self.path,second).load()['pages']['deadline_tracking'],[])
        archive=Path(self.temp.name)/'backup.zip';portable_backup(w.store,archive);restored=restore_backup(archive,Path(self.temp.name)/'restore');self.assertEqual(ProjectStore(restored,w.store.project_id).load()['pages']['deadline_tracking'],[task()])
    def test_schema8_import_readonly_and_defaults(self):
        w=self.window;source=Path(self.temp.name)/'old.db';p=ProjectStore.create(source,'舊庫');s=ProjectStore(source);file=Path(self.temp.name)/'old.txt';file.write_text('old');p['pages']['documents']['rows']=[new_asset(file)];p['pages']['diary']=[dict(id='old',number=1,date='2026-10-18',description='原始事記',note='')];s.save(p['pages'],0)
        import json
        with closing(sqlite3.connect(source)) as conn,conn:
            conn.execute("DELETE FROM pages WHERE page_id='deadline_tracking'");docs=json.loads(conn.execute("SELECT payload FROM pages WHERE page_id='documents'").fetchone()[0])
            for row in docs['rows']:
                for key in ['number','document_no','document_date']:row.pop(key)
            conn.execute("UPDATE pages SET payload=? WHERE page_id='documents'",(json.dumps(docs),));conn.execute('PRAGMA user_version=8')
        before=sha(source);preview=preview_database(source);self.assertEqual(sha(source),before);self.assertFalse(preview['projects'][0]['errors']);self.assertEqual(preview['projects'][0]['pages']['documents']['rows'][0]['number'],1)
        w.store.import_preview(preview);self.assertEqual(sha(source),before)
    def test_transaction_failure_keeps_deadlines(self):
        w=self.window;original=w.store.load();value=deepcopy(original['pages']);value['deadline_tracking']=[task(),task()]
        with self.assertRaises(ValueError):w.store.save(value,0)
        after=w.store.load();self.assertEqual(after['pages'],original['pages']);self.assertEqual(after['metadata']['revision'],'0')
    def test_document_edit_dialog_and_reopen(self):
        w=self.window;w.session.unlocked.add('documents');source=Path(self.temp.name)/'doc.txt';source.write_text('content');w.commit_extra('documents',dict(categories=[],rows=[new_asset(source)]));row=w.session.pages['documents']['rows'][0]
        def save():
            dialog=next(d for d in w.findChildren(QDialog) if d.isVisible());dialog.findChild(QLineEdit,'document-document_no').setText('001-甲');dialog.findChild(QLineEdit,'document-document_date').setText('2026-10-18');dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(0,save);w.edit_document(row);w.store.save(w.session.pages,0);loaded=w.store.load()['pages']['documents']['rows'][0];self.assertEqual(loaded['document_no'],'001-甲');self.assertEqual(loaded['document_date'],'2026-10-18');self.assertEqual(loaded['id'],row['id']);self.assertEqual(loaded['source'],row['source'])
    def test_renumber_cancel_preserves_business_data(self):
        w=self.window;w.session.unlocked.add('documents');source=Path(self.temp.name)/'doc.txt';source.write_text('content');w.commit_extra('documents',dict(categories=[],rows=[dict(new_asset(source),number=10)]));before=deepcopy(w.session.pages)
        with patch('traaduoduo.document_forms.QDialog.exec',return_value=QDialog.DialogCode.Rejected):w.renumber_documents()
        self.assertEqual(w.session.pages,before)
    def test_preferences_reopen_and_width_keys(self):
        w=self.window;w.set_document_columns(['document_no']);ui=w.asset_ui['documents'];ui['table'].setColumnWidth(w.asset_column('documents','name'),333);ui['sort'].setCurrentIndex(4);w.diary_tabs.setCurrentIndex(1)
        from traaduoduo.ui import Window
        other=Window(w.settings)
        try:
            self.assertTrue(other.asset_ui['documents']['table'].isColumnHidden(2));self.assertEqual(other.asset_ui['documents']['table'].columnWidth(1),333);self.assertEqual(other.asset_ui['documents']['sort'].currentIndex(),4);self.assertEqual(other.diary_tabs.currentIndex(),1)
        finally:other.close()
    def test_timer_survives_save_and_activation_refresh_is_nonmutating(self):
        w=self.window;w.save(auto=True);self.wait_io();self.assertTrue(w.deadline_timer.isActive());w._tracking_day=date(2000,1,1);before=deepcopy(w.session.pages);w._tracking_activation();self.assertEqual(w._tracking_day,date.today());self.assertEqual(w.session.pages,before)

# unittest inherits test_* methods; keep the shared fixture but select new tests only.
for _name in list(support.UITests.__dict__):
    if _name.startswith('test_'):setattr(TrackingUI,_name,None)
