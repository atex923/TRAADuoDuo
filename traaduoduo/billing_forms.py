"""Locked payment ledgers and explicit management-fee allocation editor."""
from copy import deepcopy
from decimal import Decimal
import uuid
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QComboBox,
    QDialog,QDialogButtonBox,QLineEdit,QScrollArea,QTableWidgetItem,QAbstractItemView,QHeaderView,QMessageBox,QToolTip)
from .forms import ProjectTable,DateField,info_button
from .billing import (PAYMENT_KEYS,CONTRACT_MONEY,DATES,CATEGORIES,STAGES,new_record,validate_billing,
                      summary,stage_summary,period_options,fmt,number,total,warnings,allocation_filled,contract_progress,ADMIN_MONEY,ADMIN_DATES,effective_period)
from .presentation import MoneyField,CompactSummary

class MoneyItem(QTableWidgetItem):
    def __lt__(self,other):
        try:
            return number(self.text() or '0')<number(other.text() or '0')
        except (ValueError,ArithmeticError):
            return self.text()<other.text()

class BillingForms:
    @staticmethod
    def billing_field_wrapper(widget,label,hint):
        wrapper=QWidget(); line=QHBoxLayout(wrapper); line.setContentsMargins(0,0,0,0); line.setSpacing(4)
        line.addWidget(widget,1)
        info=info_button(wrapper,label,hint)
        if info: line.addWidget(info)
        return wrapper

    def build_billing(self):
        self.payment_tables={}; self.payment_buttons={}; self.payment_periods={}; self.payment_summaries={}
        self.payment_counts={}; self.allocation_buttons=[]
        self.payment_columns={
            'contract_payments':[('period','期數'),*CONTRACT_MONEY,*DATES,('note','備註')],
            'other_payments':[('period','期數'),('payment_date','計價日期'),('item','計價項目'),('stage','提撥階段'),('amount','計價金額'),('tax','計價稅金'),('status','分攤狀態'),('note','備註')],
            'admin_payments':[('period','期數'),*CATEGORIES,*ADMIN_MONEY,*ADMIN_DATES,('note','備註')]}
        for key,title in zip(PAYMENT_KEYS,['發包工程','發包以外','管理費']):
            outer,content=self.edit_page(key); self.billing_tabs.addTab(outer,title)
            layout=QVBoxLayout(content)
            if key=='admin_payments':
                scroll=QScrollArea(); scroll.setWidgetResizable(True); body=QWidget(); box=QVBoxLayout(body)
                layout.addWidget(scroll); scroll.setWidget(body); layout=box
                self.allocation_table=ProjectTable(4,11)
                self.allocation_table.setHorizontalHeaderLabels(['階段','比例提示','管理費提撥','分攤合計',*[label for _,label in CATEGORIES],'累計提撥','累計分攤','檢查狀態','操作'])
                self.allocation_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                self.allocation_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                self.allocation_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
                row_height=round(18*self.logicalDpiY()/72);self.allocation_table.verticalHeader().setMinimumSectionSize(1);self.allocation_table.verticalHeader().setDefaultSectionSize(row_height)
                for r in range(4):self.allocation_table.setRowHeight(r,row_height)
                self.allocation_table.setFixedHeight(row_height*4+self.allocation_table.horizontalHeader().sizeHint().height()+28)
                self.allocation_table.cellDoubleClicked.connect(lambda row,*_:self.edit_allocation(row))
                layout.addWidget(self.allocation_table)
                allocation_actions=QHBoxLayout(); self.allocation_button=QPushButton('編輯選取階段分攤')
                self.allocation_button.clicked.connect(lambda:self.edit_allocation(self.allocation_table.currentRow()))
                self.allocation_button.hide()
                self.available_basis_combo=QComboBox()
                self.available_basis_combo.addItem('可支用：截至所選期生效分攤－所選期支用','period')
                self.available_basis_combo.setToolTip('固定規則：分攤與支用都截至所選期，不能改為全階段模式。')
                self.available_basis_combo.hide()
                for index in range(4):
                    button=QPushButton('編輯分攤')
                    button.setAccessibleName(STAGES[index][1]+'編輯分攤')
                    button.clicked.connect(lambda checked=False,i=index:self.edit_allocation(i))
                    self.allocation_table.setCellWidget(index,10,button); self.allocation_buttons.append(button)
                policy=QLabel('提撥每階段限一筆，改期或調整請編輯原紀錄。60／30／10只提示，不自動產生計價；分攤三欄皆填才標示已填，0為已填。')
                policy.setWordWrap(True); layout.addWidget(policy)
            top=QHBoxLayout(); self.payment_periods[key]=QComboBox()
            self.payment_periods[key].setFixedWidth(180)
            self.payment_periods[key].addItem('全部期別',None)
            self.payment_periods[key].currentIndexChanged.connect(lambda *_,k=key:self.refresh_payment_summary(k))
            top.addWidget(QLabel('累計截至')); top.addWidget(self.payment_periods[key])
            layout.addLayout(top)
            label=CompactSummary() if key=='admin_payments' else QLabel(); label.setWordWrap(True); label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.payment_summaries[key]=label; layout.addWidget(label)
            font=label.font(); font.setPointSize(16); label.setFont(font)
            label.setStyleSheet('QLabel {background:#CEFFCE;color:#173a22;font-size:16pt;padding:8px;border-radius:5px;}')
            if key=='admin_payments':
                label.setObjectName('adminStatistics')
                label.setStyleSheet('QTextBrowser {background:#CEFFCE;color:#173a22;font-size:16pt;padding:0px;border:1px solid #94bc94;}')
            actions=QHBoxLayout(); self.payment_buttons[key]=[]
            for text,handler in [('新增',lambda checked=False,k=key:self.edit_payment(k)),
                ('編輯',lambda checked=False,k=key:self.edit_selected_payment(k)),
                ('移除',lambda checked=False,k=key:self.remove_payment(k))]:
                button=QPushButton(text); button.clicked.connect(handler); actions.addWidget(button); self.payment_buttons[key].append(button)
            if key=='admin_payments':
                top.addLayout(actions)
                count=QLabel(); self.payment_counts[key]=count; top.addWidget(count,1)
            else:
                count=QLabel();count.setWordWrap(True);self.payment_counts[key]=count;top.addWidget(count,1)
                actions.addStretch(); layout.addLayout(actions)
            table=ProjectTable(0,len(self.payment_columns[key])); self.payment_tables[key]=table
            table.setHorizontalHeaderLabels([label for _,label in self.payment_columns[key]])
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.setSortingEnabled(True); table.setMinimumHeight(195)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            for col,(field,_) in enumerate(self.payment_columns[key]):
                table.setColumnWidth(col,65 if field=='period' else 140)
            table.cellDoubleClicked.connect(lambda *_,k=key:self.edit_selected_payment(k))
            layout.addWidget(table)
        self.billing_warning=QLabel(); self.billing_warning.setWordWrap(True)
        self.billing_warning.setStyleSheet('color:#a1261c;')
        layout.addWidget(self.billing_warning)

    def payment_rows(self,key):
        value=self.session.pages[key]
        return value['rows'] if key=='admin_payments' else value

    def populate_billing(self):
        before=self.loading; self.loading=True
        reset=getattr(self,'billing_project',None)!=self.store.project_id
        self.billing_project=self.store.project_id
        stages={s['stage']:s for s in stage_summary(self.session.pages)}
        for key,table in self.payment_tables.items():
            rows=self.payment_rows(key); combo=self.payment_periods[key]
            selected=None if reset else combo.currentData()
            combo.blockSignals(True); combo.clear(); combo.addItem('全部期別',None)
            periods=set(period_options(rows))
            if key=='admin_payments':
                periods.update(p for a in self.session.pages[key]['allocations'] if (p:=effective_period(self.session.pages,a['stage'])) is not None)
            for period in sorted(periods):
                combo.addItem('第 '+str(period)+' 期',period)
            combo.setCurrentIndex(max(0,combo.findData(selected))); combo.blockSignals(False)
            table.setSortingEnabled(False); table.setRowCount(len(rows))
            for r,row in enumerate(rows):
                stage=stages.get(row.get('stage'))
                for c,(field,_) in enumerate(self.payment_columns[key]):
                    text=row.get(field,'')
                    if field=='item':
                        text={'transfer':'管理費提撥','0A':'0A計價','legacy':'待分類：'+row.get('legacy_item','')}.get(text,text)
                    if field=='stage':
                        text=stage['label'] if stage else ('待指定' if row.get('item')=='transfer' else '')
                    if field=='status':
                        text=('已填分攤' if stage and stage['filled'] else '待分攤') if row.get('item')=='transfer' else ''
                    numeric=field in {k for k,_ in CONTRACT_MONEY+CATEGORIES+ADMIN_MONEY} or field in ('amount','tax')
                    cell=MoneyItem(fmt(text)) if numeric else MoneyItem(str(text)) if field=='period' else QTableWidgetItem(str(text))
                    if field=='period':
                        cell.setData(Qt.ItemDataRole.DisplayRole,row['period'])
                    cell.setTextAlignment((Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignHCenter)|Qt.AlignmentFlag.AlignVCenter)
                    cell.setData(Qt.ItemDataRole.UserRole,row['id']); cell.setToolTip(str(text))
                    if row.get('item')=='transfer' and field in ('amount','status'):
                        cell.setForeground(QColor('#1657b5' if stage and stage['filled'] else '#bd1b1b'))
                    table.setItem(r,c,cell)
            table.setSortingEnabled(True); table.sortItems(0,Qt.SortOrder.AscendingOrder)
        for r,(stage,_,_) in enumerate(STAGES):
            value=stages[stage]; a=value['allocation']
            cells=[value['label'],value['ratio'],fmt(value['transfer']),fmt(value['allocated']),
                   *[fmt(a[c]) for c,_ in CATEGORIES],fmt(value['running_transfer']),fmt(value['running_allocation']),
                   '；'.join(value['warnings']) or ('已填分攤' if value['filled'] else '待分攤')]
            for c,text in enumerate(cells):
                item=QTableWidgetItem(text); item.setToolTip(text)
                item.setTextAlignment((Qt.AlignmentFlag.AlignRight if 2<=c<=8 else Qt.AlignmentFlag.AlignHCenter)|Qt.AlignmentFlag.AlignVCenter)
                if c in (2,3,9):
                    item.setForeground(QColor('#1657b5' if value['filled'] else '#bd1b1b'))
                self.allocation_table.setItem(r,c,item)
        if not self.allocation_table.property('widthSettingsInstalled'):
            for col,width in enumerate([190,70,95,95,100,110,110,100,100,160,110]):
                self.allocation_table.setColumnWidth(col,width)
        self.allocation_table.horizontalHeader().setStretchLastSection(False)
        self.available_basis_combo.setCurrentIndex(self.available_basis_combo.findData(self.session.pages['admin_payments']['available_basis']))
        self.billing_warning.setText('；'.join(warnings(self.session.pages)) or '計價資料檢查：無警告。')
        self.loading=before
        for key in PAYMENT_KEYS:
            self.refresh_payment_summary(key)

    def refresh_payment_summary(self,key):
        if not self.session:
            return
        rows=self.payment_rows(key); period=self.payment_periods[key].currentData()
        values=summary(self.session.pages,key,period)
        text=f'紀錄 {len(rows)} 筆／總計 {len(period_options(rows))} 個期別　'
        text+='（全部期別）' if period is None else f'（截至第{period}期，含較早期）'
        self.payment_counts[key].setText(text); text=''
        names=[('amount','累計計價'),('tax','累計稅金')]
        if key=='contract_payments':
            names += [('paid','累計實發'),('paid_tax','累計實發稅金'),('retention','累計保留款')]
        elif key=='other_payments':
            names += [('transfer','累計管理費提撥'),('0A','累計0A計價')]
        else:
            names += [(c,'累計'+label) for c,label in CATEGORIES]
            names += [(c+'_available',label+'可支用') for c,label in CATEGORIES]
            if values['undated_allocations']:
                text+=f'\n⚠ {values["undated_allocations"]} 筆分攤尚無唯一對應提撥，暫未納入餘額。'
        if key=='admin_payments':
            rows=[]
            for title,group in [('計價累計',names[:2]),('費別累計',names[2:5]),('可支用額',names[5:8])]:
                cells='<td align="left">'+title+'　</td>'+''.join('<td align="left">'+label.replace('累計','').replace('可支用','')+'　'+fmt(values[field])+' 元　</td>' for field,label in group)
                rows.append('<tr>'+cells+'</tr>')
            self.payment_summaries[key].setText('<div style="font-size:16pt">累計計價與可支用額</div><table style="font-size:16pt" cellspacing="0" cellpadding="0">'+''.join(rows)+'</table>'+text)
        else:
            display='　｜　'.join(label+' '+fmt(values[field])+' 元' for field,label in names)
            if key=='contract_payments':
                display+='\n累計計價進度：'+contract_progress(self.session.pages,period)
                self.payment_summaries[key].setToolTip('（截至所選期累計計價＋累計稅金）÷ 含稅契約金額 × 100%')
            self.payment_summaries[key].setText(display)

    def selected_payment(self,key):
        table=self.payment_tables[key]; row=table.currentRow()
        if row<0 or not self.session:
            return None
        rid=table.item(row,0).data(Qt.ItemDataRole.UserRole)
        return next((r for r in self.payment_rows(key) if r['id']==rid),None)

    def edit_selected_payment(self,key):
        row=self.selected_payment(key)
        if row:
            self.edit_payment(key,row)

    def edit_payment(self,key,row=None):
        if not self.session or key not in self.session.unlocked:
            return
        existing=deepcopy(row) if row else new_record(key,uuid.uuid4().hex,max((r['period'] for r in self.payment_rows(key)),default=0)+1)
        dialog=QDialog(self); dialog.setWindowTitle('工程計價資料'); dialog.setObjectName('paymentDialog')
        box=QVBoxLayout(dialog); grid=QGridLayout(); box.addLayout(grid); fields={}
        columns=[('period','期數')]+([('item','計價項目'),('stage','提撥階段'),('amount','計價金額'),('tax','計價稅金'),('payment_date','計價日期')] if key=='other_payments' else [*CATEGORIES,*ADMIN_MONEY,*ADMIN_DATES] if key=='admin_payments' else CONTRACT_MONEY+DATES)+[('note','備註')]
        for index,(field,label) in enumerate(columns):
            if field in ('item','stage'):
                widget=QComboBox()
                choices=[('0A','0A計價'),('transfer','管理費提撥'),('legacy','待分類（舊資料）')] if field=='item' else [('', '未指定'),*[(s,label) for s,label,_ in STAGES]]
                for data,title in choices:
                    widget.addItem(title,data)
                widget.setCurrentIndex(max(0,widget.findData(existing[field])))
            else:
                widget=DateField() if field in {k for k,_ in DATES+ADMIN_DATES} else MoneyField(2) if field in {k for k,_ in CONTRACT_MONEY+CATEGORIES+ADMIN_MONEY} or field in ('amount','tax') else QLineEdit()
                widget.setText(str(existing.get(field,'')))
                widget.setAlignment(Qt.AlignmentFlag.AlignRight if isinstance(widget,MoneyField) else Qt.AlignmentFlag.AlignCenter)
                if field=='period':
                    widget.setToolTip('正整數業務期別；可同一期多筆，累計按期數，不按列號或日期。')
            widget.setObjectName('payment_'+field); widget.setAccessibleName(label)
            hint=('正整數業務期別；同一期可多筆，不按日期或列號累計。' if field=='period' else
                  '每階段限一筆管理費提撥；改期請編輯原紀錄。不依日期猜測，比例不自動產生紀錄。' if field=='stage' else
                  '日期可留空；日曆取消不填入今天。' if field in {k for k,_ in DATES} else
                  '保存十進位原值，支援千分位；空白不同於0，不推定稅率或自動變號。管理費計價合計為三費別之和。' if field in {k for k,_ in CONTRACT_MONEY+CATEGORIES} else label)
            fields[field]=widget; grid.addWidget(QLabel(label),index//2,(index%2)*2)
            grid.addWidget(self.billing_field_wrapper(widget,label,hint),index//2,(index%2)*2+1)
        if key=='admin_payments':
            fields['amount'].setReadOnly(True)
            def recalculate():
                try:
                    entered=[fields[c].text() for c,_ in CATEGORIES if fields[c].text().strip()]
                    fields['amount'].setText(str(sum((number(text) for text in entered),Decimal(0))) if entered else '')
                except (ValueError,ArithmeticError):
                    fields['amount'].setText('')
            for c,_ in CATEGORIES:
                fields[c].textChanged.connect(recalculate)
            recalculate()
        if key=='other_payments':
            def item_changed():
                fields['stage'].setEnabled(fields['item'].currentData()=='transfer')
            fields['item'].currentIndexChanged.connect(item_changed); item_changed()
        hint=QLabel('金額保留原始十進位；未填≠0，不自動拆稅。估驗金額（稅）先保存原值，不推定含稅公式。負數不自動轉號；請留意頁面警告。')
        hint.setWordWrap(True); box.addWidget(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); box.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('儲存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.rejected.connect(dialog.reject)
        def submit():
            try:
                candidate=deepcopy(existing)
                for field,widget in fields.items():
                    candidate[field]=widget.currentData() if isinstance(widget,QComboBox) else widget.value() if isinstance(widget,MoneyField) else widget.text().strip()
                    if field in {k for k,_ in CONTRACT_MONEY+CATEGORIES}:
                        candidate[field]=candidate[field].replace(',','')
                candidate['period']=int(candidate['period'])
                if key=='other_payments' and candidate['item']!='transfer':
                    candidate['stage']=''
                if self.submit_payment(key,candidate):
                    dialog.accept()
            except (ValueError,ArithmeticError) as exc:
                QMessageBox.warning(dialog,'計價資料未完成',str(exc))
        buttons.accepted.connect(submit); dialog.resize(760,450); dialog.exec()

    def submit_payment(self,key,candidate):
        if not self.session or key not in self.session.unlocked:
            return False
        value=deepcopy(self.session.pages[key]); rows=value['rows'] if key=='admin_payments' else value
        updated=[r for r in rows if r['id']!=candidate['id']]+[deepcopy(candidate)]
        if key=='admin_payments':
            value['rows']=updated
        else:
            value=updated
        try:
            validate_billing(key,value)
            if key=='other_payments' and candidate['item']=='transfer' and not candidate['stage'] and not any(r['id']==candidate['id'] for r in rows):
                raise ValueError('新增管理費提撥請明確選擇階段；不依日期猜測')
        except (ValueError,ArithmeticError,KeyError) as exc:
            QMessageBox.warning(self,'計價資料未完成',str(exc)); return False
        self.session.change(key,value); self.populate_billing(); self.changed(); return True

    def remove_payment(self,key):
        row=self.selected_payment(key)
        if not row or key not in self.session.unlocked:
            return
        if QMessageBox.question(self,'移除計價明細','確定移除此筆？累計及連動值會依剩餘明細重算。')!=QMessageBox.StandardButton.Yes:
            return
        value=deepcopy(self.session.pages[key]); rows=[r for r in self.payment_rows(key) if r['id']!=row['id']]
        if key=='admin_payments':
            value['rows']=rows
        else:
            value=rows
        self.session.change(key,value); self.populate_billing(); self.changed()

    def edit_allocation(self,index):
        if not self.session or 'admin_payments' not in self.session.unlocked or not 0<=index<4:
            return
        if not self.allocation_allowed(index):
            self.message.setText('請先儲存上一階段分攤並建立對應提撥'); return
        stage=STAGES[index][0]; value=self.session.pages['admin_payments']
        existing=next(a for a in value['allocations'] if a['stage']==stage)
        dialog=QDialog(self); dialog.setObjectName('allocationDialog'); dialog.setWindowTitle(STAGES[index][1])
        box=QVBoxLayout(dialog); grid=QGridLayout(); box.addLayout(grid); fields={}
        for r,(field,label) in enumerate(CATEGORIES):
            widget=MoneyField(2);widget.setAlignment(Qt.AlignmentFlag.AlignRight);widget.setText(str(existing[field])); widget.setObjectName('allocation_'+field); fields[field]=widget
            grid.addWidget(QLabel(label),r,0)
            grid.addWidget(self.billing_field_wrapper(widget,label,'三費別皆填才算已填，可明確填0；有效期由同階段提撥期數連動。'),r,1)
        hint=QLabel('提撥由發包以外連動，不可在此改寫。三費別皆填（可填0）才標示已填分攤；留空表示尚未分攤。末期負數檢查僅警告，不自動變號。')
        hint.setWordWrap(True); box.addWidget(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); box.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('儲存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.rejected.connect(dialog.reject)
        def submit():
            try:
                candidate=dict(existing,**{k:w.value() for k,w in fields.items()})
                if candidate['period']!='':
                    candidate['period']=int(candidate['period'])
                if self.submit_allocation(candidate):
                    dialog.accept()
            except ValueError as exc:
                QMessageBox.warning(dialog,'分攤資料未完成',str(exc))
        buttons.accepted.connect(submit); dialog.resize(560,300); dialog.exec()

    def submit_allocation(self,candidate):
        if not self.session or 'admin_payments' not in self.session.unlocked:
            return False
        value=deepcopy(self.session.pages['admin_payments'])
        try:
            if candidate['stage'] not in {s for s,_,_ in STAGES}:
                raise ValueError('未知分攤階段')
            index=next(i for i,(s,_,_) in enumerate(STAGES) if s==candidate['stage'])
            if not self.allocation_allowed(index):
                raise ValueError('請先儲存上一階段分攤並建立對應提撥')
            value['allocations']=[deepcopy(candidate) if a['stage']==candidate['stage'] else a for a in value['allocations']]
            validate_billing('admin_payments',value)
        except (ValueError,ArithmeticError,KeyError) as exc:
            QMessageBox.warning(self,'分攤資料未完成',str(exc)); return False
        self.session.change('admin_payments',value); self.populate_billing(); self.changed()
        self.save()
        return True

    def allocation_allowed(self,index):
        if index==0: return True
        if not self.session: return False
        stage=STAGES[index-1][0]
        prior=next(a for a in self.session.saved['admin_payments']['allocations'] if a['stage']==stage)
        current=next(a for a in self.session.pages['admin_payments']['allocations'] if a['stage']==stage)
        return prior==current and allocation_filled(prior) and effective_period(self.session.pages,stage) is not None and effective_period(self.session.saved,stage)==effective_period(self.session.pages,stage)

    def apply_billing_locks(self,ready):
        for key,buttons in self.payment_buttons.items():
            editable=bool(ready and key in self.session.unlocked)
            for button in buttons:
                button.setEnabled(editable)
        editable=bool(ready and 'admin_payments' in self.session.unlocked)
        self.allocation_button.setEnabled(editable); self.available_basis_combo.setEnabled(False)
        for index,button in enumerate(self.allocation_buttons):
            allowed=self.allocation_allowed(index)
            button.setEnabled(editable and allowed)
            button.setText('編輯分攤' if allowed else '待上期填妥')
            button.setToolTip('上一階段分攤與對應提撥儲存後開放' if not allowed else '編輯此階段分攤')

    def clear_billing(self):
        for table in self.payment_tables.values():
            table.setRowCount(0)
        for label in self.payment_summaries.values():
            label.setText('尚未開啟工程')
        for row in range(4):
            for col in range(10): self.allocation_table.takeItem(row,col)
        for label in self.payment_counts.values(): label.clear()
        self.billing_warning.clear(); self.billing_project=None
