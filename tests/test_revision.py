"""V0.5 acceptance: real services, widgets, transactions and reopen."""
from copy import deepcopy
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from PySide6.QtCore import QDate,QTimer,Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QDialog,QDialogButtonBox,QPushButton,QTextEdit,QGroupBox
import test_ui as support
from traaduoduo.store import ProjectStore,default_pages
from traaduoduo.scheduling import deadlines,working_calendar,weather_text
from traaduoduo.domain import count_workdays,calculate_day,calculate_finish,CalendarContext
from traaduoduo.finance import cost_totals,normalize_costs,legacy_money,legacy_percent,legacy_date
from traaduoduo.calendar_forms import DateEntryDialog
from traaduoduo.forms import info_button
from traaduoduo.importer import preview_database

class SchedulingRevisionTests(unittest.TestCase):
    def fixture(self):
        p=default_pages('工期試算')
        p['basic'].update(start='2026-10-05',days='10',initial_days='20',acceptance_days='30')
        p['holidays']=[['2026-10-12','假期']]; p['railway']=[['2026-10-14','輸運']]
        p['makeup']=[['2026-10-24','補班']]
        p['weather']=[['2026-10-08','0','.5','','0'],['2026-10-15','1','0','','0'],['2026-10-20','0','.5','','0']]
        return p

    def test_confirmed_finish_and_inspection_chain(self):
        p=self.fixture(); result=deadlines(p)
        self.assertEqual(result,dict(workday_finish='2026-10-22',calendar_finish='2026-10-14',initial_expected='2026-11-11',acceptance_expected='2026-12-11',workdayA='8'))
        p['basic']['mode']='日曆天'; result=deadlines(p)
        self.assertEqual(result['initial_expected'],'2026-11-03')
        self.assertEqual(result['acceptance_expected'],'2026-12-03')

    def test_opening_day_counts_and_calendar_ignores_exclusions(self):
        p=self.fixture(); p['basic'].update(start='2026-10-10',days='1',mode='日曆天')
        p['holidays']=[['2026-10-10','假日']]
        result=deadlines(p)
        self.assertEqual(result['calendar_finish'],'2026-10-10')
        self.assertEqual(result['workday_finish'],'2026-10-12')

    def test_weekend_makeup_and_railway_holiday_priority(self):
        p=self.fixture(); day=date(2026,10,24)
        self.assertEqual(calculate_day(day,working_calendar(p))[0],1)
        p['holidays'].append([day.isoformat(),'假期'])
        self.assertEqual(calculate_day(day,working_calendar(p))[0],0)
        p['holidays']=[]; p['railway'].append([day.isoformat(),'輸運'])
        self.assertEqual(calculate_day(day,working_calendar(p))[0],0)

    def test_makeup_halfday_and_independent_no_count(self):
        p=self.fixture(); day=date(2026,10,24)
        p['weather'].append([day.isoformat(),'0','.5','','0'])
        self.assertEqual(calculate_day(day,working_calendar(p))[0],Decimal('.5'))
        p['weather'][-1][4]='1'
        self.assertEqual(calculate_day(day,working_calendar(p))[0],0)
        self.assertEqual(weather_text([day.isoformat(),'0','0','現場停工','1']),'不計工期,現場停工')

    def test_half_day_remaining_moves_over_weekend_and_holiday(self):
        p=self.fixture(); p['basic'].update(start='2026-10-09',days='1')
        p['weather']=[['2026-10-09','0','.5','','0']]
        self.assertEqual(deadlines(p)['workday_finish'],'2026-10-13')
        self.assertEqual(count_workdays(date(2026,10,9),date(2026,10,13),working_calendar(p)),Decimal('1.5'))

    def test_am_one_has_full_day_priority_and_no_double_deduction(self):
        day=date(2026,10,5)
        ctx=CalendarContext(weather={day:('1','.5','test','1')})
        self.assertEqual(calculate_day(day,ctx)[0],0)
        self.assertEqual(weather_text(['2026-10-05','1','.5','note','1']),'上午:雨天,全日不計')

    def test_blank_deadlines_and_invalid_days(self):
        p=self.fixture()
        for value in ('0',''):
            p['basic']['days']=value; self.assertEqual(deadlines(p)['workday_finish'],'')
        for value in ('0.5','-1','36601','NaN'):
            p['basic']['days']=value
            with self.assertRaises((ValueError,ArithmeticError)): deadlines(p)
        p['basic'].update(days='1',initial_days='',acceptance_days='10')
        self.assertEqual(deadlines(p)['acceptance_expected'],'')

    def test_leap_day_year_crossing_and_real_dates_untouched(self):
        p=self.fixture(); p['basic'].update(start='2024-02-28',days='3',mode='日曆天',actual_finish='2026-01-01',initial_actual='2026-01-02',acceptance_actual='2026-01-03')
        before=deepcopy(p); self.assertEqual(deadlines(p)['calendar_finish'],'2024-03-01')
        self.assertEqual(p,before)
        p['basic'].update(start='2026-12-31',days='2')
        self.assertEqual(deadlines(p)['calendar_finish'],'2027-01-01')

class LegacyFormatTests(unittest.TestCase):
    def test_currency_suffix_and_prefix_are_explicit_not_guessed(self):
        for source,expected in [('0元','0'),('700元','700'),('60元','60'),('NT$ 1,234.50 元','1234.50'),('$ -12元','-12'),('  ','')]:
            self.assertEqual(legacy_money(source),expected)
        self.assertEqual(legacy_money('約700元'),'約700元')
        self.assertEqual(legacy_money('一萬元'),'一萬元')

    def test_percentage_is_not_divided_by_100(self):
        self.assertEqual(legacy_percent('10%'),'10')
        self.assertEqual(legacy_percent('3％'),'3')
        self.assertEqual(legacy_percent('10'),'10')
        self.assertEqual(legacy_percent('十%'),'十%')

    def test_date_parenthesis_is_preserved_without_guessing(self):
        text='2024-07-26(原25號因颱順延)'
        self.assertEqual(legacy_date(text),('2024-07-26',text))
        self.assertEqual(legacy_date('2026-02-30(備註)'),('2026-02-30(備註)',''))
        self.assertEqual(legacy_date('預計2024-07-26'),('預計2024-07-26',''))

class RevisionUITests(unittest.TestCase):
    setUp=support.UITests.setUp
    tearDown=support.UITests.tearDown
    wait_io=support.UITests.wait_io

    def test_tabs_font_width_placeholder_and_redundant_info(self):
        w=self.window; x=w.primary_tabs.x(); width=w.primary_tabs.width()
        for i in (3,4,5,6,0,1):
            w.tabs.setCurrentIndex(i); support.APP.processEvents()
            self.assertEqual(w.primary_tabs.x(),x); self.assertEqual(w.primary_tabs.width(),width)
        self.assertEqual(w.calendar_tabs.tabText(0),'假期補班與疏運表')
        w.resize(1440,1000); support.APP.processEvents()
        self.assertLess(w.secondary_tabs.x()+w.secondary_tabs.tabRect(0).x()-w.primary_tabs.geometry().right(),50)
        self.assertEqual(w.fields['number'].width(),240)
        self.assertEqual(w.fields['contractor'].width(),240)
        self.assertEqual(w.fields['signed'].width(),240)
        self.assertEqual(w.fields['signed'].palette().color(QPalette.ColorRole.PlaceholderText).name(),'#8e8e8e')
        self.assertIsNone(info_button(w,'工程編號','工程編號'))
        button=info_button(w,'工期','可計工作天'); button.click(); support.APP.processEvents()
        d=w.findChild(QDialog,'fieldInfoDialog')
        self.assertEqual(d.findChild(QTextEdit).font().pixelSize(),39); d.close()
        self.assertTrue(any(g.title()=='工程基本資料' for g in w.findChildren(QGroupBox)))
        self.assertTrue(w.guarantee_base_combo.isHidden()); self.assertTrue(w.copy_source_combo.isHidden())

    def test_scheduling_capture_reopen_and_actual_dates_preserved(self):
        w=self.window; p=SchedulingRevisionTests().fixture()
        w.store.save({key:p[key] for key in ('basic','holidays','makeup','railway','weather')},0)
        w.adopt(w.store.load()); self.assertEqual(w.fields['workday_finish'].text(),'2026-10-22')
        w.toggle_lock('basic'); w.fields['mode'].setCurrentIndex(1)
        self.assertEqual(w.fields['initial_expected'].text(),'2026-11-03')
        w.save(); self.wait_io(); w.adopt(w.store.load())
        self.assertEqual(w.fields['acceptance_expected'].text(),'2026-12-03')
        w.tabs.setCurrentIndex(1); w.calendar.setSelectedDate(QDate(2026,10,24)); w.refresh_calendar()
        self.assertEqual(w.calendar.day_details['2026-10-24']['daily'],'')
        self.assertEqual(calculate_day(date(2026,10,24),working_calendar(w.session.pages))[0],1)
        self.assertIn('補班',w.calendar.day_details['2026-10-24']['makeup'])
        self.assertEqual(w.calendar.day_details['2026-10-08']['weather'],'下午:雨天')

    def test_cost_totals_readonly_decimal_and_missing_inputs(self):
        w=self.window; w.toggle_lock('costs')
        for kind in ('budget','contract'):
            for key,val in dict(award_total='1000.01',work='1000.01',work_tax='0',labor='0',unfinished_tax='50',own_labor='10',purchased_material='20',road_stock='30',road_purchase='40',supervision='50',freight='60',pollution='70',stamp_tax='999').items():
                w.cost_fields[kind][key].setText(val)
        w.capture_costs()
        for kind in ('budget','contract'):
            side=w.session.pages['costs'][kind]
            self.assertEqual(side['other_fees'],'70'); self.assertEqual(side['non_labor'],'280')
            self.assertEqual(side['unfinished'],'1230.01'); self.assertEqual(side['total'],'1280.01')
            for key in ('other_fees','unfinished','total'): self.assertTrue(w.cost_fields[kind][key].isReadOnly())
        w.cost_fields['contract']['unfinished_tax'].clear(); w.capture_costs()
        self.assertEqual(w.session.pages['costs']['contract']['total'],'')
        w.save(); self.wait_io(); self.assertEqual(w.store.load()['pages']['costs']['budget']['total'],'1280.01')

    def test_invalid_date_draft_hides_stale_deadlines_without_writing(self):
        w=self.window; w.toggle_lock('basic')
        w.fields['start'].setText('2026-10-05'); w.fields['days'].setText('1'); w.capture_basic()
        self.assertEqual(w.fields['workday_finish'].text(),'2026-10-05')
        w.fields['start'].setText('2026-02-30'); w.capture_basic()
        self.assertEqual(w.fields['workday_finish'].text(),'')
        w.save(auto=True); self.assertEqual(w.store.load()['pages']['basic']['start'],'')
        w.fields['start'].setText('2026-10-06'); w.capture_basic()
        self.assertEqual(w.fields['workday_finish'].text(),'2026-10-06')

    def test_extensions_mirrored_names_amounts_show_hide_and_persist(self):
        w=self.window; w.toggle_lock('costs')
        with patch('traaduoduo.finance_forms.QInputDialog.getText',return_value=('臨時設施',True)): w.add_cost_extension()
        w.extension_tables['budget'].item(0,0).setText('改名費用')
        self.assertEqual(w.extension_tables['contract'].item(0,0).text(),'改名費用')
        w.extension_tables['budget'].item(0,1).setText('1.01')
        w.copy_extension(0)
        self.assertEqual(w.session.pages['costs']['extensions'][0]['contract'],'1.01')
        self.assertEqual(w.session.pages['costs']['contract']['other_fees'],'1.01')
        rid=w.session.pages['costs']['extensions'][0]['id']
        self.assertTrue(all(button.isHidden() for button in w.extension_toggles.values()))
        self.assertFalse(w.extension_containers['contract'].isHidden())
        self.assertEqual(w.session.pages['costs']['contract']['other_fees'],'1.01')
        w.save(); self.wait_io(); w.adopt(w.store.load())
        self.assertEqual(w.session.pages['costs']['extensions'][0]['id'],rid)
        self.assertFalse(w.extension_containers['budget'].isHidden())

    def test_calendar_dialog_cancel_today_and_noncount_persistence(self):
        w=self.window; w.tabs.setCurrentIndex(1); w.calendar_tabs.setCurrentIndex(2); w.toggle_lock('weather')
        def cancel():
            d=next(d for d in w.findChildren(DateEntryDialog) if d.isVisible())
            self.assertEqual(d.calendar.selectedDate(),QDate.currentDate()); d.reject()
        QTimer.singleShot(0,cancel); w.add_row('weather'); self.assertEqual(w.session.pages['weather'],[])
        def submit():
            d=next(d for d in w.findChildren(DateEntryDialog) if d.isVisible())
            d.calendar.setSelectedDate(QDate(2026,10,19)); d.fields['pm'].setText('.5'); d.fields['note'].setText('停工說明')
            d.fields['am'].setText('1')
            self.assertFalse(d.fields['pm'].isEnabled()); self.assertFalse(d.fields['note'].isEnabled())
            d.fields['am'].setText('0'); self.assertEqual(d.fields['note'].text(),'停工說明')
            self.assertTrue(d.fields['pm'].isEnabled()); d.fields['nc'].setText('1'); d.submit()
        QTimer.singleShot(0,submit); w.add_row('weather'); w.save(); self.wait_io()
        row=w.store.load()['pages']['weather'][0]
        self.assertEqual(row,['2026-10-19','0','.5','停工說明','1'])
        self.assertEqual(weather_text(row),'不計工期,停工說明')

    def test_bad_extension_keeps_draft_and_blocks_save_until_corrected(self):
        w=self.window; w.toggle_lock('costs')
        with patch('traaduoduo.finance_forms.QInputDialog.getText',return_value=('測試費',True)): w.add_cost_extension()
        w.extension_tables['budget'].item(0,1).setText('不是金額')
        w.save(auto=True); self.assertIsNone(w.future)
        self.assertEqual(w.store.load()['pages']['costs']['extensions'],[])
        w.populate_extensions()
        self.assertEqual(w.extension_tables['budget'].item(0,1).text(),'不是金額')
        with patch('traaduoduo.finance_forms.QMessageBox.warning'): w.copy_extension(0)
        self.assertEqual(w.session.pages['costs']['extensions'][0]['contract'],'')
        w.extension_tables['budget'].item(0,1).setText('12.34'); w.copy_extension(0)
        w.save(); self.wait_io()
        self.assertEqual(w.store.load()['pages']['costs']['extensions'][0]['contract'],'12.34')

    def test_duplicate_day_dialog_does_not_add(self):
        w=self.window; w.toggle_lock('holidays')
        day=QDate.currentDate().toString('yyyy-MM-dd')
        w.session.change('holidays',[[day,'原值']]); w.populate_table('holidays')
        def duplicate():
            d=next(d for d in w.findChildren(DateEntryDialog) if d.isVisible()); d.submit()
            self.assertIn('重複',d.error.text()); self.assertTrue(d.isVisible()); d.reject()
        QTimer.singleShot(0,duplicate); w.add_row('holidays')
        self.assertEqual(w.session.pages['holidays'],[[day,'原值']])

    def test_stage_sequence_requires_successful_saved_previous_and_zero_counts(self):
        w=self.window; w.tabs.setCurrentIndex(2); w.billing_tabs.setCurrentIndex(2); w.toggle_lock('admin_payments')
        from traaduoduo.billing import new_record
        w.session.pages['other_payments']=[dict(new_record('other_payments','transfer',1),item='transfer',stage='first',amount='0')]
        self.assertFalse(w.allocation_buttons[1].isEnabled())
        candidate=dict(stage='first',period=1,**{'0C12':'0','0C11':'0','0C14':'0'})
        self.assertTrue(w.submit_allocation(candidate)); self.assertFalse(w.allocation_buttons[1].isEnabled())
        self.wait_io(); self.assertTrue(w.allocation_buttons[1].isEnabled()); self.assertFalse(w.allocation_buttons[2].isEnabled())
        w.adopt(w.store.load()); w.toggle_lock('admin_payments'); self.assertTrue(w.allocation_buttons[1].isEnabled())
        with patch('traaduoduo.billing_forms.QMessageBox.warning'):
            self.assertFalse(w.submit_allocation(dict(candidate,stage='third')))
        self.assertTrue(w.available_basis_combo.isHidden())
        self.assertNotIn('基準：',w.payment_summaries['admin_payments'].text())

    def test_legacy_out_of_order_allocations_remain_stored(self):
        w=self.window; admin=deepcopy(w.session.pages['admin_payments'])
        admin['allocations'][3].update(period=6,**{'0C12':'-1','0C11':'0','0C14':'0'})
        w.store.save({'admin_payments':admin},0); w.adopt(w.store.load()); w.toggle_lock('admin_payments')
        self.assertEqual(w.session.pages['admin_payments']['allocations'][3]['0C12'],'-1')
        self.assertFalse(w.allocation_buttons[3].isEnabled())

    def test_failed_allocation_write_does_not_unlock_next_stage(self):
        w=self.window; w.toggle_lock('admin_payments')
        from traaduoduo.billing import new_record
        w.session.pages['other_payments']=[dict(new_record('other_payments','transfer',1),item='transfer',stage='first',amount='0')]
        candidate=dict(stage='first',period=1,**{'0C12':'0','0C11':'0','0C14':'0'})
        with patch.object(w.store,'save',side_effect=OSError('disk full')),patch('traaduoduo.ui.QMessageBox.warning'),self.assertLogs(level='ERROR'):
            self.assertTrue(w.submit_allocation(candidate)); self.wait_io()
        self.assertFalse(w.allocation_allowed(1)); self.assertTrue(w.session.dirty())
        self.assertEqual(w.store.load()['pages']['admin_payments']['allocations'][0]['0C12'],'')
        w.save(); self.wait_io(); self.assertTrue(w.allocation_allowed(1))

    def test_real_v041_readonly_conversion_and_original_hash(self):
        w=self.window; source=Path(self.temp.name)/'real-schema6.db'
        old=Path(os.environ.get('TRAA_V041_TEST_SOURCE',str(Path(__file__).resolve().parents[2]/'V0.4.1')))
        if not (old/'traaduoduo/store.py').is_file():
            self.skipTest('Set TRAA_V041_TEST_SOURCE to a V0.4.1 source folder for historical-schema acceptance')
        code="""from pathlib import Path
import sys
from traaduoduo.store import ProjectStore
p=Path(sys.argv[1]); result=ProjectStore.create(p,'V041真實結構')
c=result['pages']['costs']; c['budget'].update(total='999',unfinished='888',award_total='100',unfinished_tax='5')
b=dict(result['pages']['basic'],start='2026-10-05',days='1',workday_finish='2020-01-01')
ProjectStore(p).save({'costs':c,'basic':b,'weather':[['2026-10-05','0','0','-1']]},0)
"""
        subprocess.run([sys.executable,'-c',code,str(source)],cwd=old,env=dict(os.environ,PYTHONPATH=str(old)),check=True)
        before=hashlib.sha256(source.read_bytes()).hexdigest(); preview=preview_database(source)
        self.assertFalse(preview['projects'][0]['errors'])
        pid=w.store.import_preview(preview)['ids'][0]; migrated=ProjectStore(self.path,pid).load()['pages']
        self.assertEqual(migrated['costs']['budget']['historical_totals'],{'total':'999','unfinished':'888'})
        self.assertEqual(migrated['costs']['budget']['total'],'')
        self.assertEqual(migrated['costs']['budget']['historical_v070']['award_total'],'100')
        self.assertEqual(migrated['basic']['historical_deadlines']['workday_finish'],'2020-01-01')
        self.assertEqual(migrated['basic']['workday_finish'],'2026-10-06')
        self.assertEqual(migrated['weather'][0][4],'1')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
