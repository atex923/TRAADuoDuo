"""Capture actual V0.6 widgets using generated files and an isolated QA DB."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import argparse
import json
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings,QDate,Qt
from PySide6.QtGui import QImage,QColor,QPdfWriter,QPainter
from PySide6.QtWidgets import QApplication,QMessageBox
from unittest.mock import patch
from traaduoduo.ui import Window
from traaduoduo.store import ProjectStore
from traaduoduo.billing import new_record
from traaduoduo.asset_store import new_asset,inventory
from traaduoduo.aa_import import inspect_aa
from traaduoduo.instance import MacInstance

parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--aa',type=Path);args=parser.parse_args()
target=args.output.resolve();target.mkdir(parents=True,exist_ok=True)
app=QApplication([])
with tempfile.TemporaryDirectory(prefix='traa-v060-') as directory:
    directory=Path(directory);instance=MacInstance(directory)
    if not instance.owner:raise RuntimeError('相同 QA 身分已執行')
    database=directory/'demo.db';payload=ProjectStore.create(database,'站區環境改善工程（示範）');pid=payload['metadata']['project_id'];store=ProjectStore(database,pid)
    p=payload['pages'];p['basic'].update(number='TR-DEMO-001',contract='DEMO-2026-001',contractor='示範營造有限公司',start='2026-10-05',days='100',description='站區設施與環境改善',warranty_note='依契約規定辦理')
    p['costs']['budget'].update(award_total='12000000',work='11428571',own_labor='100000',pollution='60000')
    p['costs']['contract'].update(award_total='10500000',work='10000000',base_price='10800000',own_labor='100000',pollution='55000')
    p['costs']['extensions']=[dict(id='ext-demo',label='臨時設施費',budget='40000',contract='35000')]
    p['admin_payments']['allocations'][0].update(period=1,**{'0C12':'30000','0C11':'20000','0C14':'10000'})
    p['admin_payments']['allocations'][1].update(period=3,**{'0C12':'15000','0C11':'10000','0C14':'5000'})
    p['admin_payments']['rows']=[dict(new_record('admin_payments','expense-'+str(i),i),amount=str(i*600),tax=str(i*30),payment_date='2026-10-16',**{'0C12':str(i*300),'0C11':str(i*200),'0C14':str(i*100)}) for i in [10,2,1,9,3]]
    p['contract_payments']=[dict(new_record('contract_payments','contract-'+str(i),i),amount=str(i*30000),tax=str(i*1500)) for i in [10,2,1,9,3]]
    p['other_payments']=[dict(new_record('other_payments','transfer',1),item='transfer',stage='first',amount='60000'),dict(new_record('other_payments','transfer2',3),item='transfer',stage='second',amount='30000')]
    p['diary']=[dict(id='diary-demo',number=1,date='2026-10-17',description='辦理現場會勘，確認施工界面與安全維護措施。',note='此為示範資料。')]
    p['holidays']=[['2026-10-12','假期（示範）']];p['railway']=[['2026-10-14','疏運（示範）']];p['weather']=[['2026-10-08','0','.5','','0'],['2026-10-15','1','0','','0']]
    if args.aa:
        batch=inspect_aa(args.aa);batch['name']='AA 示範修訂版';batch['filename']='AA_DEMO.xlsx'
        # Public screenshots show layout only, never supplied-project descriptions or amounts.
        for row in batch['rows']:
            values=row['values'];values[1]='DEMO-2026-001';values[3]='示範工程項目 '+values[2]
            values[4]='';values[5]='';values[7]='';values[9]='1';values[10]='1000';values[11]='1000';values[12]='';values[13]='';values[14]='';values[15]=''
        p['details']['budget']=[batch]
    photo=directory/'現況照片.png';image=QImage(600,400,QImage.Format.Format_RGB32);image.fill(QColor('#d7e8d1'));paint=QPainter(image);paint.setPen(QColor('#315f3c'));paint.drawText(40,200,'TRAADuoDuo QA image');paint.end();image.save(str(photo))
    pdf=directory/'契約示範.pdf';writer=QPdfWriter(str(pdf));painter=QPainter(writer);painter.drawText(500,500,'TRAADuoDuo QA PDF');painter.end();del writer
    p['photos']['rows']=[new_asset(photo)];p['documents']['rows']=[inventory(database,pid,'documents',new_asset(pdf))]
    store.save(p,0)
    w=Window(QSettings(str(directory/'qa.ini'),QSettings.Format.IniFormat));instance.activate(w);w.adopt(store.load());w.resize(1440,1000);w.show();app.processEvents()
    def shot(name):
        app.processEvents()
        if not w.grab().save(str(target/(name+'.png'))):raise RuntimeError('擷取失敗')
    shot('contract-execution');w.basic_tabs.setCurrentIndex(1);shot('costs');w.basic_tabs.setCurrentIndex(2);shot('guarantees')
    w.tabs.setCurrentIndex(1);w.calendar_tabs.setCurrentIndex(3);w.calendar.setSelectedDate(QDate(2026,10,17));shot('calendar')
    w.tabs.setCurrentIndex(2)
    for i,name in enumerate(['contract-payments','other-payments','management-payments']):w.billing_tabs.setCurrentIndex(i);shot(name)
    w.tabs.setCurrentIndex(3);shot('aa-details');w.tabs.setCurrentIndex(4);shot('diary');w.tabs.setCurrentIndex(5);w.asset_ui['documents']['table'].setCurrentCell(0,0);w.preview_asset('documents');shot('documents')
    w.tabs.setCurrentIndex(6);w.asset_ui['photos']['table'].setCurrentCell(0,0);w.preview_asset('photos')
    import time
    deadline=time.monotonic()+10
    while w.thumbnail_jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.02)
    shot('photos');w.resize(860,650);w.tabs.setCurrentIndex(2);w.billing_tabs.setCurrentIndex(2);shot('management-narrow')
    metrics=dict(version='V0.6.0',window_width=w.width(),normal_field_width=w.fields['number'].width(),long_field_width=w.fields['name'].width(),summary_pt=w.payment_summaries['admin_payments'].font().pointSize(),period_order=[w.payment_tables['admin_payments'].item(r,0).text() for r in range(5)])
    (target/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2))
    w.autosave.stop();w.session.saved=deepcopy(w.session.pages)
    with patch('traaduoduo.ui.QMessageBox.question',return_value=QMessageBox.StandardButton.Discard):w.close()
    instance.close()
print(target)
