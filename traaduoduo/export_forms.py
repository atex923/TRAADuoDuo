"""Capture current views on the GUI thread, then export immutable data."""
from copy import deepcopy
from datetime import date,datetime
from decimal import Decimal,InvalidOperation
from pathlib import Path
import calendar
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QFormLayout,QComboBox,QCheckBox,QLabel,QDialogButtonBox,QFileDialog,QMessageBox
from .report_export import Report,Column,atomic_export
from .billing import PAYMENT_KEYS,CATEGORIES,summary,contract_progress,fmt,STAGES
from .forms import DateField
from .finance import FIELDS
from .presentation import MoneyField
from .aa_import import TABLES
from .tracking import TRACKING_COLUMNS,deadline_status

MONEY_KEYS={'amount','tax','estimated','paid','paid_tax','retention',*[k for k,v in CATEGORIES]}
DATE_KEYS={'date','due_date','completed_date','overdue_date','document_date','payment_date','reviewed','submitted','opening','committee','award_date'}

def column(key,title):
    return Column(key,title,'money' if key in MONEY_KEYS else 'number' if key in ('number','period') else 'date' if key in DATE_KEYS else 'issued' if key=='issued_at' else 'text')

class ExportForms:
    def report_snapshot(self,all_rows=False,all_columns=False,draft=False):
        if not self.session:raise ValueError('請先開啟工程')
        pages=deepcopy(self.session.pages);key=self.current_page();main=self.tabs.tabText(self.tabs.currentIndex());title=main
        subtabs=self.active_subtabs()
        if subtabs:title+='／'+subtabs.tabText(subtabs.currentIndex())
        scope='全部紀錄' if all_rows else '目前檢視範圍';columns=[];rows=[];sums=[];table=None;data={};keys=[]
        if key in ('basic','guarantees'):
            fields=self.fields if key=='basic' else self.guarantee_fields;columns=[Column('field','欄位'),Column('value','內容')]
            for name,field in fields.items():
                value=pages[key].get(name,'')
                if isinstance(field,MoneyField):value=Decimal(field.value()) if field.value() else ''
                elif isinstance(field,DateField) and value:value=date.fromisoformat(value)
                elif name in ('days','initial_days','acceptance_days','warranty_years') and value!='':value=int(value)
                elif isinstance(value,bool):value='是' if value else '否'
                rows.append((field.accessibleName() or name,value))
        elif key=='costs':
            columns=[Column('field','費用項目'),Column('budget','預算金額','money'),Column('contract','契約金額','money')]
            rows=[(label,pages['costs']['budget'][name],pages['costs']['contract'][name]) for name,label in FIELDS]
            rows.extend((r['label'],r['budget'],r['contract']) for r in pages['costs']['extensions'])
        elif key=='bids':
            table=self.bid_table;names=['awarded','number','review','online','opening','committee','award_date'];indices=[i for i in range(7) if all_columns or not table.isColumnHidden(i)]
            columns=[column(names[i],table.horizontalHeaderItem(i).text()) for i in indices];lookup={r['id']:r for r in pages['bids']}
            for i in range(table.rowCount()):
                row=lookup[table.item(i,0).data(Qt.ItemDataRole.UserRole)]
                values=['＊' if row['awarded'] else '',row['number'],(' ～ '.join([row['review_start'],row['review_end']]) if row['review_start'] or row['review_end'] else ''),(' ～ '.join([row['online_start'],row['online_end']]) if row['online_start'] or row['online_end'] else ''),row['opening'],row['committee'],row['award_date']]
                rows.append(tuple(values[j] for j in indices))
            table=None
        elif key in PAYMENT_KEYS:
            table=self.payment_tables[key];keys=self.payment_columns[key];values=pages[key]['rows'] if key=='admin_payments' else pages[key];data={r['id']:r for r in values}
            period=None if all_rows else self.payment_periods[key].currentData();scope='全部期別' if period is None else f'截至第 {period} 期（含較早期）'
            data={rid:r for rid,r in data.items() if period is None or r['period']<=period}
            values=summary(pages,key,period);sums=[('累計計價',fmt(values['amount'])),('累計稅金',fmt(values['tax']))]
            if key=='contract_payments':sums.append(('累計計價進度',contract_progress(pages,period)))
            if key=='admin_payments':sums.extend((label+'可支用',fmt(values[c+'_available'])) for c,label in CATEGORIES)
        elif key in ('documents','photos'):
            ui=self.asset_ui[key];table=ui['table'];keys=ui['fields'];values=pages[key]['rows'];data={r['id']:r for r in values};categories={r['id']:r['name'] for r in pages[key]['categories']}
            for row in data.values():row['stock']='是' if row['stock'] else '否';row['category']=categories.get(row['category'],'未分類');row['status']='庫存' if row['stock']=='是' else '連結'
        elif key=='diary':
            table=self.diary_table;keys=[('date','日期'),('description','說明'),('note','備註')];data={r['id']:r for r in pages[key]}
            scope='全部事記' if all_rows else '搜尋：'+(self.diary_search.text() or '全部')+'／'+self.diary_sort.currentText()
        elif key=='deadline_tracking':
            table=self.tracking_table;keys=TRACKING_COLUMNS;data={r['id']:dict(r,alert=deadline_status(r)['text'],overdue_date=deadline_status(r)['overdue_date']) for r in pages[key]};scope='全部期限' if all_rows else self.tracking_filter.currentText()
        elif key=='details':
            kind=list(TABLES)[self.detail_tabs.currentIndex()];ui=self.detail_ui[kind];batch=next((r for r in pages['details'][kind] if r['id']==ui['versions'].currentData()),None)
            if not batch:raise ValueError('目前修訂版沒有可匯出資料')
            scope='修訂版：'+batch.get('name',batch['filename'])+'／'+('全部層級' if all_rows else ui['levels'].currentText())
            tree=ui['tree'];ids=[]
            def visit(item,parents_visible=True):
                visible=parents_visible and not item.isHidden()
                if visible:ids.append(item.data(0,Qt.ItemDataRole.UserRole))
                for i in range(item.childCount()):visit(item.child(i),visible and item.isExpanded())
            for i in range(tree.topLevelItemCount()):visit(tree.topLevelItem(i))
            indices=[i for i in range(tree.columnCount()) if all_columns or not tree.isColumnHidden(i)]
            columns=[Column(str(i),tree.headerItem().text(i),'money' if i in (10,11) else 'number' if i in (9,12) else 'text') for i in indices]
            by_id={r['id']:r for r in batch['rows']};ordered=batch['rows'] if all_rows else [by_id[rid] for rid in ids]
            rows=[tuple(r['values'][i] for i in indices) for r in ordered]
        elif key in self.tables:
            title+='／'+dict(holidays='假期',makeup='補班',railway='鐵路疏運',weather='晴雨').get(key,key)
            table=self.tables[key];indices=[i for i in range(table.columnCount()) if all_columns or not table.isColumnHidden(i)];columns=[Column(str(i),table.horizontalHeaderItem(i).text(),'date' if i==0 else 'text') for i in indices]
            rows=[tuple(table.item(r,i).text() if table.item(r,i) else '' for i in indices) for r in range(table.rowCount())]
        elif self.tabs.currentIndex()==1:
            year,month=self.calendar.yearShown(),self.calendar.monthShown();scope=f'{year:04}-{month:02} 施工月曆'
            columns=[Column('date','日期','date'),Column('week','星期'),Column('holiday','假期／補班'),Column('railway','疏運'),Column('weather','晴雨'),Column('work','累計工作日')]
            for day in range(1,calendar.monthrange(year,month)[1]+1):
                value=date(year,month,day);info=self.calendar.day_details.get(value.isoformat(),{});rows.append((value.isoformat(),'一二三四五六日'[value.weekday()],info.get('holiday') or info.get('makeup',''),info.get('railway',''),info.get('weather',''),info.get('work','')))
        else:raise ValueError('此頁尚無可匯出的資料表')
        if table is not None and keys:
            indices=[i for i in range(len(keys)) if all_columns or not table.isColumnHidden(i)];columns=[column(*keys[i]) for i in indices]
            ordered=[]
            for i in range(table.rowCount()):
                item=table.item(i,0);rid=item.data(Qt.ItemDataRole.UserRole) if item else None
                if rid in data:ordered.append(data[rid])
            if all_rows:
                used={r['id'] for r in ordered};ordered.extend(r for rid,r in data.items() if rid not in used)
                if key=='diary':ordered=self.diary_rows(all_rows=True)
                elif key in ('documents','photos'):
                    from .tracking import document_order
                    ordered=document_order(ordered,self.asset_ui[key]['sort'].currentIndex())
                elif key=='deadline_tracking':ordered.sort(key=lambda r:r['number'])
            for row in ordered:
                values=[]
                for i in indices:
                    field,label=keys[i];value=row.get(field,'')
                    if field=='stage':value=dict((k,t) for k,t,_ in STAGES).get(value,value)
                    if field=='item':value={'transfer':'管理費提撥','0A':'0A計價','legacy':'待分類'}.get(value,value)
                    if field=='status' and key in PAYMENT_KEYS:value='提撥' if row.get('item')=='transfer' else ''
                    values.append(value)
                rows.append(tuple(values))
        if not columns:raise ValueError('沒有選取任何匯出欄位')
        return Report(pages['basic']['name'],title,scope,tuple(columns),tuple(rows),tuple(sums),draft,scope.endswith('施工月曆'))

    def export_report_dialog(self):
        if not self.session:return
        if self._auto_job is not None:self._auto_after.append(self.export_report_dialog);return
        self.capture_basic();dialog=QDialog(self);dialog.setWindowTitle('匯出 PDF／Excel');form=QFormLayout(dialog)
        try:preview=self.report_snapshot()
        except (ValueError,ArithmeticError) as exc:QMessageBox.information(self,'無可匯出資料',str(exc));return
        form.addRow('工程',QLabel(preview.project));form.addRow('來源表格',QLabel(preview.title));form.addRow('目前範圍',QLabel(preview.scope+f'／{len(preview.rows)} 筆／{len(preview.columns)} 欄'))
        kind=QComboBox();kind.addItems(['PDF 報表','Excel（.xlsx）']);form.addRow('格式',kind)
        paper=QComboBox();paper.addItems(['A4','A3']);form.addRow('紙張',paper)
        orientation=QComboBox();orientation.addItems(['直向','橫向']);form.addRow('方向',orientation)
        all_rows=QCheckBox('全部紀錄（忽略搜尋、分類、期別與折疊篩選）');form.addRow(all_rows)
        all_columns=QCheckBox('全部欄位（包含目前隱藏欄）');form.addRow(all_columns)
        policy=QComboBox();policy.addItems(['先儲存再匯出','匯出目前草稿（明確標示）']);form.addRow('資料狀態',policy)
        form.addRow(QLabel('預設依目前檢視排序、篩選及可見欄位匯出；文件／照片僅輸出清單。寬表PDF分欄組列印，重複識別欄。'))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);form.addRow(buttons);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        extension='pdf' if kind.currentIndex()==0 else 'xlsx';path,_=QFileDialog.getSaveFileName(self,'匯出報表',self.session.pages['basic']['name']+'.'+extension,f'{extension.upper()} (*.{extension})')
        if not path:return
        if not path.lower().endswith('.'+extension):path+='.'+extension
        overwrite=Path(path).exists()
        if overwrite and QMessageBox.question(self,'確認覆寫','覆寫這個輸出檔？')!=QMessageBox.StandardButton.Yes:return
        paper_name=paper.currentText();wide=orientation.currentIndex()==1;rows_option=all_rows.isChecked();columns_option=all_columns.isChecked()
        def export():
            try:
                report=self.report_snapshot(rows_option,columns_option,draft=bool(self.session.dirty()))
                self.io(lambda:atomic_export(report,path,extension,overwrite,paper_name,wide),lambda p:self.message.setText('匯出完成：'+p))
            except (ValueError,ArithmeticError) as exc:QMessageBox.warning(self,'無法匯出',str(exc))
        if policy.currentIndex()==0:self.save(after=export)
        else:export()
