from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QDialog,QDialogButtonBox,QLineEdit,QCheckBox,QMessageBox
import test_ui as support
from traaduoduo.finance import management_fee,empty_costs,normalize_costs,percent
from traaduoduo.store import ProjectStore
from traaduoduo.importer import preview_database


def bid(number=1,awarded=False,award='2026-10-16'):
    return dict(id='bid-'+str(number),number=number,awarded=awarded,review_start='',review_end='',online_start='2026-10-01',online_end='2026-10-05',opening='2026-10-08',committee='2026-10-10',award_date=award)


class FinanceTests(unittest.TestCase):
    setUp=support.UITests.setUp
    tearDown=support.UITests.tearDown
    wait_io=support.UITests.wait_io

    def test_confirmed_defaults_and_missing_legacy_settings(self):
        for costs in (empty_costs(),normalize_costs({'contract':{'award_total':'1050000'}})):
            self.assertEqual(costs['guarantee_base'],'award_total')
            self.assertEqual(costs['own_labor_copy'],'own_labor')
        w=self.window
        self.assertEqual(w.guarantee_base_combo.currentData(),'award_total')
        self.assertEqual(w.copy_source_combo.currentData(),'own_labor')
        costs=deepcopy(w.session.pages['costs'])
        costs['contract'].update(award_total='1050000',work='1000000')
        w.store.save({'costs':costs},0)
        result=ProjectStore(self.path).load()['pages']
        self.assertEqual(result['costs']['guarantee_base'],'award_total')
        self.assertEqual(result['costs']['own_labor_copy'],'own_labor')
        self.assertEqual(result['guarantees']['performance_auto_amount'],'105000.00')
        self.assertEqual(result['guarantees']['warranty_auto_amount'],'31500.00')

    def test_explicit_saved_sources_and_manual_amounts_are_preserved(self):
        w=self.window
        costs=normalize_costs({'guarantee_base':'work','own_labor_copy':'management_amount',
                              'contract':{'award_total':'1050000','work':'1000000'}})
        guarantees=dict(w.session.pages['guarantees'],performance_manual=True,performance_amount='777',
                        warranty_manual=True,warranty_amount='888')
        w.store.save({'costs':costs,'guarantees':guarantees},0)
        result=ProjectStore(self.path).load()
        w.adopt(result)
        self.assertEqual(w.guarantee_base_combo.currentData(),'work')
        self.assertEqual(w.copy_source_combo.currentData(),'management_amount')
        self.assertEqual(result['pages']['guarantees']['performance_auto_amount'],'100000.00')
        self.assertEqual(w.guarantee_fields['performance_amount'].text(),'777')
        self.assertEqual(w.guarantee_fields['warranty_amount'].text(),'888')

    def test_tier_boundaries_and_truncate(self):
        side=empty_costs()['budget']
        points={5000000:150000,25000000:450000,100000000:1200000,500000000:4000000,600000000:4500000}
        for value,expected in points.items():
            side['award_total']=str(value)
            self.assertEqual(management_fee(side,'budget')['total'],expected)
            for delta in (-1,1):
                side['award_total']=str(value+delta)
                result=management_fee(side,'budget')
                self.assertGreaterEqual(result['total'],0)
                self.assertEqual(result['default']%1000,0)
                rates={5000000:('0.03','0.015'),25000000:('0.015','0.01'),100000000:('0.01','0.007'),500000000:('0.007','0.005'),600000000:('0.005','0.005')}
                self.assertEqual(result['raw_total'],Decimal(expected)+Decimal(delta)*Decimal(rates[value][0 if delta<0 else 1]))
                self.assertEqual(result['total'],Decimal(expected))
        side['award_total']='5000001'
        self.assertEqual(management_fee(side,'budget')['total'],Decimal('150000'))
        self.assertEqual(management_fee(side,'budget')['raw_total'],Decimal('150000.015'))
        self.assertEqual(management_fee(side,'budget')['default'],150000)
        self.assertEqual(percent('1','3'),'33.33%')
        self.assertEqual(percent('100','0'),'—')

    def test_cost_save_manual_guarantees_and_base_selection(self):
        w=self.window
        w.basic_tabs.setCurrentIndex(1); w.toggle_lock('costs')
        w.cost_fields['budget']['award_total'].setText('5,000,000')
        w.cost_fields['contract']['work'].setText('1000000')
        w.cost_fields['contract']['award_total'].setText('1050000')
        w.capture_costs()
        self.assertEqual(w.session.pages['costs']['budget']['management_amount'],'150000')
        self.assertEqual(w.guarantee_fields['performance_amount'].text(),'105000.00')
        self.assertEqual(w.guarantee_fields['warranty_amount'].text(),'31500.00')
        w.guarantee_base_combo.setCurrentIndex(w.guarantee_base_combo.findData('work'))
        self.assertEqual(w.guarantee_fields['performance_amount'].text(),'100000.00')
        self.assertEqual(w.guarantee_fields['warranty_amount'].text(),'30000.00')
        w.guarantee_base_combo.setCurrentIndex(w.guarantee_base_combo.findData('award_total'))
        self.assertEqual(w.guarantee_fields['performance_amount'].text(),'105000.00')
        w.toggle_lock('guarantees')
        w.guarantee_fields['performance_manual'].setChecked(True)
        w.guarantee_fields['performance_amount'].setText('777')
        w.capture_form('guarantees')
        w.cost_fields['contract']['work'].setText('2000000'); w.capture_costs()
        self.assertEqual(w.guarantee_fields['performance_amount'].text(),'777')
        w.save(); self.wait_io()
        result=w.store.load()['pages']
        self.assertEqual(result['guarantees']['performance_amount'],'777')
        self.assertEqual(result['guarantees']['performance_auto_amount'],'105000.00')

    def test_management_manual_survives_base_changes_and_restore(self):
        w=self.window; w.toggle_lock('costs')
        w.cost_fields['budget']['award_total'].setText('5000000'); w.capture_costs()
        w.fee_manual['budget'].setChecked(True)
        w.cost_fields['budget']['management_adjustment'].setText('149999'); w.capture_costs()
        w.cost_fields['budget']['award_total'].setText('25000000'); w.capture_costs()
        self.assertEqual(w.session.pages['costs']['budget']['management_amount'],'149999')
        w.fee_manual['budget'].setChecked(False)
        self.assertEqual(w.session.pages['costs']['budget']['management_amount'],'450000')
        w.fee_manual['budget'].setChecked(True)
        self.assertEqual(w.session.pages['costs']['budget']['management_amount'],'149999')
        w.save(); self.wait_io()

    def test_extensions_ids_copy_and_overwrite_cancel(self):
        w=self.window; w.toggle_lock('costs')
        for i in range(7):
            with patch('traaduoduo.finance_forms.QInputDialog.getText',return_value=('擴充'+str(i),True)):
                w.add_cost_extension()
        ids=[r['id'] for r in w.session.pages['costs']['extensions']]
        self.assertEqual(len(set(ids)),7)
        self.assertEqual(w.extension_table.rowCount(),7)
        w.extension_table.item(0,1).setText('1,000')
        w.extension_table.setCurrentCell(0,0); w.copy_extension()
        self.assertEqual(w.session.pages['costs']['extensions'][0]['contract'],'1000')
        w.extension_table.item(0,1).setText('2000')
        with patch('traaduoduo.finance_forms.QMessageBox.question',return_value=QMessageBox.StandardButton.No):
            w.copy_extension()
        self.assertEqual(w.session.pages['costs']['extensions'][0]['contract'],'1000')
        w.save(); self.wait_io()
        self.assertEqual([r['id'] for r in w.store.load()['pages']['costs']['extensions']],ids)

    def test_copy_own_labor_always_uses_budget_and_no_empty_placeholder_rows(self):
        w=self.window; w.toggle_lock('costs')
        self.assertEqual(w.extension_table.rowCount(),0)
        w.cost_fields['budget']['award_total'].setText('5000000')
        w.cost_fields['budget']['own_labor'].setText('10000'); w.capture_costs()
        w.copy_cost('own_labor')
        self.assertEqual(w.session.pages['costs']['contract']['own_labor'],'10000')
        w.copy_source_combo.setCurrentIndex(1)
        with patch('traaduoduo.finance_forms.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            w.copy_cost('own_labor')
        self.assertEqual(w.session.pages['costs']['contract']['own_labor'],'10000')

    def test_negative_cost_and_bad_award_batch_roll_back(self):
        w=self.window
        original=w.store.load()
        costs=deepcopy(original['pages']['costs'])
        costs['budget']['award_total']='5000000'
        with self.assertRaises(ValueError):
            w.store.save({'costs':costs,'bids':[bid(1,True),bid(2,True)]},0)
        self.assertEqual(w.store.load()['pages'],original['pages'])
        costs['budget']['award_total']='-1'
        with self.assertRaises(ValueError):
            w.store.save({'costs':costs},0)
        self.assertEqual(w.store.load()['metadata']['revision'],'0')

    def test_delete_awarded_bid_restores_history_after_reopen(self):
        w=self.window
        w.store.save({'basic':dict(w.session.pages['basic'],award='2025-03-04')},0)
        w.adopt(w.store.load()); w.toggle_lock('bids')
        w.submit_bid(bid(1,True)); w.bid_table.selectRow(0)
        with patch('traaduoduo.finance_forms.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            w.remove_bid()
        self.assertEqual(w.fields['award'].text(),'2025-03-04')
        w.save(); self.wait_io()
        self.assertEqual(w.store.load()['pages']['basic']['award'],'2025-03-04')

    def test_unique_award_feedback_cancel_restore_and_ids(self):
        w=self.window
        basic=dict(w.session.pages['basic'],award='2025-01-01')
        w.store.save({'basic':basic},0); w.adopt(w.store.load())
        w.basic_tabs.setCurrentIndex(3); w.toggle_lock('bids')
        self.assertTrue(w.submit_bid(bid(1,True)))
        self.assertEqual(w.fields['award'].text(),'2026-10-16')
        self.assertTrue(w.fields['award'].isReadOnly())
        with patch('traaduoduo.finance_forms.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(w.submit_bid(bid(2,True,'2026-11-01')))
        self.assertEqual(sum(r['awarded'] for r in w.session.pages['bids']),1)
        self.assertEqual(w.fields['award'].text(),'2026-11-01')
        self.assertTrue(w.submit_bid(bid(2,False,'2026-11-01')))
        self.assertEqual(w.fields['award'].text(),'2025-01-01')
        w.save(); self.wait_io()
        self.assertEqual({r['id'] for r in w.store.load()['pages']['bids']},{'bid-1','bid-2'})

    def test_database_unique_index_and_project_isolation(self):
        w=self.window
        with self.assertRaises(sqlite3.IntegrityError):
            with w.store.connect() as conn:
                conn.execute('INSERT INTO bids VALUES(?,?,?,?)',(w.store.project_id,'x',1,'{}'))
                conn.execute('INSERT INTO bids VALUES(?,?,?,?)',(w.store.project_id,'y',1,'{}'))
        self.assertEqual(w.store.load()['pages']['bids'],[])
        w.store.save({'bids':[bid(1,True)]},0)
        other=w.store.add_project('工程乙')['metadata']['project_id']
        ProjectStore(self.path,other).save({'bids':[bid(1,True)]},0)
        self.assertEqual(len(w.store.load()['pages']['bids']),1)

    def test_bad_bid_dates_and_multiple_winners_rollback(self):
        w=self.window
        for rows in ([bid(1,True),bid(2,True)], [dict(bid(),online_end='2026-09-01')]):
            with self.assertRaises(ValueError):
                w.store.save({'bids':rows},0)
            self.assertEqual(w.store.load()['metadata']['revision'],'0')
            self.assertEqual(w.store.load()['pages']['bids'],[])

    def test_locked_new_pages_and_cost_undo(self):
        w=self.window
        self.assertTrue(w.cost_fields['budget']['award_total'].isReadOnly())
        self.assertFalse(w.bid_buttons[0].isEnabled())
        self.assertFalse(w.submit_bid(bid()))
        w.basic_tabs.setCurrentIndex(1); w.toggle_lock('costs')
        w.cost_fields['budget']['award_total'].setText('5000000'); w.capture_costs()
        self.assertEqual(w.session.pages['costs']['budget']['management_amount'],'150000')
        w.undo()
        self.assertEqual(w.session.pages['costs']['budget']['award_total'],'')
        self.assertEqual(w.session.pages['costs']['budget']['management_amount'],'')

    def test_new_schema_export_import_and_raw_reference(self):
        w=self.window
        costs=deepcopy(w.session.pages['costs'])
        costs['contract']['work']='1000000'
        w.store.save({'costs':costs,'bids':[bid(1,True)]},0)
        out=Path(self.temp.name)/'export.db'; w.store.export_project(out)
        self.assertEqual(ProjectStore(out).load()['pages'],w.store.load()['pages'])
        preview=preview_database(out)
        self.assertFalse(preview['projects'][0]['errors'])
        self.assertEqual(preview['projects'][0]['pages']['bids'][0]['id'],'bid-1')

    def test_actual_bid_dialog_saves_and_cancel_does_not_add(self):
        w=self.window; w.toggle_lock('bids')
        def submit():
            dialog=next(d for d in w.findChildren(QDialog) if d.isVisible())
            fields=dialog.findChildren(QLineEdit)
            fields[-1].setText('2026-10-16')
            dialog.findChild(QCheckBox).setChecked(True)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        QTimer.singleShot(0,submit); w.edit_bid()
        self.assertEqual(len(w.session.pages['bids']),1)
        self.assertEqual(w.fields['award'].text(),'2026-10-16')
        def cancel():
            next(d for d in w.findChildren(QDialog) if d.isVisible()).reject()
        QTimer.singleShot(0,cancel); w.edit_bid()
        self.assertEqual(len(w.session.pages['bids']),1)
        w.save(); self.wait_io()

    def test_schema3_copy_preserves_stage_one_and_source_bytes(self):
        import hashlib
        from contextlib import closing
        source=Path(self.temp.name)/'stage-one.db'
        pages=deepcopy(self.window.session.pages)
        pages.pop('costs'); pages.pop('bids')
        pages['guarantees'].update(performance_manual=True,performance_amount='888')
        with closing(sqlite3.connect(source)) as c,c:
            c.executescript('CREATE TABLE projects(project_id TEXT PRIMARY KEY,revision INTEGER,saved_at TEXT,archived INTEGER); CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE pages(project_id TEXT,page_id TEXT,payload TEXT,PRIMARY KEY(project_id,page_id)); CREATE TABLE imports(source_key TEXT PRIMARY KEY,project_id TEXT,report TEXT,raw_payload TEXT);')
            c.execute("INSERT INTO projects VALUES('old',0,'',0)")
            c.executemany('INSERT INTO pages VALUES(?,?,?)',[('old',key,json.dumps(value)) for key,value in pages.items()])
            c.execute('PRAGMA application_id=1414676801')
            c.execute('PRAGMA user_version=3')
        before=hashlib.sha256(source.read_bytes()).hexdigest()
        preview=preview_database(source)
        self.assertFalse(preview['projects'][0]['errors'])
        pid=self.window.store.import_preview(preview)['ids'][0]
        new=ProjectStore(self.path,pid).load()['pages']
        self.assertEqual(new['guarantees']['performance_amount'],'888')
        self.assertEqual(new['costs']['budget']['award_total'],'')
        self.assertEqual(new['costs']['budget']['other_fees'],'0')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)

    def test_old_fxwork_finance_maps_known_columns_without_recalculation(self):
        from contextlib import closing
        import test_unified as fixtures
        fixture=fixtures.UnifiedTests('test_shared_database_isolation_and_revision')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        source=fixture.legacy()
        with closing(sqlite3.connect(source)) as c,c:
            for key in ('budget_contract_total','budget_mgmt_fee','award_contract_amount','deposit_performance','deposit_performance_manual'):
                c.execute('ALTER TABLE projects ADD COLUMN '+key+' TEXT')
            c.execute("UPDATE projects SET budget_contract_total='5000000',budget_mgmt_fee='123456',award_contract_amount='4000000',deposit_performance='888',deposit_performance_manual='1' WHERE id=1")
            c.executescript("CREATE TABLE bids(id INTEGER,project_id INTEGER,round_no INTEGER,online_date TEXT,open_date TEXT,award_date TEXT); INSERT INTO bids VALUES(10,1,1,'2026-01-01','2026-01-08','2026-01-10');")
        preview=preview_database(source)
        item=preview['projects'][0]
        self.assertFalse(item['errors'])
        result=self.window.store.import_preview(dict(preview,projects=[item]))
        new=ProjectStore(self.path,result['ids'][0]).load()['pages']
        self.assertEqual(new['costs']['budget']['management_amount'],'123456')
        self.assertTrue(new['costs']['budget']['management_manual'])
        self.assertEqual(new['guarantees']['performance_amount'],'888')
        self.assertTrue(new['guarantees']['performance_manual'])
        self.assertEqual(new['basic']['award'],'2026-01-10')
        self.assertEqual(new['bids'][0]['id'],'legacy-10')
