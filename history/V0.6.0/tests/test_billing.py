from contextlib import closing
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QDialog,QDialogButtonBox,QLineEdit,QComboBox,QMessageBox
import test_ui as support
import test_unified as unified
from traaduoduo.billing import (PAYMENT_KEYS,STAGES,CATEGORIES,new_record,empty_admin,normalize_billing,summary,stage_summary,
    validate_billing,period_options,warnings,allocation_filled)
from traaduoduo.store import ProjectStore,APPLICATION_ID
from traaduoduo.importer import preview_database

def record(kind='contract_payments',rid='r1',period=1,**values):
    return dict(new_record(kind,rid,period),**values)

def allocation(stage='first',period=1,travel='60',overtime='30',other='10'):
    return dict(stage=stage,period=period,**{'0C12':travel,'0C11':overtime,'0C14':other})

class BillingTests(unittest.TestCase):
    setUp=support.UITests.setUp
    tearDown=support.UITests.tearDown
    wait_io=support.UITests.wait_io

    def unlock(self,*keys):
        self.window.tabs.setCurrentIndex(2)
        for key in keys:
            self.window.toggle_lock(key)

    def test_period_cumulative_unordered_gaps_and_same_period_rows(self):
        pages=deepcopy(self.window.session.pages)
        pages['contract_payments']=[record(rid='a',period=10,amount='100.01'),record(rid='b',period=2,amount='0.02',tax='0.001'),record(rid='c',period=2,amount='0.03'),record(rid='d',period=5,amount='-1')]
        self.assertEqual(period_options(pages['contract_payments']),[2,5,10])
        self.assertEqual(summary(pages,'contract_payments',2)['amount'],Decimal('.05'))
        self.assertEqual(summary(pages,'contract_payments',5)['amount'],Decimal('-.95'))
        self.assertEqual(summary(pages,'contract_payments')['amount'],Decimal('99.06'))
        self.assertEqual(summary(pages,'contract_payments',1)['amount'],0)

    def test_validation_preserves_blank_zero_and_rejects_bad_types(self):
        row=record(amount='',tax='0')
        validate_billing('contract_payments',[row])
        for values in ({'period':0},{'period':True},{'period':1.5},{'amount':'NaN'},{'tax':'Infinity'},{'payment_date':'2026-02-30'}):
            with self.assertRaises((ValueError,ArithmeticError)):
                validate_billing('contract_payments',[dict(row,**values)])
        with self.assertRaises(ValueError):
            validate_billing('contract_payments',[row,row])

    def test_management_derived_sum_cannot_be_omitted_or_forged(self):
        for amount in ('','999'):
            row=record('admin_payments',amount=amount,**{'0C12':'10','0C11':'20'})
            data=deepcopy(self.window.session.pages['admin_payments']); data['rows']=[row]
            with self.assertRaises(ValueError):
                validate_billing('admin_payments',data)
        data['rows']=[record('admin_payments')]
        validate_billing('admin_payments',data)
        self.assertEqual(data['rows'][0]['amount'],'')

    def test_unknown_allocation_stage_and_duplicate_are_rejected(self):
        w=self.window; self.unlock('admin_payments'); before=deepcopy(w.session.pages)
        with patch('traaduoduo.billing_forms.QMessageBox.warning'):
            self.assertFalse(w.submit_allocation(allocation('unknown')))
        self.assertEqual(w.session.pages,before)
        value=deepcopy(w.session.pages['admin_payments']); value['allocations'][1]=value['allocations'][0]
        with self.assertRaises(ValueError):
            w.store.save({'admin_payments':value},0)

    def test_actual_other_dialog_uses_explicit_stage_and_cancel(self):
        w=self.window; self.unlock('other_payments')
        def save():
            dialog=next(d for d in w.findChildren(QDialog) if d.isVisible())
            combo=dialog.findChild(QComboBox,'payment_item'); combo.setCurrentIndex(combo.findData('transfer'))
            stage=dialog.findChild(QComboBox,'payment_stage'); stage.setCurrentIndex(stage.findData('second'))
            dialog.findChild(QLineEdit,'payment_amount').setText('100')
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        QTimer.singleShot(0,save); w.edit_payment('other_payments')
        self.assertEqual(stage_summary(w.session.pages)[1]['transfer'],100)
        before=deepcopy(w.session.pages)
        QTimer.singleShot(0,lambda:next(d for d in w.findChildren(QDialog) if d.isVisible()).reject())
        w.edit_payment('other_payments',w.session.pages['other_payments'][0])
        self.assertEqual(w.session.pages,before)

    def test_explicit_unique_stages_not_date_order(self):
        p=deepcopy(self.window.session.pages)
        p['other_payments']=[record('other_payments','a',5,item='transfer',stage='first',amount='100',payment_date='2026-12-01'),
            record('other_payments','c',2,item='transfer',stage='third',amount='10'),record('other_payments','d',3,item='0A',amount='20')]
        stages=stage_summary(p)
        self.assertEqual([s['transfer'] for s in stages],[100,0,10,0])
        self.assertEqual(stages[2]['running_transfer'],110)
        validate_billing('other_payments',p['other_payments'])
        self.assertEqual(summary(p,'other_payments',3)['transfer'],10)
        self.assertEqual(summary(p,'other_payments')['0A'],20)

    def test_zero_allocations_are_filled_blanks_are_pending_and_colors(self):
        w=self.window; self.unlock('other_payments','admin_payments')
        w.submit_payment('other_payments',record('other_payments',item='transfer',stage='first',amount='0'))
        self.assertEqual(w.payment_tables['other_payments'].item(0,6).text(),'待分攤')
        self.assertFalse(allocation_filled(allocation(travel='0',overtime='',other='0')))
        w.submit_allocation(allocation(travel='0',overtime='0',other='0'))
        cell=w.payment_tables['other_payments'].item(0,6)
        self.assertEqual(cell.text(),'已填分攤')
        self.assertEqual(cell.foreground().color().name(),'#1657b5')
        w.save(); self.wait_io()
        self.assertEqual(w.store.load()['pages']['admin_payments']['allocations'][0]['0C12'],'0')

    def test_final_negative_zero_and_positive_are_not_silently_changed(self):
        p=deepcopy(self.window.session.pages)
        p['other_payments']=[record('other_payments',item='transfer',stage='final',amount='-100')]
        p['admin_payments']['allocations'][3]=allocation('final',travel='-60',overtime='-30',other='-10')
        validate_billing('other_payments',p['other_payments'])
        validate_billing('admin_payments',p['admin_payments'])
        self.assertFalse(stage_summary(p)[3]['warnings'])
        p['other_payments'][0]['amount']='100'
        self.assertIn('末期提撥含正數',stage_summary(p)[3]['warnings'])
        p['other_payments'][0]['amount']='0'
        self.assertIn('末期提撥為0，請核對',stage_summary(p)[3]['warnings'])
        self.assertEqual(p['other_payments'][0]['amount'],'0')

    def test_available_basis_and_unknown_effective_period(self):
        p=deepcopy(self.window.session.pages)
        p['admin_payments']['allocations'][0]=allocation(period=1)
        p['admin_payments']['allocations'][1]=allocation('second',period=5,travel='100',overtime='0',other='0')
        p['admin_payments']['rows']=[record('admin_payments',period=2,amount='20',**{'0C12':'20'})]
        self.assertEqual(summary(p,'admin_payments',2)['0C12_available'],40)
        p['admin_payments']['allocations'][0]['period']=''
        self.assertEqual(summary(p,'admin_payments',2)['0C12_available'],-20)
        self.assertEqual(summary(p,'admin_payments')['0C12_available'],80)
        self.assertTrue(any('未填生效期' in s for s in warnings(p)))

    def test_all_four_stages_enforce_one_transfer_but_same_period_0A_is_allowed(self):
        rows=[]
        for index,(stage,_,_) in enumerate(STAGES):
            row=record('other_payments',stage,index+1,item='transfer',stage=stage,amount='10')
            rows.append(row)
            with self.assertRaisesRegex(ValueError,'每階段限一筆'):
                validate_billing('other_payments',rows+[dict(row,id='duplicate-'+stage,period=100)])
        rows.extend([record('other_payments','0a1',1,amount='1'),record('other_payments','0a2',1,amount='2')])
        validate_billing('other_payments',rows)

    def test_duplicate_transfer_ui_rejects_without_merging_or_replacing(self):
        w=self.window; self.unlock('other_payments')
        original=record('other_payments','original',1,item='transfer',stage='first',amount='100')
        self.assertTrue(w.submit_payment('other_payments',original))
        before=deepcopy(w.session.pages)
        with patch('traaduoduo.billing_forms.QMessageBox.warning') as warning:
            self.assertFalse(w.submit_payment('other_payments',dict(original,id='second',period=2,amount='200')))
        self.assertIn('original',warning.call_args.args[2]); self.assertIn('second',warning.call_args.args[2])
        self.assertEqual(w.session.pages,before)
        self.assertTrue(w.submit_payment('other_payments',dict(original,period=4,amount='110')))
        self.assertEqual(w.session.pages['other_payments'],[dict(original,period=4,amount='110')])
        w.save(); self.wait_io()
        self.assertEqual(w.store.load()['pages']['other_payments'],w.session.pages['other_payments'])

    def test_stage_reassignment_conflict_and_delete_releases_slot(self):
        w=self.window; self.unlock('other_payments')
        first=record('other_payments','a',1,item='transfer',stage='first',amount='10')
        second=record('other_payments','b',2,item='transfer',stage='second',amount='20')
        w.submit_payment('other_payments',first); w.submit_payment('other_payments',second)
        before=deepcopy(w.session.pages)
        with patch('traaduoduo.billing_forms.QMessageBox.warning'):
            self.assertFalse(w.submit_payment('other_payments',dict(first,stage='second')))
        self.assertEqual(w.session.pages,before)
        w.payment_tables['other_payments'].selectRow(1)
        with patch('traaduoduo.billing_forms.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            w.remove_payment('other_payments')
        self.assertTrue(w.submit_payment('other_payments',dict(first,stage='second')))
        self.assertEqual(w.session.pages['other_payments'],[dict(first,stage='second')])

    def test_database_stage_unique_index_is_atomic_and_project_scoped(self):
        w=self.window; pid=w.store.project_id
        other=w.store.add_project('同階段另一工程')['metadata']['project_id']
        with self.assertRaises(sqlite3.IntegrityError):
            with w.store.connect() as c:
                c.execute('INSERT INTO other_payments VALUES(?,?,?,?,?)',(pid,'one',1,'first',json.dumps(record('other_payments','one',1,item='transfer',stage='first'))))
                c.execute('INSERT INTO other_payments VALUES(?,?,?,?,?)',(pid,'two',2,'first',json.dumps(record('other_payments','two',2,item='transfer',stage='first'))))
        self.assertEqual(w.store.load()['pages']['other_payments'],[])
        rows=[record('other_payments','x',1,item='transfer',stage='first',amount='100')]
        w.store.save({'other_payments':rows},0)
        ProjectStore(self.path,other).save({'other_payments':rows},0)
        self.assertEqual(len(ProjectStore(self.path,other).load()['pages']['other_payments']),1)

    def test_historical_balance_excludes_future_and_undated_allocations(self):
        p=deepcopy(self.window.session.pages)
        p['admin_payments']['allocations']=[allocation('first',1,'100','0','0'),allocation('second',5,'200','0','0'),allocation('third','','300','0','0'),allocation('final',8,'-20','0','0')]
        p['admin_payments']['rows']=[record('admin_payments','old',2,amount='30',**{'0C12':'30'}),record('admin_payments','new',6,amount='50',**{'0C12':'50'})]
        self.assertEqual(summary(p,'admin_payments',2)['0C12_available'],70)
        self.assertEqual(summary(p,'admin_payments',5)['0C12_available'],270)
        self.assertEqual(summary(p,'admin_payments',6)['0C12_available'],220)
        self.assertEqual(summary(p,'admin_payments',8)['0C12_available'],200)
        self.assertEqual(summary(p,'admin_payments')['0C12_available'],200)
        self.assertEqual(summary(p,'admin_payments',2)['undated_allocations'],1)
        p['admin_payments']['available_basis']='all'
        self.assertEqual(summary(p,'admin_payments',2)['0C12_available'],70)
        with self.assertRaises(ValueError):
            validate_billing('admin_payments',p['admin_payments'])

    def test_fixed_period_policy_and_allocation_only_period_selector(self):
        w=self.window; self.unlock('admin_payments')
        self.assertEqual(empty_admin()['available_basis'],'period')
        self.assertFalse(w.available_basis_combo.isEnabled())
        self.assertEqual(w.available_basis_combo.count(),1)
        self.assertEqual(w.available_basis_combo.currentData(),'period')
        w.submit_allocation(allocation(period=5))
        combo=w.payment_periods['admin_payments']
        self.assertGreaterEqual(combo.findData(5),1)
        combo.setCurrentIndex(combo.findData(5))
        self.assertIn('截至第5期',w.payment_counts['admin_payments'].text())
        document=QTextDocument(); document.setHtml(w.payment_summaries['admin_payments'].text())
        self.assertRegex(document.toPlainText(),r'可支用額\s+0C12差費\s+60')

    def test_full_optional_admin_fields_are_preserved_and_exported(self):
        w=self.window; self.unlock('admin_payments')
        row=record('admin_payments',amount='60.01',tax='3.001',estimated='63.011',paid='55',paid_tax='2.75',retention='5.01',submitted='2026-10-01',payment_date='2026-10-02',reviewed='2026-10-03',note='完整欄位',**{'0C12':'10.01','0C11':'20','0C14':'30'})
        self.assertTrue(w.submit_payment('admin_payments',row)); w.save(); self.wait_io()
        out=Path(self.temp.name)/'full.db'; w.store.export_project(out)
        self.assertEqual(ProjectStore(out).load()['pages']['admin_payments']['rows'],[row])

    def test_payment_crud_and_reopen_preserve_all_fields(self):
        w=self.window; self.unlock('contract_payments')
        row=record(estimated='105.123',amount='100.01',tax='5.0005',paid='90',paid_tax='4.5',retention='10',submitted='2026-10-01',payment_date='2026-10-02',reviewed='2026-10-03',note='測試')
        self.assertTrue(w.submit_payment('contract_payments',row))
        w.save(); self.wait_io()
        self.assertEqual(w.store.load()['pages']['contract_payments'],[row])
        row['amount']='110.01'; w.submit_payment('contract_payments',row)
        self.assertEqual(len(w.session.pages['contract_payments']),1)
        w.save(); self.wait_io()
        self.assertEqual(ProjectStore(self.path).load()['pages']['contract_payments'][0]['amount'],'110.01')

    def test_locked_mutations_and_archive_rejected(self):
        w=self.window
        before=deepcopy(w.session.pages)
        for key in PAYMENT_KEYS:
            self.assertFalse(w.submit_payment(key,record(key)))
            w.remove_payment(key); w.edit_payment(key)
            self.assertEqual(w.payment_tables[key].editTriggers(),w.payment_tables[key].EditTrigger.NoEditTriggers)
            self.assertTrue(w.payment_tables[key].isEnabled())
        self.assertFalse(w.submit_allocation(allocation()))
        self.assertEqual(w.session.pages,before)
        w.store.archive(w.store.project_id); w.adopt(w.store.load())
        self.assertFalse(w.locks['admin_payments'].isEnabled())
        with self.assertRaises(ValueError):
            w.store.save({'contract_payments':[record()]},0)

    def test_new_transfer_requires_stage_without_mutating_draft(self):
        w=self.window; self.unlock('other_payments')
        with patch('traaduoduo.billing_forms.QMessageBox.warning'):
            self.assertFalse(w.submit_payment('other_payments',record('other_payments',item='transfer',amount='100')))
        self.assertEqual(w.session.pages['other_payments'],[])

    def test_actual_payment_dialog_save_and_cancel(self):
        w=self.window; self.unlock('contract_payments')
        def save():
            dialog=next(d for d in w.findChildren(QDialog) if d.isVisible() and d.objectName()=='paymentDialog')
            dialog.findChild(QLineEdit,'payment_amount').setText('1,234.50')
            dialog.findChild(QLineEdit,'payment_payment_date').setText('2026-10-16')
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        QTimer.singleShot(0,save); w.edit_payment('contract_payments')
        self.assertEqual(w.session.pages['contract_payments'][0]['amount'],'1234.50')
        before=deepcopy(w.session.pages)
        QTimer.singleShot(0,lambda:next(d for d in w.findChildren(QDialog) if d.isVisible()).reject())
        w.edit_payment('contract_payments')
        self.assertEqual(w.session.pages,before)

    def test_actual_admin_dialog_combines_categories_and_preserves_tax(self):
        w=self.window; self.unlock('admin_payments')
        def save():
            dialog=next(d for d in w.findChildren(QDialog) if d.isVisible())
            for field,value in [('0C12','10.01'),('0C11','20'),('0C14','30'),('tax','3.0005')]:
                dialog.findChild(QLineEdit,'payment_'+field).setText(value)
            self.assertTrue(dialog.findChild(QLineEdit,'payment_amount').isReadOnly())
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        QTimer.singleShot(0,save); w.edit_payment('admin_payments')
        row=w.session.pages['admin_payments']['rows'][0]
        self.assertEqual(row['amount'],'60.01'); self.assertEqual(row['tax'],'3.0005')

    def test_actual_allocation_dialog_and_undo(self):
        w=self.window; self.unlock('admin_payments'); w.billing_tabs.setCurrentIndex(2)
        def save():
            dialog=next(d for d in w.findChildren(QDialog) if d.isVisible())
            for key,value in [('0C12','60'),('0C11','30'),('0C14','10'),('period','1')]:
                dialog.findChild(QLineEdit,'allocation_'+key).setText(value)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        QTimer.singleShot(0,save); w.edit_allocation(0)
        self.assertTrue(stage_summary(w.session.pages)[0]['filled'])
        w.undo()
        self.assertFalse(stage_summary(w.session.pages)[0]['filled'])
        before=deepcopy(w.session.pages)
        QTimer.singleShot(0,lambda:next(d for d in w.findChildren(QDialog) if d.isVisible()).reject())
        w.edit_allocation(0); self.assertEqual(w.session.pages,before)

    def test_remove_transfer_recomputes_and_keeps_allocation(self):
        w=self.window; self.unlock('other_payments','admin_payments'); w.billing_tabs.setCurrentIndex(1)
        w.submit_payment('other_payments',record('other_payments',item='transfer',stage='first',amount='100'))
        w.submit_allocation(allocation()); w.payment_tables['other_payments'].selectRow(0)
        with patch('traaduoduo.billing_forms.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            w.remove_payment('other_payments')
        stage=stage_summary(w.session.pages)[0]
        self.assertEqual(stage['transfer'],0); self.assertEqual(stage['allocated'],100)
        self.assertIn('尚無對應提撥',stage['warnings'])
        w.undo(); self.assertEqual(stage_summary(w.session.pages)[0]['transfer'],100)

    def test_isolation_switch_failure_preserves_draft_and_period_filter(self):
        w=self.window; self.unlock('contract_payments')
        first=w.store.project_id; second=w.store.add_project('計價乙')['metadata']['project_id']
        w.submit_payment('contract_payments',record(period=5,amount='100'))
        w.payment_periods['contract_payments'].setCurrentIndex(1)
        with patch.object(w.store,'save',side_effect=OSError('disk full')),patch('traaduoduo.ui.QMessageBox.warning'),self.assertLogs(level='ERROR'):
            w.switch_project(second); self.wait_io()
        self.assertEqual(w.store.project_id,first)
        self.assertEqual(w.session.pages['contract_payments'][0]['amount'],'100')
        w.switch_project(second); self.wait_io()
        self.assertEqual(w.session.pages['contract_payments'],[])
        self.assertIsNone(w.payment_periods['contract_payments'].currentData())
        self.assertEqual(ProjectStore(self.path,first).load()['pages']['contract_payments'][0]['amount'],'100')

    def test_mid_write_failure_rolls_back_all_pages_and_revision(self):
        w=self.window; original=w.store.load(); real=ProjectStore._write_billing
        def fail(conn,pid,pages):
            real(conn,pid,pages); raise RuntimeError('injected after records')
        with patch.object(ProjectStore,'_write_billing',side_effect=fail),self.assertRaises(RuntimeError):
            w.store.save({'basic':dict(original['pages']['basic'],name='不可寫入'),'contract_payments':[record(amount='10')]},0)
        self.assertEqual(w.store.load()['pages'],original['pages'])
        self.assertEqual(w.store.load()['metadata']['revision'],'0')

    def test_sql_period_ids_foreign_keys_and_revision_conflict(self):
        w=self.window; pid=w.store.project_id
        for values in [(pid,'a',0,'{}'),('missing','b',1,'{}')]:
            with self.assertRaises(sqlite3.IntegrityError):
                with w.store.connect() as c:
                    c.execute('INSERT INTO contract_payments VALUES(?,?,?,?)',values)
        w.store.save({'contract_payments':[record()]},0)
        with self.assertRaises(ValueError):
            w.store.save({'contract_payments':[]},0)
        self.assertEqual(len(w.store.load()['pages']['contract_payments']),1)

    def test_export_backup_preview_roundtrip_new_ledgers(self):
        w=self.window; p=deepcopy(w.session.pages)
        p['contract_payments']=[record(amount='10.1234')]
        p['other_payments']=[record('other_payments',item='transfer',stage='final',amount='-10')]
        p['admin_payments']['allocations'][3]=allocation('final',travel='-10',overtime='0',other='0')
        p['admin_payments']['rows']=[record('admin_payments',amount='1',tax='0',**{'0C12':'1'})]
        w.store.save(p,0)
        out=Path(self.temp.name)/'out.db'; backup=Path(self.temp.name)/'backup.db'
        w.store.export_project(out); w.store.backup(backup)
        for path in (out,backup):
            self.assertEqual(ProjectStore(path).load()['pages'],w.store.load()['pages'])
        preview=preview_database(out); self.assertFalse(preview['projects'][0]['errors'])
        pid=w.store.import_preview(preview)['ids'][0]
        self.assertEqual(ProjectStore(self.path,pid).load()['pages'],w.store.load()['pages'])

    def legacy_fixture(self):
        fixture=unified.UnifiedTests('test_shared_database_isolation_and_revision'); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        source=fixture.legacy()
        with closing(sqlite3.connect(source)) as c,c:
            c.executescript('''
                CREATE TABLE payment_contract(id INTEGER,project_id INTEGER,period_no TEXT,estimated_amount_taxed TEXT,billing_amount_untaxed TEXT,billing_business_tax TEXT,paid_amount_untaxed TEXT,paid_business_tax TEXT,retention_amount TEXT,contractor_submit_date TEXT,owner_payment_date TEXT,supervision_submit_date TEXT,cumulative_billing_amount TEXT);
                CREATE TABLE payment_other(id INTEGER,project_id INTEGER,period_no TEXT,payment_date TEXT,payment_item TEXT,payment_amount TEXT);
                CREATE TABLE payment_admin(id INTEGER,project_id INTEGER,period_no TEXT,payment_date TEXT,travel_fee_billing TEXT,overtime_fee_billing TEXT,other_fee_billing TEXT,tax_amount TEXT,current_amount TEXT);
                INSERT INTO payment_contract VALUES(10,1,'2','105','100','5','90','4.5','10','2026-10-01','2026-10-02','2026-10-03','999999');
                INSERT INTO payment_other VALUES(11,1,'3','2026-10-04','管理費','100');
                INSERT INTO payment_admin VALUES(12,1,'4','2026-10-05','10','20','30','3.0001','999999');
            ''')
        return source

    def test_legacy_payments_map_without_guessed_tax_stage_or_cumulatives(self):
        source=self.legacy_fixture(); before=hashlib.sha256(source.read_bytes()).hexdigest()
        preview=preview_database(source); a,b=preview['projects']
        self.assertFalse(a['errors']); self.assertEqual(b['pages']['contract_payments'],[])
        p=a['pages']; self.assertEqual(summary(p,'contract_payments')['amount'],100)
        self.assertEqual(p['contract_payments'][0]['submitted'],'2026-10-01')
        self.assertEqual(p['other_payments'][0]['stage'],''); self.assertEqual(p['other_payments'][0]['tax'],'')
        self.assertEqual(p['admin_payments']['rows'][0]['amount'],'60')
        self.assertEqual(p['admin_payments']['rows'][0]['tax'],'3.0001')
        pid=self.window.store.import_preview(preview)['ids'][0]
        imported=ProjectStore(self.path,pid).load()['pages']
        self.assertEqual(imported['admin_payments'],p['admin_payments'])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)

    def test_legacy_currency_and_rate_decoration_preserves_raw_and_imports(self):
        source=self.legacy_fixture()
        with closing(sqlite3.connect(source)) as c,c:
            c.execute('ALTER TABLE projects ADD COLUMN performance_bond_rate TEXT')
            c.execute('ALTER TABLE projects ADD COLUMN warranty_rate TEXT')
            c.execute('ALTER TABLE projects ADD COLUMN budget_other TEXT')
            c.execute("UPDATE projects SET performance_bond_rate='10%',warranty_rate='3%',budget_other='500元'")
            c.execute("UPDATE payment_admin SET travel_fee_billing='0元',other_fee_billing='700元',tax_amount='60元'")
        before=source.read_bytes(); preview=preview_database(source); item=preview['projects'][0]
        self.assertFalse(item['errors'])
        self.assertEqual(item['pages']['admin_payments']['rows'][0]['amount'],'720')
        self.assertEqual(item['pages']['guarantees']['performance_rate'],'10')
        self.assertEqual(item['raw']['payment_admin'][0]['travel_fee_billing'],'0元')
        pid=self.window.store.import_preview(preview)['ids'][0]
        self.assertEqual(ProjectStore(self.path,pid).load()['pages']['admin_payments']['rows'][0]['tax'],'60')
        self.assertEqual(source.read_bytes(),before)

    def test_unrecognized_admin_amount_is_preview_error_not_crash_or_silent_zero(self):
        source=self.legacy_fixture()
        with closing(sqlite3.connect(source)) as c,c:
            c.execute("UPDATE payment_admin SET travel_fee_billing='約700元'")
        before=source.read_bytes(); preview=preview_database(source)
        self.assertIn('0C12',preview['projects'][0]['errors'][0])
        self.assertEqual(preview['projects'][0]['pages']['admin_payments']['rows'][0]['0C12'],'約700元')
        self.assertFalse(preview['projects'][1]['errors'])
        self.assertEqual(source.read_bytes(),before)

    def test_legacy_unknown_period_blocks_batch_and_preserves_source(self):
        source=self.legacy_fixture()
        with closing(sqlite3.connect(source)) as c,c:
            c.execute("UPDATE payment_contract SET period_no='' WHERE id=10")
        before=source.read_bytes(); preview=preview_database(source)
        self.assertTrue(preview['projects'][0]['errors'])
        with self.assertRaises(ValueError):
            self.window.store.import_preview(preview)
        self.assertEqual(len(self.window.store.list_projects()),1)
        self.assertEqual(source.read_bytes(),before)

    def schema4(self,evidence=None):
        source=Path(self.temp.name)/'v030.db'; p=deepcopy(self.window.session.pages)
        for k in PAYMENT_KEYS:
            p.pop(k)
        with closing(sqlite3.connect(source)) as c,c:
            c.executescript('CREATE TABLE projects(project_id TEXT PRIMARY KEY,revision INTEGER,saved_at TEXT,archived INTEGER); CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE pages(project_id TEXT,page_id TEXT,payload TEXT,PRIMARY KEY(project_id,page_id)); CREATE TABLE imports(source_key TEXT PRIMARY KEY,project_id TEXT,report TEXT,raw_payload TEXT); CREATE TABLE bids(project_id TEXT,record_id TEXT,awarded INTEGER,payload TEXT);')
            c.execute("INSERT INTO projects VALUES('source',0,'',0)")
            c.executemany('INSERT INTO pages VALUES(?,?,?)',[('source',k,json.dumps(v)) for k,v in p.items() if k!='bids'])
            if evidence:
                c.execute('INSERT INTO imports VALUES(?,?,?,?)',(evidence['source_key'],'source',json.dumps(evidence['report']),json.dumps(evidence['raw'])))
            c.execute(f'PRAGMA application_id={APPLICATION_ID}'); c.execute('PRAGMA user_version=4')
        return source

    def schema5(self,duplicate=False):
        source=Path(self.temp.name)/'v040.db'
        payload=ProjectStore.create(source,'舊計價工程'); store=ProjectStore(source)
        admin=deepcopy(payload['pages']['admin_payments'])
        admin['allocations'][0]=allocation(period=1)
        admin['allocations'][1]=allocation('second',period=5,travel='200',overtime='0',other='0')
        admin['rows']=[record('admin_payments','spent',2,amount='20',**{'0C12':'20'})]
        store.save({'other_payments':[record('other_payments','first-id',1,item='transfer',stage='first',amount='100')],'admin_payments':admin},0)
        with closing(sqlite3.connect(source)) as c,c:
            c.executescript('ALTER TABLE other_payments RENAME TO other_v6; CREATE TABLE other_payments(project_id TEXT,record_id TEXT,period INTEGER,payload TEXT); INSERT INTO other_payments SELECT project_id,record_id,period,payload FROM other_v6; DROP TABLE other_v6;')
            c.execute('UPDATE pages SET payload=? WHERE page_id=?',(json.dumps({'available_basis':'all'}),'billing_settings'))
            if duplicate:
                pid=payload['metadata']['project_id']
                row=record('other_payments','duplicate-id',3,item='transfer',stage='first',amount='200')
                c.execute('INSERT INTO other_payments VALUES(?,?,?,?)',(pid,row['id'],row['period'],json.dumps(row)))
            c.execute('PRAGMA user_version=5')
        return source

    def test_schema5_readonly_copy_changes_policy_but_preserves_original_snapshot(self):
        source=self.schema5(); before=hashlib.sha256(source.read_bytes()).hexdigest()
        preview=preview_database(source); item=preview['projects'][0]
        self.assertFalse(item['errors'])
        self.assertEqual(item['pages']['admin_payments']['available_basis'],'period')
        self.assertEqual(item['raw']['pages']['admin_payments']['available_basis'],'all')
        self.assertEqual(summary(item['pages'],'admin_payments',2)['0C12_available'],40)
        pid=self.window.store.import_preview(preview)['ids'][0]
        new=ProjectStore(self.path,pid)
        self.assertEqual(new.load()['pages']['admin_payments'],item['pages']['admin_payments'])
        report=Path(self.temp.name)/'source-evidence.json'; new.export_report(report)
        self.assertEqual(json.loads(report.read_text())[0]['raw']['pages']['admin_payments']['available_basis'],'all')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)

    def test_schema5_duplicate_transfer_preview_blocks_batch_without_deleting_rows(self):
        source=self.schema5(duplicate=True); before=source.read_bytes(); preview=preview_database(source)
        item=preview['projects'][0]
        self.assertIn('每階段限一筆',item['errors'][0])
        self.assertIn('first-id',item['errors'][0]); self.assertIn('duplicate-id',item['errors'][0])
        self.assertEqual(len(item['pages']['other_payments']),2)
        self.assertEqual(len(item['raw']['pages']['other_payments']),2)
        count=len(self.window.store.list_projects())
        with self.assertRaises(ValueError):
            self.window.store.import_preview(preview)
        self.assertEqual(len(self.window.store.list_projects()),count)
        self.assertEqual(source.read_bytes(),before)

    def test_schema4_readonly_import_defaults_and_settings_preserved(self):
        source=self.schema4(); before=source.read_bytes(); preview=preview_database(source)
        self.assertFalse(preview['projects'][0]['errors'])
        p=preview['projects'][0]['pages']
        self.assertEqual(p['contract_payments'],[])
        self.assertEqual(p['costs']['guarantee_base'],'award_total')
        pid=self.window.store.import_preview(preview)['ids'][0]
        self.assertEqual(ProjectStore(self.path,pid).load()['pages']['admin_payments'],p['admin_payments'])
        self.assertEqual(source.read_bytes(),before)

    def test_schema4_recovers_payments_from_its_exact_original_evidence(self):
        legacy=preview_database(self.legacy_fixture())['projects'][0]
        source=self.schema4(legacy); before=source.read_bytes(); preview=preview_database(source)
        item=preview['projects'][0]
        self.assertFalse(item['errors'])
        self.assertEqual(item['pages']['contract_payments'],legacy['pages']['contract_payments'])
        self.assertTrue(any('補回計價' in line for line in item['report']))
        self.assertEqual(source.read_bytes(),before)

    def test_table_numeric_sort_preserves_stable_id_and_same_period(self):
        w=self.window; self.unlock('contract_payments')
        for row in [record(rid='ten',period=10,amount='2'),record(rid='two',period=2,amount='1000'),record(rid='also-two',period=2,amount='10')]:
            w.submit_payment('contract_payments',row)
        table=w.payment_tables['contract_payments']; table.sortItems(2,Qt.SortOrder.DescendingOrder); table.selectRow(0)
        self.assertEqual(w.selected_payment('contract_payments')['id'],'two')
        w.submit_payment('contract_payments',dict(w.selected_payment('contract_payments'),amount='99'))
        self.assertEqual(len(w.session.pages['contract_payments']),3)
        self.assertEqual(next(r for r in w.session.pages['contract_payments'] if r['id']=='two')['amount'],'99')

    def test_payment_header_narrow_window_and_filters_remain_operable(self):
        w=self.window; w.resize(860,650); w.tabs.setCurrentIndex(2)
        support.APP.processEvents()
        self.assertEqual(w.secondary_tabs.count(),3)
        self.assertEqual([w.billing_tabs.tabText(i) for i in range(3)],['發包工程','發包以外','管理費'])
        for i,key in enumerate(PAYMENT_KEYS):
            w.billing_tabs.setCurrentIndex(i)
            self.assertEqual(w.current_page(),key)
            self.assertTrue(w.payment_tables[key].isEnabled())
            self.assertGreater(w.payment_tables[key].horizontalScrollBar().maximum(),0)
        self.assertLessEqual(w.secondary_tabs.geometry().right(),w.tab_header.width())
