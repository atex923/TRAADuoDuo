"""Capture actual widgets with generated, isolated QA data."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import argparse,sys,tempfile,json
from pathlib import Path
from datetime import date,timedelta
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from traaduoduo.ui import Window
from traaduoduo.store import ProjectStore
from traaduoduo.asset_store import new_asset
from traaduoduo.instance import MacInstance

parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
app=QApplication([])
with tempfile.TemporaryDirectory(prefix='traa-v070-') as directory:
    root=Path(directory);guard=MacInstance(root)
    if not guard.owner:raise RuntimeError('QA 實例已執行')
    payload=ProjectStore.create(root/'qa.db','站區環境改善工程（示範）');store=ProjectStore(root/'qa.db');pages=payload['pages'];today=date.today()
    pages['diary']=[dict(id='diary-demo',number=1,date=today.isoformat(),description='辦理現場會勘，確認施工界面及文件提送期限。',note='隔離測試資料，不含使用者工程。')]
    for number,offset,work,completed in [(1,-2,'提送安全維護改善成果及照片',''),(2,0,'完成施工計畫書修正並函送審查',''),(3,2,'提送材料檢驗報告及品質查核文件',''),(4,5,'確認交通維持及夜間施工配合事項',''),(5,7,'辦理階段施工進度協調會議',''),(6,-4,'完成現場勘查紀錄歸檔',(today-timedelta(days=2)).isoformat())]:
        pages['deadline_tracking'].append(dict(id='t'+str(number),number=number,issued_at=(today-timedelta(days=7)).isoformat()+(' 09:30' if number==1 else ''),document_no=f'示範工字第00{number}號',due_date=(today+timedelta(days=offset)).isoformat(),work=work,completed_date=completed))
    file=root/'施工文件示範.txt';file.write_text('示範文件，不含真實資料。',encoding='utf-8')
    pages['documents']['rows']=[dict(new_asset(file),number=n,name=name,document_no=f'示範工字第00{n}號',document_date=(today-timedelta(days=n)).isoformat(),note='僅連結／可勾選庫存檔') for n,name in [(10,'現場會勘紀錄'),(1,'施工計畫書'),(2,'材料檢驗報告')]]
    store.save(pages,0);w=Window(QSettings(str(root/'qa.ini'),QSettings.Format.IniFormat));guard.activate(w);w.adopt(store.load());w.resize(1600,1000);w.show();app.processEvents()
    def shot(name):
        app.processEvents()
        if not w.grab().save(str(args.output/(name+'.png'))):raise RuntimeError('無法擷取')
    w.tabs.setCurrentIndex(4);w.diary_tabs.setCurrentIndex(0);shot('diary')
    w.diary_tabs.setCurrentIndex(1);shot('deadline-tracking');w.tracking_filter.setCurrentIndex(2);shot('deadline-completed');w.tracking_filter.setCurrentIndex(0)
    w.tabs.setCurrentIndex(5);w.asset_ui['documents']['sort'].setCurrentIndex(3);shot('documents')
    w.set_document_columns(['document_no','note']);shot('documents-hidden')
    w.tabs.setCurrentIndex(4);w.resize(900,700);shot('deadline-narrow')
    (args.output/'metrics-v070.json').write_text(json.dumps(dict(version='V0.7.0',schema=9,platform=app.platformName(),generated_date=today.isoformat(),deadline_rows=w.tracking_table.rowCount(),upcoming_rows=w.upcoming_table.rowCount(),document_order=[w.asset_ui['documents']['table'].item(i,0).text() for i in range(3)]),ensure_ascii=False,indent=2),encoding='utf-8')
    w.autosave.stop();w.session.saved=deepcopy(w.session.pages);w.close();guard.close()
print(args.output)
