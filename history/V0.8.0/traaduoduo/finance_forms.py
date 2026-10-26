"""Cost and bid forms; all changes pass through the same locked EditSession."""
from copy import deepcopy
import uuid
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont,QFontMetrics
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QGroupBox,QLabel,QLineEdit,
    QCheckBox,QPushButton,QScrollArea,QComboBox,QTableWidgetItem,QAbstractItemView,QHeaderView,
    QDialog,QDialogButtonBox,QMessageBox,QInputDialog,QBoxLayout,QSpinBox)
from .forms import DateField,ProjectTable,info_button
from .finance import FIELDS,COPY_KEYS,DERIVED_COSTS,management_fee,percent,format_money,amount
from .presentation import MoneyField,money,compact_field


class FinanceForms:
    def build_costs(self):
        outer,content=self.edit_page('costs')
        self.basic_tabs.addTab(outer,'工程費用')
        layout=QVBoxLayout(content)
        scroll=QScrollArea(); scroll.setWidgetResizable(True)
        body=QWidget(); boxes=QVBoxLayout(body)
        settings=QHBoxLayout()
        self.guarantee_base_combo=QComboBox()
        self.guarantee_base_combo.addItem('保證金基數：發包工程費金額','work')
        self.guarantee_base_combo.addItem('保證金基數：契約金額（含稅）','award_total')
        self.copy_source_combo=QComboBox()
        self.copy_source_combo.addItem('自辦工費 ▶：預算自辦工費','own_labor')
        self.copy_source_combo.addItem('自辦工費 ▶：預算工程管理費','management_amount')
        for combo in (self.guarantee_base_combo,self.copy_source_combo):
            combo.currentIndexChanged.connect(self.capture_costs)
            combo.hide()
        columns=QHBoxLayout(); self.cost_columns=columns; boxes.addLayout(columns)
        columns.setDirection(QBoxLayout.Direction.TopToBottom if self.width()<1320 else QBoxLayout.Direction.LeftToRight)
        self.cost_fields={}; self.fee_labels={}; self.fee_manual={}; self.cost_buttons=[]
        self.extension_tables={}; self.extension_containers={}; self.extension_toggles={}
        self.non_labor_labels={}
        for kind,title,color in [('budget','預算金額','#EFFFD7'),('contract','契約金額','#FFFFDF')]:
            group=QGroupBox(title)
            group.setObjectName('costGroup')
            group.setStyleSheet('QGroupBox#costGroup {background:'+color+';font-size:26px;margin-top:28px;padding-top:22px;}')
            columns.addWidget(group,1)
            grid=QGridLayout(group); grid.setColumnStretch(4,1); grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(round(2*group.logicalDpiY()/72))
            label_font=QFont(self.font()); label_font.setPixelSize(26)
            metrics=QFontMetrics(label_font)
            grid.setColumnMinimumWidth(0,metrics.horizontalAdvance('未完工程進項稅額')+metrics.horizontalAdvance('中')*3)
            self.cost_fields[kind]={}
            ordered=list(FIELDS)
            base=next(item for item in ordered if item[0]=='base_price'); ordered.remove(base)
            if kind=='contract':
                ordered.insert(next(i for i,item in enumerate(ordered) if item[0]=='award_total')+1,base)
            row=0
            for key,label in ordered:
                if key=='management_amount':
                    section=QLabel('包工費以外')
                    section.setStyleSheet('font-size:16pt;')
                    subtotal=QLineEdit();subtotal.setReadOnly(True);subtotal.setFixedWidth(220)
                    subtotal.setAccessibleName(title+'包工費以外');subtotal.setStyleSheet('font-size:16pt;')
                    subtotal.setAlignment(Qt.AlignmentFlag.AlignRight);compact_field(subtotal)
                    self.non_labor_labels[kind]=subtotal
                    self.cost_fields[kind]['non_labor']=subtotal
                    grid.addWidget(section,row,0);grid.addWidget(subtotal,row,1);grid.addWidget(QLabel('元'),row,2);row+=1
                if key=='base_price' and kind=='budget':
                    continue
                labels={'total':('總工程預算','總工程費用'),'award_total':('發包工程費預算','契約金額'),
                        'work':('發包工程','發包工程費金額'),'work_tax':('進項稅額','營業稅')}
                label=labels.get(key,(label,label))[0 if kind=='budget' else 1]
                field=MoneyField(2); field.setFixedWidth(220)
                field.setAlignment(Qt.AlignmentFlag.AlignRight); field.setStyleSheet('font-size:16pt;')
                if key=='management_amount':
                    field=MoneyField(0 if kind=='budget' else 2);field.setFixedWidth(220);field.setAlignment(Qt.AlignmentFlag.AlignRight);field.setStyleSheet('font-size:16pt;')
                compact_field(field)
                field.setAccessibleName(title+label)
                field.setToolTip('金額以十進位保存；可輸入千分位逗號。未填表示尚未提供，不自動拆算稅額。')
                field.textEdited.connect(self.basic_edited)
                field.editingFinished.connect(self.capture_costs)
                self.cost_fields[kind][key]=field
                title_label=QLabel(label); title_label.setStyleSheet('font-size:16pt;')
                grid.addWidget(title_label,row,0); grid.addWidget(field,row,1)
                grid.addWidget(QLabel('元（含稅）' if key in ('total','award_total') else '元'),row,2)
                if key in DERIVED_COSTS or key=='management_amount' or (kind=='budget' and key=='award_total'):
                    field.setReadOnly(True)
                    hint={'total':'未完工程＋未完工程進項稅額。','unfinished':'發包工程費預算／契約金額＋工程管理費＋包工費以外。','other_fees':'空污費＋擴充項目。','management_amount':'由下方調整後管理費連動。','award_total':'發包工程＋進項稅額；來源未填則留空。'}[key]
                    field.setToolTip(hint)
                    grid.addWidget(info_button(group,label,hint),row,3)
                if kind=='contract' and key in COPY_KEYS:
                    button=QPushButton('▶'); button.setFixedSize(26,25)
                    button.setStyleSheet('padding:0px;font-size:12px;')
                    button.setToolTip('將預算對應欄位複製一次；自辦工費複製預算自辦工費')
                    button.clicked.connect(lambda checked=False,k=key:self.copy_cost(k))
                    grid.addWidget(button,row,3); self.cost_buttons.append(button)
                if key=='pollution':
                    button=QPushButton('＋'); button.setFixedSize(30,30)
                    button.setAccessibleName(title+'新增其他費用')
                    button.clicked.connect(self.add_cost_extension)
                    grid.addWidget(button,row,4,Qt.AlignmentFlag.AlignLeft); self.cost_buttons.append(button)
                row+=1
            extension=QWidget(); ext_layout=QVBoxLayout(extension); ext_layout.setContentsMargins(0,0,0,0)
            toggle=QPushButton('隱藏擴充欄位'); self.extension_toggles[kind]=toggle; toggle.hide()
            toggle.clicked.connect(self.toggle_extensions)
            table=ProjectTable(0,4 if kind=='contract' else 3)
            table.setStyleSheet('font-size:16pt;')
            table.setHorizontalHeaderLabels(['項目名稱',title+'（元）']+(['複製'] if kind=='contract' else [])+['刪除'])
            table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
            table.setColumnWidth(1,156)
            if kind=='contract': table.setColumnWidth(2,52)
            table.itemChanged.connect(lambda *_,k=kind:self.capture_extensions(k))
            self.extension_tables[kind]=table; self.extension_containers[kind]=extension
            ext_layout.addWidget(table); grid.addWidget(extension,row,0,1,5)
            grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.extension_table=self.extension_tables['budget']
        self.ratio_label=QLabel(); self.ratio_label.setObjectName('costRatio')
        self.ratio_label.setWordWrap(True); boxes.addWidget(self.ratio_label)
        self.cost_legacy_notice=QLabel(); self.cost_legacy_notice.setWordWrap(True); boxes.addWidget(self.cost_legacy_notice)
        fees=QHBoxLayout(); self.management_columns=fees; boxes.addLayout(fees)
        fees.setDirection(QBoxLayout.Direction.TopToBottom if self.width()<1320 else QBoxLayout.Direction.LeftToRight)
        for kind,title in [('budget','工程管理費（預算）'),('contract','工程管理費（契約）')]:
            group=QGroupBox(title); fees.addWidget(group,1)
            group.setObjectName('managementFeeGroup')
            group.setStyleSheet('QGroupBox#managementFeeGroup {font-size:26px;margin-top:28px;padding-top:22px;} QLabel,QLineEdit,QCheckBox {font-size:16pt;}')
            grid=QGridLayout(group); labels=[];grid.setVerticalSpacing(round(2*group.logicalDpiY()/72))
            fee_font=QFont(self.font());fee_font.setPointSize(16);fee_metrics=QFontMetrics(fee_font)
            grid.setColumnMinimumWidth(0,fee_metrics.horizontalAdvance('500萬～2500萬 1.5%')+fee_metrics.horizontalAdvance('中')*3)
            for row,label in enumerate(['計算基數','500萬以下 3%','500萬～2500萬 1.5%','2500萬～1億 1%','1億～5億 0.7%','超過5億 0.5%','原管理費合計']):
                value=QLabel('—'); value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                value.setMinimumWidth(170); value.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(QLabel(label),row,0); grid.addWidget(value,row,1); labels.append(value)
            self.fee_labels[kind]=labels
            check=QCheckBox('手動調整')
            check.setToolTip('取消手動調整仍保留已保存值')
            check.toggled.connect(self.capture_costs); self.fee_manual[kind]=check
            field=MoneyField(2); field.setAlignment(Qt.AlignmentFlag.AlignRight);field.setStyleSheet('font-size:16pt;');compact_field(field)
            field.textEdited.connect(self.basic_edited); field.editingFinished.connect(self.capture_costs)
            self.cost_fields[kind]['management_adjustment']=field
            grid.addWidget(check,7,0,1,2); grid.addWidget(QLabel('調整後合計（元）'),8,0); grid.addWidget(field,8,1)
        boxes.addWidget(QLabel('管理費基數＝包工費＋自辦工費＋自購材料費＋路備材料費＋路購材料費；包工費未填不計。預設截千元，保留人工調整。'))
        scroll.setWidget(body); layout.addWidget(scroll)

    def toggle_extensions(self):
        if not self.session:
            return
        self.extension_ui_visible=not getattr(self,'extension_ui_visible',self.session.pages['costs'].get('extensions_visible',True))
        if 'costs' in self.session.unlocked:
            value=deepcopy(self.session.pages['costs']); value['extensions_visible']=self.extension_ui_visible
            self.session.change('costs',value); self.changed()
        self.populate_extensions()

    def capture_costs(self,*_):
        if self.loading or not self.session or 'costs' not in self.session.unlocked:
            return
        value=deepcopy(self.session.pages['costs'])
        for kind in ('budget','contract'):
            previous=value[kind].copy()
            for key,field in self.cost_fields[kind].items():
                if key not in (*DERIVED_COSTS,'management_amount','management_adjustment') and not (kind=='budget' and key=='award_total'):
                    value[kind][key]=field.value() if isinstance(field,MoneyField) else field.text().replace(',','').strip()
            manual=self.fee_manual[kind].isChecked()
            adjustment=self.cost_fields[kind]['management_adjustment'].value()
            if not manual:
                adjustment=previous['management_adjustment']
            elif not previous['management_manual'] and previous['management_adjustment']!='':
                adjustment=previous['management_adjustment']
                self.cost_fields[kind]['management_adjustment'].setText(adjustment)
            value[kind]['management_manual']=manual
            value[kind]['management_adjustment']=adjustment
        value['guarantee_base']=self.guarantee_base_combo.currentData()
        value['own_labor_copy']=self.copy_source_combo.currentData()
        self.session.change('costs',value); self.changed()

    def copy_cost(self,key):
        if not self.session or 'costs' not in self.session.unlocked:
            return
        self.capture_costs()
        source='own_labor' if key=='own_labor' else key
        value=self.session.pages['costs']['budget'][source]
        field=self.cost_fields['contract'][key]
        if field.text() and field.text().replace(',','')!=value:
            if QMessageBox.question(self,'確認覆寫','以預算來源覆寫此契約欄位？')!=QMessageBox.StandardButton.Yes:
                return
        field.setText(value); self.capture_costs()

    def add_cost_extension(self):
        if not self.session or 'costs' not in self.session.unlocked:
            return
        label,ok=QInputDialog.getText(self,'新增費用項目','項目名稱')
        if ok and label.strip():
            value=deepcopy(self.session.pages['costs'])
            value['extensions'].append(dict(id=uuid.uuid4().hex,label=label.strip(),budget='',contract=''))
            value['extensions_visible']=True; self.extension_ui_visible=True
            self.session.change('costs',value); self.populate_extensions(); self.changed()

    def populate_extensions(self):
        before=self.loading; self.loading=True
        items=self.session.pages['costs']['extensions'] if self.session else []
        visible=True
        for kind,table in self.extension_tables.items():
            table.setRowCount(len(items)); table.clearContents()
            for row,item in enumerate(items):
                table.setRowHeight(row,table.fontMetrics().height()+round(3*table.logicalDpiY()/72))
                for col,key in enumerate(('label',kind)):
                    try: text=item[key] if col==0 else format_money(item[key])
                    except (ValueError,ArithmeticError): text=item[key]
                    cell=QTableWidgetItem(text); cell.setData(Qt.ItemDataRole.UserRole,item['id'])
                    if col==1: cell.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
                    table.setItem(row,col,cell)
                if kind=='contract':
                    button=QPushButton('▶'); button.setAccessibleName('複製預算'+item['label'])
                    button.clicked.connect(lambda checked=False,r=row:self.copy_extension(r))
                    button.setEnabled(bool(self.session and 'costs' in self.session.unlocked))
                    table.setCellWidget(row,2,button)
                remove=QPushButton('-'); remove.setAccessibleName('刪除'+item['label'])
                remove.setEnabled(bool(self.session and 'costs' in self.session.unlocked))
                remove.clicked.connect(lambda checked=False,rid=item['id']:self.remove_extension(rid))
                table.setCellWidget(row,table.columnCount()-1,remove)
            table.setFixedHeight(min(6,len(items))*(table.fontMetrics().height()+round(3*table.logicalDpiY()/72))+table.horizontalHeader().height()+table.horizontalScrollBar().sizeHint().height()+8)
            self.extension_containers[kind].setVisible(visible and bool(items))
            self.extension_toggles[kind].setText(('隱藏' if visible else '顯示')+'擴充欄位（'+str(len(items))+'）')
        self.loading=before

    def remove_extension(self,rid):
        if not self.session or 'costs' not in self.session.unlocked: return
        item=next((r for r in self.session.pages['costs']['extensions'] if r['id']==rid),None)
        if not item: return
        if QMessageBox.question(self,'刪除擴充費用',f"刪除「{item['label']}」？\n預算：{item['budget']}\n契約：{item['contract']}\n兩側同步移除，可使用回復動作復原。")!=QMessageBox.StandardButton.Yes: return
        value=deepcopy(self.session.pages['costs']); value['extensions']=[r for r in value['extensions'] if r['id']!=rid]
        self.session.change('costs',value); self.populate_extensions(); self.changed()

    def capture_extensions(self,kind='budget',*_):
        if self.loading or not self.session or 'costs' not in self.session.unlocked:
            return
        value=deepcopy(self.session.pages['costs'])
        if kind not in self.extension_tables: kind='budget'
        for row,item in enumerate(value['extensions']):
            for col,key in enumerate(('label',kind)):
                cell=self.extension_tables[kind].item(row,col)
                if cell:
                    item[key]=cell.text().replace(',','').strip() if col else cell.text()
        self.session.change('costs',value)
        # Keep the active delegate/editor alive while synchronizing shared names.
        self.loading=True
        for other,table in self.extension_tables.items():
            if other!=kind:
                for row,item in enumerate(value['extensions']):
                    if table.item(row,0): table.item(row,0).setText(item['label'])
        self.loading=False
        self.changed()

    def copy_extension(self,row=None):
        row=self.extension_table.currentRow() if row is None or isinstance(row,bool) else row
        if not self.session or 'costs' not in self.session.unlocked or not 0<=row<len(self.session.pages['costs']['extensions']):
            return
        value=deepcopy(self.session.pages['costs']); item=value['extensions'][row]
        try:
            if item['budget']!='': amount(item['budget'])
        except (ValueError,ArithmeticError):
            QMessageBox.warning(self,'費用尚未完成','請先修正預算擴充金額，再複製。'); return
        if item['contract'] and item['contract']!=item['budget'] and QMessageBox.question(self,'確認覆寫','以預算金額覆寫此契約擴充項目？')!=QMessageBox.StandardButton.Yes:
            return
        item['contract']=item['budget']; self.session.change('costs',value); self.populate_extensions(); self.changed()

    def populate_finance(self):
        self.loading=True
        self.extension_ui_visible=self.session.pages['costs'].get('extensions_visible',True)
        for kind in ('budget','contract'):
            for key,field in self.cost_fields[kind].items():
                field.setText(format_money(self.session.pages['costs'][kind][key]))
            self.fee_manual[kind].setChecked(self.session.pages['costs'][kind]['management_manual'])
        self.guarantee_base_combo.setCurrentIndex(self.guarantee_base_combo.findData(self.session.pages['costs']['guarantee_base']))
        self.copy_source_combo.setCurrentIndex(self.copy_source_combo.findData(self.session.pages['costs']['own_labor_copy']))
        self.populate_extensions(); self.populate_bids(); self.loading=False
        self.refresh_finance()

    def refresh_finance(self):
        if not self.session:
            return
        value=self.session.pages['costs']
        try:
            for kind in ('budget','contract'):
                result=management_fee(value[kind],kind)
                numbers=[result['source'],*result['tiers'],result['total']] if result else [None]*7
                for label,number in zip(self.fee_labels[kind],numbers):
                    label.setText('—' if number is None else money(number))
                self.cost_fields[kind]['management_amount'].setText(format_money(value[kind]['management_amount']))
                for key in DERIVED_COSTS-{'non_labor'}:
                    self.cost_fields[kind][key].setText(format_money(value[kind][key]))
                self.non_labor_labels[kind].setText(format_money(value[kind]['non_labor']))
                if not value[kind]['management_manual']:
                    self.cost_fields[kind]['management_adjustment'].setText(format_money(str(result['default'])) if result else '')
            self.ratio_label.setText('決標／預算 '+percent(value['contract']['award_total'],value['budget']['award_total'])+'　決標／底價 '+percent(value['contract']['award_total'],value['contract']['base_price'])+'　底價／預算 '+percent(value['contract']['base_price'],value['budget']['award_total']))
        except (ValueError,ArithmeticError):
            self.ratio_label.setText('請修正金額後再計算')
        changes=[]
        for kind in ('budget','contract'):
            for key,old in value[kind].get('historical_totals',{}).items():
                if old and old!=value[kind].get(key): changes.append(('預算' if kind=='budget' else '契約')+('總額' if key=='total' else '未完工程')+' 舊值 '+format_money(old)+'／連動 '+(format_money(value[kind].get(key,'')) or '待填'))
        old_settings=value.get('source_settings_legacy',{})
        if old_settings.get('guarantee_base','award_total')!='award_total':
            changes.append('歷史保證金仍採已存發包工程費基數；原設定保留，未自動覆寫')
        if old_settings.get('own_labor_copy','own_labor')!='own_labor':
            changes.append('自辦工費▶依本次確認改複製預算自辦工費；舊來源設定保留供核對')
        self.cost_legacy_notice.setText('歷史值核對：'+'；'.join(changes) if changes else '')
        self.cost_legacy_notice.setVisible(bool(changes))
        self.fields['award'].setText(self.session.pages['basic']['award'])

    def clear_finance(self):
        self.loading=True
        for kind in ('budget','contract'):
            for field in self.cost_fields[kind].values():
                field.clear()
            self.fee_manual[kind].setChecked(False)
            for label in self.fee_labels[kind]:
                label.setText('—')
        for table in self.extension_tables.values(): table.setRowCount(0)
        self.bid_table.setRowCount(0)
        self.ratio_label.setText('尚未開啟工程')
        self.loading=False

    def apply_finance_locks(self,ready):
        editable=bool(ready and 'costs' in self.session.unlocked)
        for kind,fields in self.cost_fields.items():
            for key,field in fields.items():
                field.setReadOnly(not editable or key in DERIVED_COSTS or key=='management_amount' or (kind=='budget' and key=='award_total') or (key=='management_adjustment' and not self.fee_manual[kind].isChecked()))
            self.fee_manual[kind].setEnabled(editable)
        for widget in [self.guarantee_base_combo,self.copy_source_combo,*self.cost_buttons]:
            widget.setEnabled(editable)
        for table in self.extension_tables.values():
            table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers if editable else QAbstractItemView.EditTrigger.NoEditTriggers)
            for button in table.findChildren(QPushButton): button.setEnabled(editable)
        for button in self.bid_buttons:
            button.setEnabled(bool(ready and 'bids' in self.session.unlocked))
        if self.session and self.session.pages['basic'].get('award_source','').startswith('bid:'):
            self.fields['award'].setReadOnly(True)
            self.fields['award'].setToolTip('由唯一決標列公告日連動；取消決標後恢復歷史日期')

    def build_bids(self):
        outer,content=self.edit_page('bids'); self.basic_tabs.addTab(outer,'招標情形')
        layout=QVBoxLayout(content); actions=QHBoxLayout(); self.bid_buttons=[]
        for label,handler in [('新增',lambda:self.edit_bid()),('編輯',lambda:self.edit_bid(self.selected_bid()) if self.selected_bid() else None),('設為／取消決標',self.toggle_bid_award),('移除',self.remove_bid)]:
            button=QPushButton(label); button.clicked.connect(handler); actions.addWidget(button); self.bid_buttons.append(button)
        actions.addStretch(); layout.addLayout(actions)
        self.bid_table=ProjectTable(0,7)
        self.bid_table.setWordWrap(False)
        self.bid_table.setHorizontalHeaderLabels(['決標','次數','公開閱覽','公開上網','開標日','評選委員會','決標公告日'])
        self.bid_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col,width in enumerate([65,65,300,300,150,150,150]):self.bid_table.setColumnWidth(col,width)
        self.bid_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.bid_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.bid_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bid_table.setSortingEnabled(True)
        self.bid_table.cellDoubleClicked.connect(lambda *_:self.edit_bid(self.selected_bid()))
        layout.addWidget(self.bid_table)
        layout.addWidget(QLabel('同工程僅一筆決標；公告日回饋基本資料。取消或刪除決標列會恢復先前保留的歷史日期。'))

    def populate_bids(self):
        self.bid_table.setSortingEnabled(False)
        rows=self.session.pages['bids']
        self.bid_table.setRowCount(len(rows))
        for r,row in enumerate(sorted(rows,key=lambda x:x['number'])):
            values=['＊' if row['awarded'] else '',row['number'],row['review_start']+' ～ '+row['review_end'],row['online_start']+' ～ '+row['online_end'],row['opening'],row['committee'],row['award_date']]
            self.bid_table.setRowHeight(r,self.bid_table.fontMetrics().height()+12)
            for c,text in enumerate(values):
                item=QTableWidgetItem(str(text)); item.setData(Qt.ItemDataRole.UserRole,row['id']); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(str(text)+('\n原始日期註記：'+'；'.join(row['legacy_date_notes'].values()) if row.get('legacy_date_notes') else ''))
                if c==1:
                    item.setData(Qt.ItemDataRole.DisplayRole,row['number'])
                self.bid_table.setItem(r,c,item)
        self.bid_table.setSortingEnabled(True)

    def selected_bid(self):
        index=self.bid_table.currentRow()
        if index<0 or not self.session:
            return None
        rid=self.bid_table.item(index,0).data(Qt.ItemDataRole.UserRole)
        return next((r for r in self.session.pages['bids'] if r['id']==rid),None)

    def edit_bid(self,row=None):
        if not self.session or 'bids' not in self.session.unlocked:
            return
        existing=deepcopy(row) if row else dict(id=uuid.uuid4().hex,number=max((r['number'] for r in self.session.pages['bids']),default=0)+1,awarded=False,review_start='',review_end='',online_start='',online_end='',opening='',committee='',award_date='')
        dialog=QDialog(self); dialog.setWindowTitle('招標資料'); box=QVBoxLayout(dialog)
        box.addWidget(QLabel('次數'));bid_number=QSpinBox();bid_number.setObjectName('bid-number');bid_number.setRange(1,999999999);bid_number.setValue(existing['number']);box.addWidget(bid_number)
        fields={}; grid=QGridLayout(); box.addLayout(grid)
        for index,(key,label) in enumerate([('review_start','公開閱覽起日'),('review_end','公開閱覽迄日'),('online_start','公開上網起日'),('online_end','公開上網迄日'),('opening','開標日'),('committee','評選委員會'),('award_date','決標公告日')]):
            field=DateField(); field.setText(existing[key]); fields[key]=field
            grid.addWidget(QLabel(label),index,0); grid.addWidget(field,index,1)
        awarded=QCheckBox('本次決標（同工程唯一）'); awarded.setChecked(existing['awarded']); box.addWidget(awarded)
        if existing.get('legacy_date_notes'):
            note=QLabel('原始日期註記（保留）：'+'；'.join(existing['legacy_date_notes'].values()))
            note.setWordWrap(True); box.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        box.addWidget(buttons); buttons.rejected.connect(dialog.reject)
        def submit():
            candidate=dict(existing,**{k:f.text() for k,f in fields.items()},number=bid_number.value(),awarded=awarded.isChecked())
            if self.submit_bid(candidate):
                dialog.accept()
        buttons.accepted.connect(submit)
        dialog.resize(420,440)
        dialog.exec()

    def submit_bid(self,candidate):
        from .finance import validate_bids
        if not self.session or 'bids' not in self.session.unlocked:
            return False
        rows=deepcopy(self.session.pages['bids'])
        others=[r for r in rows if r['id']!=candidate['id']]
        if candidate['awarded'] and any(r['awarded'] for r in others):
            if QMessageBox.question(self,'變更唯一決標','改由本次決標，並取消原決標列？')!=QMessageBox.StandardButton.Yes:
                return False
            for r in others:
                r['awarded']=False
        updated=others+[deepcopy(candidate)]
        try:
            validate_bids(updated)
        except (ValueError,KeyError) as exc:
            QMessageBox.warning(self,'招標資料未完成',str(exc)); return False
        self.session.change('bids',updated); self.populate_bids(); self.changed(); return True

    def toggle_bid_award(self):
        row=self.selected_bid()
        if row:
            self.submit_bid(dict(row,awarded=not row['awarded']))

    def remove_bid(self):
        row=self.selected_bid()
        if not row or 'bids' not in self.session.unlocked:
            return
        if QMessageBox.question(self,'移除招標紀錄','確定移除此筆？若為決標列，會恢復歷史決標日。')==QMessageBox.StandardButton.Yes:
            self.session.change('bids',[r for r in self.session.pages['bids'] if r['id']!=row['id']]); self.populate_bids(); self.changed()
