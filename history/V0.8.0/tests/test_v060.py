"""V0.6 acceptance. All mutations use isolated databases and generated files."""
import os
import json
import hashlib
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from PySide6.QtCore import QSettings,Qt,QDate,QPoint,QSize
from PySide6.QtGui import QImage,QPainter,QPdfWriter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTableView,QMessageBox
import test_ui as support
from traaduoduo.store import ProjectStore,default_pages
from traaduoduo.session import EditSession
from traaduoduo.advanced_data import validate_extra
from traaduoduo.aa_import import inspect_aa,format_decimal
from traaduoduo.asset_store import new_asset,inventory,available_path,managed_path,portable_backup,restore_backup,sha
from traaduoduo.finance import management_fee
from traaduoduo.billing import new_record
from traaduoduo.ui import Window
from traaduoduo.importer import preview_database

class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.database=self.root/'source.db'
        self.payload=ProjectStore.create(self.database,'來源工程');self.pid=self.payload['metadata']['project_id'];self.store=ProjectStore(self.database,self.pid)
        self.source=self.root/'檔案.txt';self.source.write_bytes(b'original content')
    def tearDown(self):self.temp.cleanup()
    def test_verified_stock_preserves_original_and_creates_relative_path(self):
        row=new_asset(self.source);original=deepcopy(row);stock=inventory(self.database,self.pid,'documents',row)
        self.assertEqual(row,original);self.assertTrue(stock['stock']);self.assertFalse(Path(stock['managed']).is_absolute())
        self.assertEqual(sha(available_path(self.database,stock)),sha(self.source));self.assertEqual(self.source.read_bytes(),b'original content')
    def test_new_version_retained_and_uncheck_keeps_files(self):
        row=inventory(self.database,self.pid,'documents',new_asset(self.source));old=managed_path(self.database,row['managed'])
        self.source.write_bytes(b'updated content');updated=inventory(self.database,self.pid,'documents',row)
        self.assertEqual(len(updated['versions']),1);self.assertTrue(old.exists());self.assertNotEqual(updated['managed'],row['managed'])
        updated['stock']=False;self.assertEqual(available_path(self.database,updated),self.source);self.assertTrue(old.exists())
    def test_missing_source_and_unsafe_paths_refused(self):
        row=new_asset(self.source);self.source.unlink()
        with self.assertRaises(ValueError):inventory(self.database,self.pid,'documents',row)
        with self.assertRaises(ValueError):managed_path(self.database,'../private.txt')
    def test_same_names_and_cross_project_do_not_collide(self):
        row=new_asset(self.source);other=self.store.add_project('第二工程')['metadata']['project_id']
        first=inventory(self.database,self.pid,'documents',row);second=inventory(self.database,other,'documents',new_asset(self.source))
        self.assertEqual(first['managed'],second['managed']);self.assertTrue(available_path(self.database,first).exists())
    def test_portable_roundtrip_contains_inventory_and_lists_external(self):
        stock=inventory(self.database,self.pid,'documents',new_asset(self.source));link=new_asset(self.source)
        self.store.save({'documents':dict(categories=[],rows=[stock,link])},0)
        backup=self.root/'backup.zip';result=portable_backup(self.store,backup);self.assertEqual(result['external'],1)
        restored=restore_backup(backup,self.root/'restored');payload=ProjectStore(restored).load()
        self.assertEqual(sha(available_path(restored,payload['pages']['documents']['rows'][0])),stock['sha256'])
        with self.assertRaises(ValueError):restore_backup(backup,self.root/'restored')
    def test_backup_missing_inventory_never_claims_success(self):
        stock=inventory(self.database,self.pid,'documents',new_asset(self.source));self.store.save({'documents':dict(categories=[],rows=[stock])},0)
        managed_path(self.database,stock['managed']).unlink();target=self.root/'bad.zip'
        with self.assertRaises(ValueError):portable_backup(self.store,target)
        self.assertFalse(target.exists())
    def test_restore_rejects_corrupted_manifest_and_leaves_no_destination(self):
        target=self.root/'bad.zip'
        with ZipFile(target,'w') as archive:
            archive.writestr('manifest.json',json.dumps(dict(format='TRAADuoDuo-portable-1',database='library.db',files={'../escape':'123'})))
        with self.assertRaises(ValueError):restore_backup(target,self.root/'restored')
        self.assertFalse((self.root/'restored').exists());self.assertFalse((self.root.parent/'escape').exists())
    def test_import_inventory_turns_into_readonly_source_link(self):
        stock=inventory(self.database,self.pid,'documents',new_asset(self.source));self.store.save({'documents':dict(categories=[],rows=[stock])},0)
        digest=sha(self.database);preview=preview_database(self.database);row=preview['projects'][0]['pages']['documents']['rows'][0]
        self.assertFalse(row['stock']);self.assertEqual(row['managed'],'');self.assertEqual(Path(row['source']),managed_path(self.database,stock['managed']));self.assertEqual(sha(self.database),digest)
    def test_tree_cycles_and_duplicate_diary_numbers_rejected(self):
        with self.assertRaises(ValueError):validate_extra('documents',dict(categories=[dict(id='a',parent='b'),dict(id='b',parent='a')],rows=[]))
        rows=[dict(id='a',number=1,date='2026-10-17'),dict(id='b',number=1,date='2026-10-18')]
        with self.assertRaises(ValueError):validate_extra('diary',rows)
    def test_schema7_import_keeps_old_source(self):
        with self.store.connect() as conn:
            conn.execute("DELETE FROM pages WHERE page_id IN ('documents','photos','details','diary')");conn.execute('PRAGMA user_version=7')
        digest=sha(self.database);preview=preview_database(self.database);self.assertEqual(preview['projects'][0]['pages']['diary'],[]);self.assertEqual(sha(self.database),digest)

class NewUITests(unittest.TestCase):
    setUp=support.UITests.setUp
    wait_io=support.UITests.wait_io
    def tearDown(self):
        w=self.window;w.capture_basic();w.autosave.stop();self.wait_io()
        w.session.saved=deepcopy(w.session.pages)
        with patch('traaduoduo.ui.QMessageBox.question',return_value=QMessageBox.StandardButton.Discard):w.close()
        self.temp.cleanup()
    def test_new_tabs_and_common_form_sizes(self):
        w=self.window;self.assertEqual(w.basic_tabs.tabText(0),'契約執行');self.assertEqual(w.detail_tabs.count(),4)
        self.assertEqual(w.fields['name'].width(),360);self.assertEqual(w.fields['number'].width(),240)
        self.assertEqual(w.fields['description'].width(),360)
        self.assertEqual(w.calendar_tabs.tabText(0),'假期補班與疏運表')
        self.assertTrue(all(not b.isVisible() for b in w.extension_toggles.values()))
    def test_width_memory_across_windows_and_projects(self):
        w=self.window;settings=w.settings;field=w.fields['number'];field.setFixedWidth(333);w.layout_settings.remember('basic/number',333)
        w.payment_tables['contract_payments'].setColumnWidth(0,127)
        second=w.store.add_project('乙工程');w.adopt(second);self.assertEqual(field.width(),333)
        other=Window(settings);self.assertEqual(other.fields['number'].width(),333);self.assertEqual(other.payment_tables['contract_payments'].columnWidth(0),127)
        other.close()
    def test_real_mouse_drag_form_width_and_reset(self):
        w=self.window;field=w.fields['number'];width=field.width()
        QTest.mousePress(field,Qt.MouseButton.LeftButton,pos=QPoint(width-2,15));QTest.mouseMove(field,QPoint(width+38,15));QTest.mouseRelease(field,Qt.MouseButton.LeftButton,pos=QPoint(width+38,15))
        self.assertGreater(field.width(),width);self.assertEqual(int(w.settings.value('widths/basic/number')),field.width())
        w.layout_settings.reset();self.assertEqual(field.width(),240)
    def test_numeric_period_sort_both_orders_and_summary_16pt(self):
        w=self.window;rows=[dict(new_record('contract_payments','row'+str(p),p),amount=str(p)) for p in [10,2,1,11,3,20,9]]
        w.session.pages['contract_payments']=rows;w.populate_billing();table=w.payment_tables['contract_payments']
        self.assertEqual([int(table.item(i,0).text()) for i in range(7)],[1,2,3,9,10,11,20])
        table.sortItems(0,Qt.SortOrder.DescendingOrder);self.assertEqual([int(table.item(i,0).text()) for i in range(7)],[20,11,10,9,3,2,1])
        self.assertEqual(w.payment_summaries['contract_payments'].font().pointSize(),16)
    def test_calendar_week_row_exact_padding(self):
        w=self.window;w.tabs.setCurrentIndex(1);w.calendar_tabs.setCurrentWidget(w.calendar_page);support.APP.processEvents();w.calendar.compact_rows()
        view=w.calendar.findChild(QTableView,'qt_calendar_calendarview');self.assertEqual(view.rowHeight(0),view.fontMetrics().height()+round(3*w.calendar.logicalDpiY()/72))
    def test_calendar_initial_fill_and_user_width_persistence(self):
        w=self.window;w.tabs.setCurrentIndex(1);w.calendar_tabs.setCurrentWidget(w.calendar_page);support.APP.processEvents();w.calendar.compact_rows()
        view=w.calendar.findChild(QTableView,'qt_calendar_calendarview')
        self.assertGreaterEqual(sum(view.columnWidth(c) for c in range(view.model().columnCount())),view.viewport().width()-10)
        original=view.columnWidth(1);x=view.columnViewportPosition(1)+original-2
        QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=QPoint(x,10));QTest.mouseMove(view.viewport(),QPoint(x+45,10));QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=QPoint(x+45,10))
        self.assertEqual(view.columnWidth(1),original+45)
        w.resize(1400,950);support.APP.processEvents();w.calendar.compact_rows();self.assertEqual(view.columnWidth(1),original+45)
        other=Window(w.settings);other.tabs.setCurrentIndex(1);other.calendar_tabs.setCurrentWidget(other.calendar_page);other.show();support.APP.processEvents();other.calendar.compact_rows()
        self.assertEqual(other.calendar.findChild(QTableView,'qt_calendar_calendarview').columnWidth(1),original+45);other.close()
        w.layout_settings.reset();self.assertGreaterEqual(sum(view.columnWidth(c) for c in range(view.model().columnCount())),view.viewport().width()-10)
    def test_diary_inline_edit_and_variable_height_preserved(self):
        w=self.window;w.session.unlocked.add('diary');rows=[dict(id='diary1',number=1,date='2026-10-17',description='記錄',note='')];w.commit_extra('diary',rows)
        w.diary_table.item(0,1).setText('測試說明'*120);self.assertEqual(w.session.pages['diary'][0]['description'],'測試說明'*120);self.assertGreater(w.diary_table.rowHeight(0),42)
        w.store.save({'diary':w.session.pages['diary']},0);self.assertEqual(ProjectStore(self.path).load()['pages']['diary'][0]['id'],'diary1')
    def test_stock_checkbox_runs_verified_copy_and_uncheck_keeps_original(self):
        w=self.window;source=Path(self.temp.name)/'doc.txt';source.write_text('content');w.session.unlocked.add('documents')
        w.commit_extra('documents',dict(categories=[],rows=[new_asset(source)]));table=w.asset_ui['documents']['table']
        table.item(0,w.asset_column('documents','stock')).setCheckState(Qt.CheckState.Checked);self.wait_io();row=w.session.pages['documents']['rows'][0]
        self.assertTrue(row['stock']);managed=available_path(self.path,row);self.assertTrue(managed.exists())
        table.item(0,w.asset_column('documents','stock')).setCheckState(Qt.CheckState.Unchecked);self.assertFalse(w.session.pages['documents']['rows'][0]['stock']);self.assertTrue(managed.exists());self.assertTrue(source.exists())
    def test_award_star_center_and_extension_delete_undo(self):
        w=self.window;bid=dict(id='b',number=1,awarded=True,review_start='',review_end='',online_start='',online_end='',opening='',committee='',award_date='2026-10-17');w.session.pages['bids']=[bid];w.populate_bids()
        self.assertEqual(w.bid_table.item(0,0).text(),'＊');self.assertEqual(w.bid_table.item(0,0).textAlignment(),Qt.AlignmentFlag.AlignCenter)
        w.session.unlocked.add('costs');w.session.pages['costs']['extensions']=[dict(id='e',label='新增費用',budget='10',contract='20')]
        with patch('traaduoduo.finance_forms.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):w.remove_extension('e')
        self.assertEqual(w.session.pages['costs']['extensions'],[]);w.session.undo('costs');self.assertEqual(w.session.pages['costs']['extensions'][0]['budget'],'10')
    def test_pdf_bookmark_and_highlight_dont_modify_source(self):
        w=self.window;source=Path(self.temp.name)/'sample.pdf';writer=QPdfWriter(str(source));painter=QPainter(writer);painter.drawText(200,200,'read only PDF');painter.end();del writer
        digest=sha(source);w.session.unlocked.add('documents');row=new_asset(source);w.commit_extra('documents',dict(categories=[],rows=[row]));w.asset_ui['documents']['table'].setCurrentCell(0,0);w.preview_asset('documents');reader=w.asset_ui['documents']['pdf']
        self.assertEqual(reader.doc.pageCount(),1)
        with patch('traaduoduo.pdf_reader.QInputDialog.getText',return_value=('重點',True)):reader.add_bookmark()
        reader.highlight.setChecked(True);page=reader.pages[0]
        QTest.mousePress(page,Qt.MouseButton.LeftButton,pos=QPoint(50,50));QTest.mouseRelease(page,Qt.MouseButton.LeftButton,pos=QPoint(150,90))
        notes=w.session.pages['documents']['rows'][0]['annotations']
        self.assertEqual(notes['bookmarks'][0]['name'],'重點');self.assertEqual(len(notes['highlights']),1);self.assertEqual(sha(source),digest)

class PrecisionTests(unittest.TestCase):
    def test_round_yuan_does_not_change_raw_thousand_cutoff(self):
        side=default_pages('計算')['costs']['budget'];side['labor']='5039999.2';r=management_fee(side,'budget')
        self.assertEqual(r['total'],Decimal('150600'));self.assertEqual(r['default'],Decimal('150000'))
    def test_display_two_decimals_retains_input(self):
        value='2086.9999999999995';self.assertEqual(format_decimal(value),'2,087.00');self.assertEqual(value,'2086.9999999999995')

@unittest.skipUnless(os.environ.get('TRAA_AA_TEST_SOURCE'),'Set TRAA_AA_TEST_SOURCE for read-only supplied-workbook acceptance')
class SuppliedAA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=Path(os.environ['TRAA_AA_TEST_SOURCE']);cls.digest=sha(cls.path);cls.batch=inspect_aa(cls.path)
    def test_rows_codes_and_no_source_changes(self):
        self.assertEqual(len(self.batch['rows']),678);self.assertFalse(self.batch['errors']);self.assertEqual(self.batch['max_length'],7);self.assertEqual(sha(self.path),self.digest)
        self.assertEqual(sum(r['analysis'] for r in self.batch['rows']),468);self.assertTrue(any(r['values'][2]=='011125A' for r in self.batch['rows']))
    def test_shared_formulas_caches_and_unlabeled_column_retained(self):
        formulas=[value for r in self.batch['rows'] for value in r['formulas'].values()];self.assertEqual(len(formulas),187)
        self.assertTrue(all(r['extra'] for r in self.batch['rows']));self.assertTrue(any(v['formula']=='=J8*K8' for v in formulas))
    def test_short_leaves_and_unit_price_build(self):
        self.assertEqual(sum(r['leaf'] for r in self.batch['rows']),549)
        row=next(r for r in self.batch['rows'] if r['values'][2]=='011111');children=[r for r in self.batch['rows'] if r['parent_id']==row['id']]
        self.assertEqual(sum(Decimal(r['values'][11]) for r in children),Decimal(row['values'][10]))
    def test_import_transaction_and_reopen_project_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'library.db';ProjectStore.create(path,'甲');store=ProjectStore(path);pages=store.load()['pages'];pages['details']['budget'].append(self.batch);store.save({'details':pages['details']},0)
            self.assertEqual(len(store.load()['pages']['details']['budget'][0]['rows']),678)
            second=store.add_project('乙');self.assertEqual(second['pages']['details']['budget'],[])
