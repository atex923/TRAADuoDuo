"""Generate native UI and export evidence from an isolated QA project."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from copy import deepcopy
import argparse,sys,tempfile,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings,QDate
from PySide6.QtWidgets import QApplication
from traaduoduo.ui import Window
from traaduoduo.store import ProjectStore
from traaduoduo.billing import new_record
from traaduoduo.instance import MacInstance
from traaduoduo.report_export import atomic_export

parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
app=QApplication([])
with tempfile.TemporaryDirectory(prefix='traa-v080-') as directory:
    root=Path(directory);guard=MacInstance(root)
    if not guard.owner:raise RuntimeError('QA 身分已執行')
    payload=ProjectStore.create(root/'demo.db','站區環境改善工程（示範）');store=ProjectStore(root/'demo.db');p=payload['pages'];p['basic'].update(number='TR-DEMO-008',start='2026-10-01',days='30',contractor='示範營造公司',description='站區設施改善與文件管理',warranty_note='依契約辦理')
    for kind in ('budget','contract'):p['costs'][kind].update(work='5000000',work_tax='250000',award_total='5100000',labor='4800000',own_labor='120000',purchased_material='80000',road_stock='30000',road_purchase='20000',supervision='50000',freight='8000',pollution='25000',unfinished_tax='10000')
    p['other_payments']=[dict(new_record('other_payments','t1',1),item='transfer',stage='first',amount='90000'),dict(new_record('other_payments','t2',3),item='transfer',stage='second',amount='45000')]
    for a,amounts in zip(p['admin_payments']['allocations'],[('40000','30000','15000'),('20000','10000','12000')]):a.update(dict(zip(('0C12','0C11','0C14'),amounts)))
    p['admin_payments']['rows']=[dict(new_record('admin_payments','a1',1),amount='18000',tax='900',payment_date='2026-10-10',**{'0C12':'10000','0C11':'5000','0C14':'3000'}),dict(new_record('admin_payments','a2',2),amount='12000',tax='600',payment_date='2026-10-18',**{'0C12':'6000','0C11':'4000','0C14':'2000'})]
    p['diary']=[dict(id='diary-'+str(i),number=i,date='2026-10-'+str(10+i),description=text,note='示範資料；非正式工程') for i,text in [(1,'辦理施工前協調會議'),(2,'提送材料檢驗報告'),(3,'辦理現場查驗，確認材料及施工界面')]]
    p['holidays']=[['2026-10-10','假期示範']];p['railway']=[['2026-10-20','疏運示範']];p['weather']=[['2026-10-15','0','.5','午後降雨','0']]
    store.save(p,0);w=Window(QSettings(str(root/'qa.ini'),QSettings.Format.IniFormat));guard.activate(w);w.adopt(store.load());w.resize(1600,1100);w.show();app.processEvents()
    def shot(name):
        app.processEvents()
        if not w.grab().save(str(out/(name+'.png'))):raise RuntimeError('截圖失敗')
    shot('contract-execution');w.basic_tabs.setCurrentIndex(1);shot('costs')
    w.tabs.setCurrentIndex(2);w.billing_tabs.setCurrentIndex(2);shot('management')
    report=w.report_snapshot();atomic_export(report,out/'management.pdf','pdf',overwrite=True,landscape=True);atomic_export(report,out/'management.xlsx','xlsx',overwrite=True)
    w.tabs.setCurrentIndex(4);w.diary_tabs.setCurrentIndex(0);shot('diary');w.diary_search.setText('材料');shot('diary-search');w.diary_search.clear()
    w.tabs.setCurrentIndex(1);w.calendar_tabs.setCurrentWidget(w.calendar_page);w.calendar.setSelectedDate(QDate(2026,10,22));w.refresh_calendar();shot('calendar');atomic_export(w.report_snapshot(),out/'calendar.pdf','pdf',overwrite=True,landscape=True)
    d=w.about_dialog();d.show();app.processEvents();d.grab().save(str(out/'about.png'));d.close()
    w.tabs.setCurrentIndex(2);w.billing_tabs.setCurrentIndex(2);w.resize(900,760);shot('management-narrow')
    (out/'metrics.json').write_text(json.dumps(dict(version='V0.8.0',schema=10,platform=app.platformName(),auto_save_ms=w.autosave.interval(),allocation_height=w.allocation_table.rowHeight(0),summary_font_pt=w.payment_summaries['admin_payments'].font().pointSize(),summary_height=w.payment_summaries['admin_payments'].height()),ensure_ascii=False,indent=2))
    w.autosave.stop();w.session.saved=deepcopy(w.session.pages);w.close();guard.close()
print(out)
