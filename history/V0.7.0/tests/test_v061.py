"""V0.6.1 behavior and data-preservation acceptance, isolated fixtures only."""
from concurrent.futures import ThreadPoolExecutor,CancelledError
from copy import deepcopy
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from PySide6.QtCore import Qt,QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox,QLabel
import test_ui as support
from traaduoduo.store import ProjectStore,default_pages
from traaduoduo.asset_store import inventory,new_asset,sha,managed_path,portable_backup,restore_backup,available_path
from traaduoduo.billing import new_record,contract_progress
from traaduoduo.finance import management_fee
from traaduoduo.presentation import MoneyField


class ContentReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.database=self.root/'library.db';payload=ProjectStore.create(self.database,'甲')
        self.pid=payload['metadata']['project_id'];self.store=ProjectStore(self.database,self.pid)
        self.source=self.root/'sample.txt';self.source.write_bytes(b'content-A')
    def tearDown(self):self.temp.cleanup()
    def stock(self,source=None,row=None,key='documents',pid=None):
        return inventory(self.database,pid or self.pid,key,row or new_asset(source or self.source))
    def test_same_content_different_name_and_project_and_library_type(self):
        first=self.stock();alias=self.root/'photo.png';alias.write_bytes(self.source.read_bytes())
        pid=self.store.add_project('乙')['metadata']['project_id'];second=self.stock(alias,key='photos',pid=pid)
        self.assertEqual(first['managed'],second['managed']);self.assertNotEqual(first['name'],second['name'])
        self.assertTrue(second['inventory_reused']);self.assertEqual(len(list((self.root/'Docstore').rglob('sample.txt'))),1)
    def test_repeated_inventory_does_not_add_identical_versions(self):
        first=self.stock();again=self.stock(row=first)
        self.assertEqual(again['managed'],first['managed']);self.assertEqual(again['versions'],[])
        self.assertTrue(again['inventory_reused'])
    def test_different_content_same_filename_keeps_both_and_history(self):
        first=self.stock();self.source.write_bytes(b'content-B');second=self.stock(row=first)
        self.assertNotEqual(first['managed'],second['managed']);self.assertEqual(len(second['versions']),1)
        self.assertEqual(available_path(self.database,first).read_bytes(),b'content-A')
    def test_source_already_in_inventory_is_reused(self):
        first=self.stock();again=self.stock(available_path(self.database,first))
        self.assertEqual(again['managed'],first['managed']);self.assertTrue(again['inventory_reused'])
    def test_corrupted_candidate_is_preserved_not_reused(self):
        first=self.stock();damaged=available_path(self.database,first);damaged.write_bytes(b'corrupted')
        again=self.stock();self.assertNotEqual(first['managed'],again['managed'])
        self.assertEqual(damaged.read_bytes(),b'corrupted');self.assertEqual(sha(available_path(self.database,again)),sha(self.source))
    def test_missing_candidate_and_broken_index_rebuild(self):
        first=self.stock();path=available_path(self.database,first);root=path.parents[3]
        (root/'.content-index.json').write_text('broken')
        second=self.stock();self.assertEqual(first['managed'],second['managed'])
        path.unlink();third=self.stock();self.assertTrue(available_path(self.database,third).exists())
    def test_legacy_unindexed_content_in_same_library_reused(self):
        first=self.stock();path=available_path(self.database,first);root=path.parents[3]
        legacy=root/self.pid/'文件'/'old'/'old.txt';legacy.parent.mkdir(parents=True);path.rename(legacy)
        again=self.stock();self.assertEqual(available_path(self.database,again),legacy)
    def test_two_workers_create_one_object(self):
        row1=new_asset(self.source);row2=new_asset(self.source)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda row:self.stock(row=row),[row1,row2]))
        self.assertEqual(results[0]['managed'],results[1]['managed'])
        self.assertEqual(sum(bool(r['inventory_reused']) for r in results),1)
    def test_cancel_does_not_create_successful_inventory(self):
        cancel=Event();cancel.set();row=new_asset(self.source);original=deepcopy(row)
        with self.assertRaises(CancelledError):inventory(self.database,self.pid,'documents',row,cancel)
        self.assertEqual(row,original);self.assertFalse((self.root/'Docstore').exists())
    def test_cancel_during_copy_and_disk_failure_keep_source_and_no_partials(self):
        original=sha(self.source)
        with patch('traaduoduo.asset_store.os.fsync',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.stock()
        self.assertEqual(sha(self.source),original);self.assertEqual(list((self.root/'Docstore').rglob('*.partial')),[])
    def test_cancel_after_copy_does_not_publish_file(self):
        cancel=Event();row=new_asset(self.source)
        from traaduoduo import asset_store
        real=asset_store.sha
        def cancelling(path,event=None):
            if str(path).endswith('.partial'):cancel.set()
            return real(path,event)
        with patch('traaduoduo.asset_store.sha',side_effect=cancelling):
            with self.assertRaises(CancelledError):inventory(self.database,self.pid,'documents',row,cancel)
        self.assertFalse(row['stock']);self.assertEqual(list((self.root/'Docstore').rglob('*.partial')),[])
        self.assertEqual(list((self.root/'Docstore').rglob('sample.txt')),[])
    def test_index_outside_library_never_reused_and_other_library_isolated(self):
        first=self.stock();root=available_path(self.database,first).parents[3]
        import json
        (root/'.content-index.json').write_text(json.dumps({first['sha256']:[str(self.source)]}))
        again=self.stock();self.assertEqual(again['managed'],first['managed'])
        other_dir=self.root/'other-library';other_dir.mkdir();db=other_dir/'library.db';p=ProjectStore.create(db,'隔離庫')
        other=inventory(db,p['metadata']['project_id'],'documents',new_asset(self.source))
        self.assertNotEqual(available_path(db,other),available_path(self.database,first));self.assertFalse(other['inventory_reused'])
    def test_source_change_during_copy_fails_without_publishing(self):
        from traaduoduo import asset_store
        row=new_asset(self.source);real=asset_store.sha;calls=0
        def changing(path,cancel=None):
            nonlocal calls
            calls+=1
            if calls==2:self.source.write_bytes(b'modified')
            return real(path,cancel)
        with patch('traaduoduo.asset_store.sha',side_effect=changing):
            with self.assertRaises(ValueError):self.stock(row=row)
        self.assertEqual(list((self.root/'Docstore').rglob('sample.txt')),[])
    def test_shared_reference_roundtrip_and_remove_one_never_deletes(self):
        first=self.stock();second=self.stock(key='photos')
        self.store.save({'documents':dict(categories=[],rows=[first]),'photos':dict(categories=[],rows=[second])},0)
        archive=self.root/'full.zip';portable_backup(self.store,archive)
        with ZipFile(archive) as z:
            self.assertEqual(sum(name.startswith('Docstore/') for name in z.namelist()),1)
        restored=restore_backup(archive,self.root/'restored');store=ProjectStore(restored);p=store.load()
        self.assertEqual(p['pages']['documents']['rows'][0]['managed'],p['pages']['photos']['rows'][0]['managed'])
        store.save({'documents':dict(categories=[],rows=[])},int(p['metadata']['revision']))
        self.assertTrue(available_path(restored,store.load()['pages']['photos']['rows'][0]).exists())


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.pages=default_pages('計價');self.pages['costs']['contract']['award_total']='210'
        self.pages['contract_payments']=[dict(new_record('contract_payments','a',1),amount='100',tax='5'),dict(new_record('contract_payments','b',10),amount='100',tax='5')]
    def test_tax_inclusive_same_period_and_all(self):
        self.assertEqual(contract_progress(self.pages,1),'50.00%');self.assertEqual(contract_progress(self.pages),'100.00%')
        self.assertEqual(contract_progress(self.pages,0),'0.00%')
    def test_zero_missing_and_overrun(self):
        self.pages['costs']['contract']['award_total']=''
        self.assertIn('未設定',contract_progress(self.pages))
        self.pages['costs']['contract']['award_total']='0';self.assertIn('為 0',contract_progress(self.pages))
        self.pages['costs']['contract']['award_total']='100';self.assertIn('210.00%',contract_progress(self.pages))
    def test_no_tax_rate_guessed_and_negative_retained(self):
        self.pages['contract_payments'][0]['tax']=''
        self.assertEqual(contract_progress(self.pages,1),'47.62%')
        self.pages['contract_payments'][0]['amount']='-100';self.assertIn('-47.62%',contract_progress(self.pages,1))


class RevisionUITests(unittest.TestCase):
    setUp=support.UITests.setUp
    wait_io=support.UITests.wait_io
    def tearDown(self):
        w=self.window;w.autosave.stop();self.wait_io();w.session.saved=deepcopy(w.session.pages)
        with patch('traaduoduo.ui.QMessageBox.question',return_value=QMessageBox.StandardButton.Discard):w.close()
        self.temp.cleanup()
    def test_compact_field_height_alignment_and_width_memory(self):
        w=self.window
        for side in ('budget','contract'):
            field=w.cost_fields[side]['award_total'];subtotal=w.cost_fields[side]['non_labor']
            self.assertEqual(field.height(),field.fontMetrics().height()+round(3*field.logicalDpiY()/72))
            self.assertEqual(subtotal.height(),field.height());self.assertEqual(subtotal.width(),field.width());self.assertTrue(subtotal.isReadOnly())
            label=next(x for x in w.findChildren(QLabel) if x.text()=='包工費以外');self.assertIn('16pt',label.styleSheet())
    def test_management_two_decimals_and_no_calculation_change(self):
        w=self.window;w.session.unlocked.add('costs');w.cost_fields['budget']['award_total'].setText('5039999.2');w.capture_costs();w.refresh_finance()
        self.assertEqual(w.fee_labels['budget'][-1].text(),'150,600.00')
        self.assertEqual(w.cost_fields['budget']['management_adjustment'].text(),'150,000.00')
        self.assertEqual(management_fee(w.session.pages['costs']['budget'],'budget')['default'],150000)
    def test_guarantee_raw_decimal_survives_format_focus_and_save(self):
        w=self.window;w.session.unlocked.add('guarantees');field=w.guarantee_fields['bid_amount']
        w.session.pages['guarantees']['bid_amount']='1234.567';w.populate_stage_forms();w.update_actions()
        self.assertEqual(field.text(),'1,235');w.capture_form('guarantees')
        self.assertEqual(w.session.pages['guarantees']['bid_amount'],'1234.567')
        field.setFocus();support.APP.processEvents();w.fields['name'].setFocus();support.APP.processEvents();w.capture_form('guarantees')
        self.assertEqual(w.session.pages['guarantees']['bid_amount'],'1234.567')
        w.store.save({'guarantees':w.session.pages['guarantees']},0)
        self.assertEqual(w.store.load()['pages']['guarantees']['bid_amount'],'1234.567')
    def test_merged_three_tables_and_key_based_undo_selection(self):
        w=self.window;w.tabs.setCurrentIndex(1);w.calendar_tabs.setCurrentIndex(0)
        self.assertEqual(w.calendar_tabs.count(),3)
        for key in ('holidays','makeup','railway'):
            w.toggle_lock(key);self.assertEqual(w.current_page(),key)
            self.assertTrue(w.calendar_tabs.currentWidget().isAncestorOf(w.tables[key]))
        w.calendar_tabs.setCurrentIndex(1);self.assertEqual(w.current_page(),'weather')
        w.calendar_tabs.setCurrentWidget(w.calendar_page);self.assertIsNone(w.current_page())
    def test_calendar_stops_after_duration_preserves_events_and_recalculates(self):
        w=self.window;w.session.pages['basic'].update(start='2026-10-05',days='2')
        w.session.pages['weather']=[['2026-10-06','0','.5','','0']]
        w.session.pages['railway']=[['2026-10-08','疏運']]
        w.tabs.setCurrentIndex(1);w.calendar_tabs.setCurrentWidget(w.calendar_page);w.calendar.setSelectedDate(QDate(2026,10,8));w.refresh_calendar()
        details=w.calendar.day_details
        self.assertEqual(details['2026-10-05']['work'],'1');self.assertEqual(details['2026-10-06']['work'],'1.5')
        self.assertEqual(details['2026-10-07']['work'],'2');self.assertEqual(details['2026-10-08']['work'],'')
        self.assertEqual(details['2026-10-08']['railway'],'疏運');self.assertEqual(details['2026-10-08']['daily'],'')
        self.assertIn('已達契約工期',w.calendar_summary.text());self.assertNotIn('選取日累計',w.calendar_summary.text())
        w.session.pages['basic']['days']='4';w.refresh_calendar();self.assertNotEqual(w.calendar.day_details['2026-10-09']['work'],'')
    def test_calendar_no_duration_and_cross_month_finish(self):
        w=self.window;w.tabs.setCurrentIndex(1);w.calendar_tabs.setCurrentWidget(w.calendar_page)
        w.session.pages['basic'].update(start='2026-10-30',days='2');w.calendar.setSelectedDate(QDate(2026,11,3));w.refresh_calendar()
        self.assertEqual(w.calendar.day_details['2026-11-02']['work'],'2');self.assertEqual(w.calendar.day_details['2026-11-03']['work'],'')
        w.session.pages['basic']['days']='0';w.refresh_calendar();self.assertTrue(all(not d['work'] for d in w.calendar.day_details.values()))
    def test_bid_date_ranges_single_line_and_centered(self):
        w=self.window;row=dict(id='bid',number=1,awarded=False,review_start='2026-10-01',review_end='2026-10-03',online_start='2026-10-05',online_end='2026-10-07',opening='2026-10-10',committee='',award_date='')
        w.session.pages['bids']=[row];w.populate_bids();self.assertFalse(w.bid_table.wordWrap())
        for col in range(7):self.assertNotIn('\n',w.bid_table.item(0,col).text());self.assertEqual(w.bid_table.item(0,col).textAlignment(),Qt.AlignmentFlag.AlignCenter)
        self.assertGreaterEqual(w.bid_table.columnWidth(2),w.bid_table.fontMetrics().horizontalAdvance(w.bid_table.item(0,2).text())+12)
    def test_count_labels_moved_and_tax_inclusive_progress_second_line(self):
        w=self.window;w.session.pages['costs']['contract']['award_total']='210'
        w.session.pages['contract_payments']=[dict(new_record('contract_payments','a',1),amount='100',tax='5')];w.populate_billing()
        for key in ('contract_payments','other_payments'):
            self.assertIn('紀錄 ',w.payment_counts[key].text());self.assertNotIn('紀錄 ',w.payment_summaries[key].text())
        self.assertIn('\n累計計價進度：50.00%',w.payment_summaries['contract_payments'].text())
    def test_stock_ui_reuses_file_and_preserves_other_record_after_removal(self):
        w=self.window;source=Path(self.temp.name)/'asset.txt';source.write_bytes(b'content')
        w.session.unlocked.update(('documents','photos'));w.commit_extra('documents',dict(categories=[],rows=[new_asset(source)]))
        w.commit_extra('photos',dict(categories=[],rows=[new_asset(source)]))
        for key in ('documents','photos'):
            w.asset_ui[key]['table'].item(0,w.asset_column(key,'stock')).setCheckState(Qt.CheckState.Checked);self.wait_io()
        first=w.session.pages['documents']['rows'][0];second=w.session.pages['photos']['rows'][0]
        self.assertEqual(first['managed'],second['managed']);self.assertIn('未重複複製',w.message.text())
        w.commit_extra('documents',dict(categories=[],rows=[]));self.assertTrue(available_path(self.path,second).exists())
