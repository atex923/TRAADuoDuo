import os,time,unittest,hashlib
from copy import deepcopy
from pathlib import Path
from threading import Event
from unittest.mock import patch,MagicMock
from PySide6.QtCore import Qt,QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox,QLabel
import test_ui as support
from traaduoduo.store import default_pages
from traaduoduo.finance import normalize_costs,format_money
from traaduoduo.session import synchronize
from traaduoduo.aa_import import inspect_aa,AB_HEADERS
from traaduoduo.store import ProjectStore
from traaduoduo.billing import new_record

class Rules(unittest.TestCase):
    def test_net_totals_both_sides_and_no_double_tax(self):
        p=default_pages('未稅')
        for side in p['costs']['budget'],p['costs']['contract']:
            side.update(work='1000',work_tax='50',award_total='1050',labor='0',management_manual=True,management_adjustment='123.456',own_labor='20',unfinished_tax='50')
        q=synchronize(p)
        for k in ('budget','contract'):
            self.assertEqual(q['costs'][k]['unfinished'],'1143.456');self.assertEqual(q['costs'][k]['total'],'1193.456')
        p['costs']['contract']['unfinished_tax']='';self.assertEqual(synchronize(p)['costs']['contract']['unfinished'],'')
    def test_v080_formula_history_not_overwritten(self):
        old={'calculation_revision':2,'budget':{'unfinished':'123','total':'150'},'contract':{'unfinished':'456'}}
        q=normalize_costs(old);self.assertEqual(q['calculation_revision'],3);self.assertEqual(q['budget']['historical_v080'],old['budget']);self.assertEqual(normalize_costs(q)['budget']['historical_v080'],old['budget']);self.assertNotIn('historical_v080',old['budget'])
    def test_money_display(self):
        self.assertEqual(format_money('1234'),'1,234.00');self.assertEqual(format_money('1234.567'),'1,234.57');self.assertEqual(format_money('0'),'0.00');self.assertEqual(format_money(''),'')

@unittest.skipUnless(os.environ.get('TRAA_AB_TEST_SOURCE'),'Set TRAA_AB_TEST_SOURCE for supplied AB3155 read-only acceptance')
class SuppliedAB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=Path(os.environ['TRAA_AB_TEST_SOURCE']);cls.digest=hashlib.sha256(cls.path.read_bytes()).hexdigest();cls.batch=inspect_aa(cls.path)
    def test_layout_codes_and_original_formula(self):
        b=self.batch;self.assertEqual(b['input_format'],'AB3155');self.assertEqual(b['header_row'],4);self.assertEqual(b['source_headers'],AB_HEADERS);self.assertEqual(len(b['rows']),687);self.assertEqual(b['max_length'],7);self.assertFalse(b['errors']);self.assertEqual(b['rows'][0]['values'][2],'01');self.assertEqual(b['rows'][0]['values'][6],'2');self.assertEqual(b['rows'][0]['values'][11],'142723810');self.assertTrue(b['rows'][0]['formulas']);self.assertTrue(b['source_metadata']);self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.digest)
    def test_wrong_format_and_empty_sheet_rejected(self):
        with self.assertRaises(ValueError):inspect_aa(self.path,input_format='A3118')
        with self.assertRaises(ValueError):inspect_aa(self.path,sheet='工作表1')
        with self.assertRaises(ValueError):inspect_aa(self.path,header_row=1,input_format='AB3155')
    def test_save_reopen_preserves_all_source_fields(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            payload=ProjectStore.create(Path(d)/'qa.db','隔離');s=ProjectStore(Path(d)/'qa.db');p=payload['pages'];p['details']['budget']=[deepcopy(self.batch)];s.save(p,0)
            self.assertEqual(s.load()['pages']['details']['budget'][0],self.batch)

class UI(unittest.TestCase):
    setUp=support.UITests.setUp
    tearDown=support.UITests.tearDown
    wait_io=support.UITests.wait_io
    def test_manual_save_click_immediate_not_idle(self):
        w=self.window;w.toggle_lock('basic');w.fields['number'].setFocus();QTest.keyClicks(w.fields['number'],'NOW');self.assertTrue(w.autosave.isActive());start=time.monotonic();w.save_button.click();self.wait_io();self.assertLess(time.monotonic()-start,3);self.assertEqual(ProjectStore(self.path).load()['pages']['basic']['number'],'NOW');self.assertFalse(w.session.dirty());self.assertFalse(w.autosave.isActive())
    def test_manual_save_during_io_not_dropped(self):
        w=self.window;w.toggle_lock('basic');w.fields['number'].setText('QUEUED');gate=Event();w.io(lambda:gate.wait(2),lambda _:None);w.save();self.assertTrue(w._manual_save_requested);gate.set();self.wait_io();self.assertEqual(w.store.load()['pages']['basic']['number'],'QUEUED')
    def test_manual_save_commits_active_table_editor(self):
        from PySide6.QtWidgets import QPlainTextEdit
        w=self.window;w.session.unlocked.add('diary');w.commit_extra('diary',[dict(id='d',number=1,date='2026-10-23',description='原文',note='')]);w.tabs.setCurrentIndex(4);w.diary_tabs.setCurrentIndex(0);w.update_actions();w.diary_table.setCurrentCell(0,1);w.diary_table.editItem(w.diary_table.item(0,1));support.APP.processEvents();editor=w.diary_table.findChild(QPlainTextEdit);self.assertIsNotNone(editor);editor.setPlainText('編輯器尚未離開');editor.setFocus();w.save_button.click();self.wait_io();self.assertEqual(w.store.load()['pages']['diary'][0]['description'],'編輯器尚未離開')
    def test_cost_display_no_precision_loss_extensions(self):
        w=self.window;w.session.unlocked.add('costs');p=deepcopy(w.session.pages);p['costs']['budget'].update(labor='0',work='100',work_tax='5',unfinished_tax='0',management_manual=True,management_adjustment='12.3456',own_labor='1.23456');p['costs']['extensions']=[dict(id='e',label='附加',budget='9.87654',contract='0')];w.session.pages=synchronize(p);w.populate_finance();self.assertEqual(w.cost_fields['budget']['management_amount'].text(),'12.35');self.assertEqual(w.cost_fields['budget']['own_labor'].value(),'1.23456');w.capture_extensions('budget');w.capture_costs();self.assertEqual(w.session.pages['costs']['extensions'][0]['budget'],'9.87654');self.assertEqual(w.session.pages['costs']['budget']['own_labor'],'1.23456');self.assertTrue(any(l.text()=='(未稅)' for l in w.findChildren(QLabel)))
        from PySide6.QtCore import QLocale
        from PySide6.QtWidgets import QLineEdit
        t=w.extension_tables['budget'];delegate=t.itemDelegateForColumn(1);self.assertEqual(delegate.displayText('1234',QLocale()),'1,234.00');e=QLineEdit();delegate.setEditorData(e,t.model().index(0,1));self.assertEqual(e.text(),'9.87654')
    def test_delete_budget_revision_cancel_confirm_undo(self):
        w=self.window;w.session.unlocked.add('details');b=dict(id='b',filename='qa.xlsx',name='測試修訂版',sha256='x',sheet='工作表',rows=[],errors=[],warnings=[],max_length=0);v=deepcopy(w.session.pages['details']);v['budget']=[b];v['contract']=[dict(b,id='c')];w.commit_extra('details',v)
        with patch('traaduoduo.advanced_forms.QMessageBox.question',return_value=QMessageBox.StandardButton.No):w.delete_detail_revision('budget')
        self.assertEqual(len(w.session.pages['details']['budget']),1)
        with patch('traaduoduo.advanced_forms.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):w.delete_detail_revision('budget')
        self.assertEqual(w.session.pages['details']['budget'],[]);self.assertEqual(len(w.session.pages['details']['contract']),1);w.tabs.setCurrentIndex(3);w.undo();self.assertEqual(w.session.pages['details']['budget'][0]['id'],'b')
    def test_locked_delete_does_nothing(self):
        w=self.window;old=deepcopy(w.session.pages);w.delete_detail_revision('budget');self.assertEqual(w.session.pages,old)
    def test_billing_alignment_all_tables_and_allocations(self):
        w=self.window
        for key in w.payment_columns:
            row=new_record(key,'a',1)
            if key=='admin_payments':w.session.pages[key]['rows']=[row]
            else:w.session.pages[key]=[row]
        w.populate_billing()
        for key,table in w.payment_tables.items():
            for c,(field,_) in enumerate(w.payment_columns[key]):
                a=table.item(0,c).textAlignment();numeric=field in ('amount','tax','paid','paid_tax','estimated','retention','0C12','0C11','0C14')
                if numeric:self.assertTrue(a & Qt.AlignmentFlag.AlignRight)
                elif field in ('period','payment_date','note'):self.assertTrue(a & Qt.AlignmentFlag.AlignHCenter)
        for c in range(10):self.assertTrue(w.allocation_table.item(0,c).textAlignment() & (Qt.AlignmentFlag.AlignRight if 2<=c<=8 else Qt.AlignmentFlag.AlignHCenter))
    def test_windows_titlebar_button_order_and_minimize_distinction(self):
        w=self.window;fake=MagicMock();fake.isVisible.return_value=True
        with patch('traaduoduo.desktop_features.sys.platform','win32'),patch('traaduoduo.desktop_features.QSystemTrayIcon') as tray:
            tray.return_value=fake;tray.isSystemTrayAvailable.return_value=True;w.install_tray();self.assertEqual([b.text() for b in w.custom_titlebar.buttons],['_','─','□','×'])
            with patch.object(w,'hide') as hide:w.changeEvent(QEvent(QEvent.Type.WindowStateChange));self.assertFalse(hide.called);w.custom_titlebar.buttons[0].click();self.assertTrue(hide.called)
            tray.isSystemTrayAvailable.return_value=False
            with patch.object(w,'showMinimized') as mini,patch.object(w,'hide') as hide:w.minimize_to_tray();self.assertTrue(mini.called);self.assertFalse(hide.called)
        w.tray=None
