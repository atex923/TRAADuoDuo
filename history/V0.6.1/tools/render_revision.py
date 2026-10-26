"""Capture the actual V0.5 Qt widgets using an isolated QA instance."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings,QDate,QTimer
from PySide6.QtWidgets import QApplication,QDialog,QDialogButtonBox,QScrollArea
from traaduoduo.ui import Window,ROOT
from traaduoduo.store import ProjectStore
from traaduoduo.instance import MacInstance
from traaduoduo.calendar_forms import DateEntryDialog
from traaduoduo.billing import new_record

app=QApplication([])
target=ROOT/'docs/screenshots/v050'; target.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='render-v050-') as directory:
    directory=Path(directory); instance=MacInstance(directory)
    if not instance.owner: raise RuntimeError('已有相同 QA 實例')
    database=directory/'demo.db'; p=ProjectStore.create(database,'站區環境改善工程（示範）')
    store=ProjectStore(database)
    basic=dict(p['pages']['basic'],number='TR-DEMO-001',contract='DEMO-2026-001',contractor='示範營造有限公司',start='2026-10-05',days='10',initial_days='20',acceptance_days='30')
    costs=p['pages']['costs']
    costs['budget'].update(award_total='1000000',unfinished_tax='55000',work='952381',work_tax='47619',own_labor='40000',purchased_material='20000',road_stock='10000',supervision='10000',freight='5000',pollution='10000')
    costs['contract'].update(award_total='900000',unfinished_tax='49000',base_price='950000',work='857142.86',work_tax='42857.14',own_labor='30000',purchased_material='15000',road_stock='10000',supervision='10000',freight='3000',pollution='8000')
    costs['extensions']=[dict(id='demo-extra',label='臨時設施費',budget='5000',contract='4000')]
    admin=p['pages']['admin_payments']; admin['allocations'][0].update(period=1,**{'0C12':'30000','0C11':'20000','0C14':'10000'})
    admin['rows']=[dict(new_record('admin_payments','demo-expense',1),amount='6000',tax='300',payment_date='2026-10-16',**{'0C12':'3000','0C11':'2000','0C14':'1000'})]
    other=[dict(new_record('other_payments','demo-transfer',1),item='transfer',stage='first',amount='60000')]
    store.save(dict(basic=basic,costs=costs,admin_payments=admin,other_payments=other,holidays=[['2026-10-12','示範假期']],makeup=[['2026-10-24','示範補班']],railway=[['2026-10-14','示範輸運']],weather=[['2026-10-08','0','.5','','0'],['2026-10-15','1','0','','0'],['2026-10-20','0','.5','','0']]),0)
    window=Window(QSettings(str(directory/'qa.ini'),QSettings.Format.IniFormat)); instance.activate(window)
    window.adopt(store.load()); window.resize(1440,1000); window.show(); app.processEvents()
    def shot(name):
        app.processEvents()
        if not window.grab().save(str(target/(name+'.png'))): raise RuntimeError('無法擷取畫面')
    shot('basic'); window.tabs.setCurrentIndex(3); shot('no-subtabs')
    window.tabs.setCurrentIndex(0); window.basic_tabs.setCurrentIndex(1); shot('costs')
    scroll=window.editors['costs'].findChild(QScrollArea); scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()); shot('management-fees')
    window.basic_tabs.setCurrentIndex(2); shot('guarantees')
    window.tabs.setCurrentIndex(1); window.calendar_tabs.setCurrentIndex(0); shot('holiday-makeup')
    window.toggle_lock('holidays')
    def dialog_shot(name,configure=None):
        def capture():
            d=next(d for d in window.findChildren(DateEntryDialog) if d.isVisible())
            if configure: configure(d)
            app.processEvents(); d.grab().save(str(target/(name+'.png'))); d.reject()
        return capture
    QTimer.singleShot(0,dialog_shot('date-dialog')); window.add_row('holidays')
    window.calendar_tabs.setCurrentIndex(2); window.toggle_lock('weather')
    QTimer.singleShot(0,dialog_shot('weather-full',lambda d:d.fields['am'].setText('1'))); window.add_row('weather')
    QTimer.singleShot(0,dialog_shot('weather-half',lambda d:d.fields['pm'].setText('.5'))); window.add_row('weather')
    window.calendar_tabs.setCurrentIndex(3); window.calendar.setSelectedDate(QDate(2026,10,17)); shot('calendar')
    window.tabs.setCurrentIndex(2); window.billing_tabs.setCurrentIndex(2); window.toggle_lock('admin_payments'); shot('admin-payments')
    window.resize(860,650); shot('admin-narrow')
    window.tabs.setCurrentIndex(0); window.basic_tabs.setCurrentIndex(0); shot('basic-narrow')
    window.basic_tabs.setCurrentIndex(1); scroll.verticalScrollBar().setValue(0); shot('costs-narrow')
    window.autosave.stop(); window.session.saved=window.session.pages.copy(); window.close(); instance.close()
print(target)
