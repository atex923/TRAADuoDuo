"""V0.8.1 isolated screenshots; no production data or processes."""
import os,sys,tempfile,argparse
from pathlib import Path
from copy import deepcopy
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from traaduoduo.ui import Window
from traaduoduo.store import ProjectStore
from traaduoduo.instance import MacInstance
from traaduoduo.billing import new_record
from traaduoduo.window_titlebar import WindowTitleBar
from traaduoduo import DISPLAY_VERSION

p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
app=QApplication([])
with tempfile.TemporaryDirectory() as td:
    root=Path(td);guard=MacInstance(root);assert guard.owner
    payload=ProjectStore.create(root/'demo.db','工程管理示範');store=ProjectStore(root/'demo.db');pages=payload['pages']
    for side in pages['costs']['budget'],pages['costs']['contract']:
        side.update(work='1000000',work_tax='50000',award_total='1050000',labor='950000',own_labor='12345.6789',unfinished_tax='50000')
    pages['other_payments']=[dict(new_record('other_payments','transfer',1),item='transfer',stage='first',amount='30000',tax='0',payment_date='2026-10-23',note='示範提撥')]
    pages['contract_payments']=[dict(new_record('contract_payments','contract',1),amount='100000',tax='5000',payment_date='2026-10-23',note='示範計價')]
    pages['admin_payments']['rows']=[dict(new_record('admin_payments','admin',1),amount='3000',tax='150',payment_date='2026-10-23',**{'0C12':'1000','0C11':'1000','0C14':'1000'})]
    store.save(pages,0);w=Window(QSettings(str(root/'qa.ini'),QSettings.Format.IniFormat));guard.activate(w);w.adopt(store.load());w.resize(1680,1120);w.show()
    def shot(name):
        app.processEvents();assert w.grab().save(str(out/(name+'.png')))
    w.basic_tabs.setCurrentIndex(1);shot('costs')
    w.tabs.setCurrentIndex(2)
    for index,name in enumerate(['contract-payments','other-payments','management']):w.billing_tabs.setCurrentIndex(index);shot(name)
    w.tabs.setCurrentIndex(3);shot('detail-formats')
    title=WindowTitleBar(w);title.setFixedWidth(1100);title.show();app.processEvents();assert title.grab().save(str(out/'windows-titlebar-component.png'));title.close()
    w.autosave.stop();w.session.saved=deepcopy(w.session.pages);w.close();guard.close()
print(DISPLAY_VERSION+' screenshots: '+str(out)+'; Qt='+app.platformName())
