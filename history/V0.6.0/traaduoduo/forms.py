"""Project forms, readable field explanations, dates and persistent locks."""
from copy import deepcopy
from PySide6.QtCore import Qt, QDate, QRectF
from PySide6.QtGui import QPainter, QColor, QPalette, QKeySequence
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QGroupBox,QLabel,
    QLineEdit,QComboBox,QPlainTextEdit,QCheckBox,QPushButton,QScrollArea,QDialog,QCalendarWidget,
    QDialogButtonBox,QStyle,QToolTip,QTableWidget,QApplication,QTextEdit)
from .details import STATES, warranty_end

def show_info(parent,title,text):
    dialog=QDialog(parent); dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.setObjectName('fieldInfoDialog'); dialog.setWindowTitle(title+'說明')
    layout=QVBoxLayout(dialog); body=QTextEdit(); body.setReadOnly(True)
    body.setPlainText(text); body.setStyleSheet('QTextEdit {font-size:39px; background:#ece9d8; padding:12px;}')
    body.setAccessibleName(title+'說明內容'); layout.addWidget(body)
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.close); layout.addWidget(buttons)
    screen=parent.screen().availableGeometry()
    dialog.resize(min(780,screen.width()-40),min(480,screen.height()-80)); dialog.show()

def info_button(parent,label,hint):
    if not hint or hint.strip()==label.strip():
        return None
    button=QPushButton('ⓘ',parent); button.setObjectName('fieldInfo'); button.setFixedSize(24,26)
    button.setAccessibleName(label+'說明'); button.setToolTip(hint)
    button.clicked.connect(lambda:show_info(button,label,hint))
    return button


class ProjectTable(QTableWidget):
    def copy_selection(self):
        cells=self.selectedItems()
        if not cells:
            return ''
        selected={(c.row(),c.column()):c.text() for c in cells}
        rows=sorted({r for r,c in selected})
        cols=sorted({c for r,c in selected})
        return '\n'.join('\t'.join(selected.get((r,c),'') for c in cols) for r in rows)

    def keyPressEvent(self,event):
        if event.matches(QKeySequence.StandardKey.Copy):
            QApplication.clipboard().setText(self.copy_selection())
            event.accept()
        else:
            super().keyPressEvent(event)


class BottomGroups(QWidget):
    def __init__(self,edit,database,about):
        super().__init__()
        self.groups=(edit,database,about)
        self.grid=QGridLayout(self)
        self.grid.setContentsMargins(0,0,0,0)
        self.grid.setSpacing(6)
        self.narrow=None
        self.reflow()

    def reflow(self):
        narrow=self.width()<1080
        if narrow==self.narrow:
            return
        self.narrow=narrow
        self.setFixedHeight(86 if narrow else 44)
        for widget in self.groups:
            self.grid.removeWidget(widget)
        if narrow:
            self.grid.addWidget(self.groups[0],0,0,1,2)
            self.grid.addWidget(self.groups[1],1,0)
            self.grid.addWidget(self.groups[2],1,1)
        else:
            for col,widget in enumerate(self.groups):
                self.grid.addWidget(widget,0,col)
        self.grid.setColumnStretch(0,0 if not narrow else 1)
        self.grid.setColumnStretch(1,1 if not narrow else 0)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.reflow()


class LockSwitch(QCheckBox):
    def __init__(self):
        super().__init__('已鎖定')
        self.setFixedSize(128,28)
        self.setAccessibleName('編輯鎖定開關')
        self.setToolTip('切換編輯狀態；鎖定前先儲存')

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#478b69' if self.isChecked() else '#abb5b0'))
        p.drawRoundedRect(QRectF(2,5,36,18),9,9)
        p.setBrush(QColor('white'))
        p.drawEllipse(QRectF(21 if self.isChecked() else 4,7,14,14))
        p.setPen(QColor('#111111' if self.isEnabled() else '#777777'))
        p.drawText(46,19,self.text())
        if self.hasFocus():
            p.setPen(QColor('#286aaa'))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(0,1,126,25),4,4)


class DateField(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setPlaceholderText('YYYY-MM-DD')
        palette=self.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText,QColor('#8E8E8E'))
        self.setPalette(palette)
        action=self.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView),QLineEdit.ActionPosition.TrailingPosition)
        action.setToolTip('選擇日期；未確認不填值')
        action.triggered.connect(self.choose_date)

    def choose_date(self):
        if self.isReadOnly() or not self.isEnabled():
            return
        d=QDialog(self)
        d.setWindowTitle('選擇日期')
        layout=QVBoxLayout(d)
        calendar=QCalendarWidget()
        day=QDate.fromString(self.text(),'yyyy-MM-dd')
        calendar.setSelectedDate(day if day.isValid() else QDate.currentDate())
        layout.addWidget(calendar)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        layout.addWidget(buttons)
        if d.exec()==QDialog.DialogCode.Accepted:
            self.setText(calendar.selectedDate().toString('yyyy-MM-dd'))
            self.textEdited.emit(self.text())
            self.editingFinished.emit()


class StageForms:
    def add_form_field(self,grid,row,key,label,page='basic',kind='text',hint='',readonly=False):
        if not hint or hint==label:
            hint=('西元 YYYY-MM-DD，可留空；點日期圖示選擇，取消不填入日期。' if kind=='date' else
                  '可輸入多行，顯示區預留三行高度。' if kind=='multi' else
                  '金額不可負數；可輸入千分位逗號，儲存使用十進位數值。' if key.endswith('_amount') else
                  '比例為 0 至 100 的百分比。' if key.endswith('_rate') else
                  '請輸入非負整數；保固年限上限 100 年。' if key in ('initial_days','acceptance_days','warranty_years') else
                  '契約工期 0 至 36600；0 表示尚未設定。' if key=='days' else label)
        fields=self.fields if page=='basic' else self.guarantee_fields
        if kind=='date':
            widget=DateField()
        elif kind=='multi':
            widget=QPlainTextEdit()
            widget.setFixedHeight(74)
        elif kind=='bool':
            widget=QCheckBox('手動修改')
        elif kind=='mode':
            widget=QComboBox()
            widget.addItem('工作天','工作日')
            widget.addItem('日曆天','日曆天')
        elif kind=='status':
            widget=QComboBox()
            widget.addItems(STATES)
        else:
            widget=QLineEdit()
        fields[key]=widget
        widget.setProperty('permanentReadOnly',readonly)
        widget.setAccessibleName(label)
        widget.setToolTip(hint or label)
        widget.setFixedWidth(360 if key in ('name','description','warranty_note') else 240)
        widget.setStyleSheet(widget.styleSheet()+';font-size:16pt;')
        callback=lambda: self.capture_form(page)
        if isinstance(widget,QLineEdit):
            widget.setMaxLength(300 if key=='name' else 120)
            widget.textEdited.connect(lambda: self.basic_edited())
            widget.editingFinished.connect(callback)
        elif isinstance(widget,QPlainTextEdit):
            widget.textChanged.connect(callback)
        elif isinstance(widget,QCheckBox):
            widget.toggled.connect(callback)
        else:
            widget.currentIndexChanged.connect(callback)
        title=QLabel(label); title.setStyleSheet('font-size:16pt;')
        grid.addWidget(title,row,0,Qt.AlignmentFlag.AlignTop if kind=='multi' else Qt.AlignmentFlag.AlignVCenter)
        wrap=QWidget()
        line=QHBoxLayout(wrap)
        line.setContentsMargins(0,0,0,0)
        line.setSpacing(4)
        line.addWidget(widget,1 if key=='name' or kind=='multi' else 0)
        info=info_button(wrap,label,hint)
        if info:
            line.addWidget(info)
        line.addStretch(0 if key=='name' or kind=='multi' else 1)
        grid.addWidget(wrap,row,1,Qt.AlignmentFlag.AlignTop)

    def build_stage_basic(self):
        outer,content=self.edit_page('basic')
        self.basic_tabs.addTab(outer,'契約執行')
        layout=QVBoxLayout(content)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        container=QWidget()
        columns=QHBoxLayout(container)
        self.basic_columns=columns
        columns.setContentsMargins(0,0,0,0)
        left,right=QGroupBox('工程基本資料'),QGroupBox('竣工、查驗與保固')
        for group in (left,right):
            group.setObjectName('basicGroup')
        container.setObjectName('basicBackground')
        container.setStyleSheet('QWidget#basicBackground {background:#ece9d8;}')
        columns.addWidget(left,1)
        columns.addWidget(right,1)
        a,b=QGridLayout(left),QGridLayout(right)
        for grid in (a,b):
            grid.setVerticalSpacing(4)
            grid.setColumnStretch(1,1)
            grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        entries=[('name','工程名稱','text'),('number','工程編號','text'),('contract','採購契約號','text'),('contractor','承攬商','text'),('award','決標日期','date'),('signed','簽約日期','date'),('start','開工日期','date'),('days','契約工期','text'),('description','工程說明','multi'),('status','執行狀態','status')]
        for row,(key,label,kind) in enumerate(entries):
            self.add_form_field(a,row,key,label,kind=kind,hint='執行狀態獨立保存，尚不連動大事記' if key=='status' else ('由唯一決標列連動；無決標列時保留歷史日期' if key=='award' else label))
        entries=[('mode','工進計算','mode',False),('workday_finish','預定竣工（工作天）','date',True),('calendar_finish','預定竣工（日曆天）','date',True),('actual_finish','實際竣工日','date',False),('initial_days','初驗期限日數','text',False),('initial_expected','預定初驗日','date',True),('initial_actual','實際初驗日','date',False),('acceptance_days','驗收期限日數','text',False),('acceptance_expected','預定驗收日','date',True),('acceptance_actual','實際驗收日','date',False),('warranty_years','保固年限（年）','text',False),('warranty_end','保固結束日','date',True),('settlement','決算日','date',False),('warranty_note','保固備註','multi',False)]
        for row,(key,label,kind,readonly) in enumerate(entries):
            hint={'workday_finish':'開工當日為第一天；排除假期、輸運及一般週末，補班例外；上午1全日不計、下午0.5半日不計。累計不足工期順延，不重複加算workdayA。','calendar_finish':'開工日期＋契約工期－1；不排除假期或晴雨。','initial_expected':'所選工進模式的預定竣工日＋初驗期限（日曆日）。','acceptance_expected':'預定初驗日＋驗收期限（日曆日）；實際日期不覆寫。','warranty_end':'實際驗收日加保固年限；閏日遇非閏年採 2/28'}.get(key,label)
            self.add_form_field(b,row,key,label,kind=kind,hint=hint,readonly=readonly)
        self.deadline_legacy_notice=QLabel(); self.deadline_legacy_notice.setWordWrap(True)
        b.addWidget(self.deadline_legacy_notice,len(entries),0,1,2)
        scroll.setWidget(container)
        layout.addWidget(scroll)

    def build_guarantees(self):
        self.guarantee_fields={}
        outer,content=self.edit_page('guarantees')
        self.basic_tabs.addTab(outer,'保證金')
        layout=QVBoxLayout(content)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        body=QWidget()
        sections=QVBoxLayout(body)
        groups=[('其他保證金',[('bid_amount','押標金','text'),('difference_amount','差額保證金','text')]),
            ('履約保證金',[('performance_amount','履約保證金','text'),('performance_manual','金額覆寫','bool'),('performance_rate','履保金比例（%）','text'),('performance_posted','繳交日期','date'),('performance_form','履保金形式','text')]),
            ('保固保證金',[('warranty_amount','保固保證金','text'),('warranty_manual','金額覆寫','bool'),('warranty_rate','保固金比例（%）','text'),('warranty_posted','繳交日期','date'),('warranty_form','保固金形式','text')]),
            ('退還與查驗',[('refund_amount','退還保固保證金','text'),('inspection','保固查驗日','date'),('refunded','退還日期','date')])]
        for title,entries in groups:
            group=QGroupBox(title)
            group.setObjectName('guaranteeGroup')
            line=QHBoxLayout(group)
            grids=[]
            counts=[0,0]
            for _ in range(2):
                part=QWidget()
                grid=QGridLayout(part)
                grid.setContentsMargins(0,0,0,0)
                grid.setAlignment(Qt.AlignmentFlag.AlignTop)
                grid.setColumnStretch(1,1)
                line.addWidget(part,0)
                grids.append(grid)
            for key,label,kind in entries:
                if key.endswith('_manual'):
                    continue
                col=1 if key.endswith('_rate') or key.endswith('_posted') or key in ('difference_amount','refunded') else 0
                self.add_form_field(grids[col],counts[col],key,label,page='guarantees',kind=kind,hint='金額以十進位保存；履約及保固額可自動連動，手動額獨立保留。' if key.endswith('_amount') else label)
                if key in ('performance_amount','warranty_amount'):
                    manual_key=key.replace('_amount','_manual')
                    check=QCheckBox(); check.setAccessibleName('手動覆寫'+label)
                    check.setToolTip('勾選以手動輸入；取消恢復自動金額，保留已存手動值。')
                    check.toggled.connect(lambda:self.capture_form('guarantees'))
                    self.guarantee_fields[manual_key]=check
                    grids[col].itemAtPosition(counts[col],1).widget().layout().insertWidget(1,check)
                counts[col]+=1
            line.addStretch(1)
            sections.addWidget(group)
        sections.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll)
        for key in ('performance_amount','warranty_amount'):
            self.guarantee_fields[key].setPlaceholderText('待工程費用連動')

    @staticmethod
    def field_value(widget):
        if isinstance(widget,QCheckBox):
            return widget.isChecked()
        if isinstance(widget,QComboBox):
            return widget.currentData() if widget.currentData() is not None else widget.currentText()
        if isinstance(widget,QPlainTextEdit):
            return widget.toPlainText()
        return widget.text()

    def capture_form(self,page):
        if self.loading or not self.session or page not in self.session.unlocked:
            return
        fields=self.fields if page=='basic' else self.guarantee_fields
        values=deepcopy(self.session.pages[page])
        values.update({key:self.field_value(widget) for key,widget in fields.items()})
        if page=='guarantees':
            for key in values:
                if key.endswith('_amount'):
                    values[key]=values[key].replace(',','').strip()
            for prefix in ('performance','warranty'):
                if not values[prefix+'_manual'] or not self.session.pages[page][prefix+'_manual']:
                    values[prefix+'_amount']=self.session.pages[page][prefix+'_amount']
        if page=='basic':
            try:
                values['warranty_end']=warranty_end(values['acceptance_actual'],values['warranty_years'])
            except (ValueError,OverflowError):
                values['warranty_end']=''
            self.fields['warranty_end'].setText(values['warranty_end'])
        self.session.change(page,values)
        self.changed()

    def populate_stage_forms(self):
        self.loading=True
        for page,fields in [('basic',self.fields),('guarantees',self.guarantee_fields)]:
            for key,widget in fields.items():
                value=self.session.pages[page][key]
                if isinstance(widget,QCheckBox):
                    widget.setChecked(value)
                elif isinstance(widget,QComboBox):
                    i=widget.findData(value)
                    widget.setCurrentIndex(i if i>=0 else widget.findText(value))
                elif isinstance(widget,QPlainTextEdit):
                    widget.setPlainText(value)
                else:
                    widget.setText(value)
        self.loading=False
        self.refresh_deadline_notice()

    def refresh_deadline_notice(self):
        if not self.session: return
        basic=self.session.pages['basic']; differences=[]
        labels=dict(workday_finish='工作天竣工',calendar_finish='日曆天竣工',initial_expected='初驗',acceptance_expected='驗收')
        for key,old in basic.get('historical_deadlines',{}).items():
            if old and old!=basic.get(key): differences.append(labels.get(key,key)+'舊值 '+old)
        if basic.get('finish'): differences.append('舊預定竣工 '+basic['finish'])
        self.deadline_legacy_notice.setText('歷史預定日期（僅保留核對，不參與重算）：'+'；'.join(differences) if differences else '')
        self.deadline_legacy_notice.setVisible(bool(differences))

    def clear_stage_forms(self):
        self.loading=True
        for fields in (self.fields,self.guarantee_fields):
            for widget in fields.values():
                if isinstance(widget,QCheckBox):
                    widget.setChecked(False)
                elif isinstance(widget,QComboBox):
                    widget.setCurrentIndex(0)
                else:
                    widget.clear()
        self.loading=False

    def apply_form_locks(self,ready):
        for page,fields in [('basic',self.fields),('guarantees',self.guarantee_fields)]:
            editable=bool(ready and page in self.session.unlocked)
            for key,widget in fields.items():
                allowed=editable and not widget.property('permanentReadOnly')
                if page=='guarantees' and key in ('performance_amount','warranty_amount'):
                    allowed=allowed and self.session.pages[page][key.replace('_amount','_manual')]
                if isinstance(widget,(QLineEdit,QPlainTextEdit)):
                    widget.setReadOnly(not allowed)
                    if isinstance(widget,DateField):
                        widget.ensurePolished()
                        palette=widget.palette()
                        palette.setColor(QPalette.ColorRole.PlaceholderText,QColor('#8E8E8E'))
                        widget.setPalette(palette)
                else:
                    widget.setEnabled(allowed)
                if page=='guarantees' and key in ('performance_amount','warranty_amount') and self.session:
                    value=self.session.pages[page][key]
                    if not self.session.pages[page][key.replace('_amount','_manual')]:
                        widget.setText(self.session.pages[page].get(key.replace('_amount','_auto_amount'),''))
                        widget.setToolTip('由契約基數及比例連動。已保存手動值：'+(value or '無'))
                    elif not widget.text() and value:
                        widget.setText(value)
