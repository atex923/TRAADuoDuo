"""Render this program's UI using Qt, without accessing real projects."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QSettings, QDate, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QScrollArea
from traaduoduo.ui import Window, ROOT
from traaduoduo.store import ProjectStore
from traaduoduo.importer import preview_database
from traaduoduo.billing import new_record

app = QApplication([])
target = ROOT / 'docs/screenshots'
target.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / '示範工程.db'
    payload = ProjectStore.create(path, '鐵路站區環境改善工程（示範）')
    basic = dict(payload['pages']['basic'], number='TR-DEMO-001', contract='DEMO-2026-001',
                 contractor='示範營造有限公司', start='2026-09-01', days='100')
    ProjectStore(path).save({'basic': basic, 'holidays': [['2026-09-25', '示範假期']],
                            'weather': [['2026-09-23', '0', '.5', '午後降雨']]}, 0)
    costs=ProjectStore(path).load()['pages']['costs']
    costs['budget'].update(award_total='12000000',work='11428571',work_tax='571429',own_labor='100000')
    costs['contract'].update(award_total='10500000',work='10000000',work_tax='500000',base_price='10800000')
    costs['extensions']=[dict(id='demo1',label='臨時設施費',budget='120000',contract='100000')]
    bids=[dict(id='demo-bid-1',number=1,awarded=True,review_start='2026-07-01',review_end='2026-07-07',online_start='2026-07-08',online_end='2026-07-25',opening='2026-07-28',committee='2026-08-03',award_date='2026-08-10')]
    ProjectStore(path).save({'costs':costs,'bids':bids},1)
    admin=ProjectStore(path).load()['pages']['admin_payments']
    admin['allocations'][0].update(period=1,**{'0C12':'75000','0C11':'35000','0C14':'25000'})
    admin['allocations'][1].update(period=3,**{'0C12':'30000','0C11':'22500','0C14':'15000'})
    admin['allocations'][3].update(period=6,**{'0C12':'-3000','0C11':'-1000','0C14':'-1000'})
    admin['rows']=[dict(new_record('admin_payments','demo-expense',1),amount='33000',tax='1650',payment_date='2026-09-30',**{'0C12':'15000','0C11':'10000','0C14':'8000'})]
    contract=[dict(new_record('contract_payments','demo-contract',1),estimated='1050000',amount='1000000',tax='50000',paid='950000',paid_tax='47500',retention='50000',submitted='2026-09-20',payment_date='2026-09-25',reviewed='2026-09-28')]
    other=[dict(new_record('other_payments','demo-other1',1),item='transfer',stage='first',amount='135000',tax='0',payment_date='2026-09-10'),
           dict(new_record('other_payments','demo-other2',3),item='transfer',stage='second',amount='67500',tax='0',payment_date='2026-10-10'),
           dict(new_record('other_payments','demo-other3',4),item='transfer',stage='third',amount='22500',tax='0',payment_date='2026-11-10'),
           dict(new_record('other_payments','demo-other4',6),item='transfer',stage='final',amount='-5000',tax='0',payment_date='2026-12-10')]
    ProjectStore(path).save({'contract_payments':contract,'other_payments':other,'admin_payments':admin},2)
    settings = QSettings(str(Path(directory) / 'preview.ini'), QSettings.Format.IniFormat)
    window = Window(settings)
    window.adopt(ProjectStore(path).load())
    window.show()
    app.processEvents()
    window.grab().save(str(target / 'main.png'))
    window.tabs.setCurrentIndex(2)
    for index,name in enumerate(['payments_contract.png','payments_other.png','payments_admin.png']):
        window.billing_tabs.setCurrentIndex(index); app.processEvents(); window.grab().save(str(target/name))
    window.resize(860,650); app.processEvents(); window.grab().save(str(target/'payments_narrow.png'))
    window.resize(1160,800); window.toggle_lock('contract_payments')
    def capture_payment_dialog():
        dialog=next(d for d in window.findChildren(QDialog) if d.isVisible())
        dialog.grab().save(str(target/'payment_dialog.png')); dialog.reject()
    QTimer.singleShot(0,capture_payment_dialog); window.edit_payment('contract_payments')
    window.tabs.setCurrentIndex(0)
    window.basic_tabs.setCurrentIndex(1)
    app.processEvents()
    window.grab().save(str(target/'costs.png'))
    scroll=window.editors['costs'].findChild(QScrollArea)
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    app.processEvents()
    window.grab().save(str(target/'management_fees.png'))
    window.basic_tabs.setCurrentIndex(3)
    app.processEvents()
    window.grab().save(str(target/'bids.png'))
    window.basic_tabs.setCurrentIndex(2)
    app.processEvents()
    window.grab().save(str(target / 'guarantees.png'))
    window.resize(860,650)
    window.basic_tabs.setCurrentIndex(0)
    app.processEvents()
    window.grab().save(str(target / 'narrow.png'))
    window.resize(1160,800)
    window.tabs.setCurrentIndex(1)
    window.calendar_tabs.setCurrentIndex(3)
    window.calendar.setSelectedDate(QDate(2026, 9, 23))
    app.processEvents()
    window.grab().save(str(target / 'calendar.png'))
    window.store.add_project('橋梁維修工程（示範）')
    def capture_dialog(name):
        dialog = next(d for d in window.findChildren(QDialog) if d.isVisible())
        dialog.grab().save(str(target / name))
        dialog.reject()
        dialog.deleteLater()
    QTimer.singleShot(0, lambda: capture_dialog('projects.png'))
    window.show_projects(window.store.list_projects())
    app.processEvents()
    source = Path(directory) / '匯入示範.db'
    ProjectStore.create(source,'舊資料轉入工程（示範）')
    QTimer.singleShot(0, lambda: capture_dialog('import.png'))
    window.show_import(preview_database(source))
    window.close()
print(target)
