"""Deadline editor and date-derived, non-mutating status views."""
from copy import deepcopy
from datetime import date
import uuid
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,QDialog,QDialogButtonBox,QFormLayout,QLineEdit,QPlainTextEdit,QSpinBox,QTableWidgetItem,QMessageBox,QAbstractItemView
from .forms import ProjectTable,DateField
from .tracking import TRACKING_COLUMNS,deadline_status,upcoming,validate_tracking

class IssuedField(QWidget):
    def __init__(self,value):
        super().__init__();layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        parts=value.split(' ',1);self.day=DateField();self.day.setText(parts[0]);self.time=QLineEdit(parts[1] if len(parts)>1 else '');self.time.setPlaceholderText('HH:MM（選填）');layout.addWidget(self.day);layout.addWidget(self.time)
    def text(self):return self.day.text().strip()+(' '+self.time.text().strip() if self.time.text().strip() else '')

class TrackingForms:
    def build_tracking(self):
        outer,body=self.edit_page('deadline_tracking');self.diary_tabs.addTab(outer,'期限追蹤');layout=QVBoxLayout(body)
        top=QWidget();top.setObjectName('deadline-upcoming');top.setStyleSheet('QWidget#deadline-upcoming {background:#FFCBB3;}');box=QVBoxLayout(top);box.addWidget(QLabel('5 天內到期的未完成工作（含今天）'))
        self.upcoming_table=ProjectTable(0,3);self.upcoming_table.setMinimumHeight(120);self.upcoming_table.setHorizontalHeaderLabels(['限期日','限期工作','剩餘天數']);self.upcoming_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);box.addWidget(self.upcoming_table)
        self.upcoming_empty=QLabel('未來 5 天內無待辦到期工作');box.addWidget(self.upcoming_empty);layout.addWidget(top,1)
        tools=QHBoxLayout();layout.addLayout(tools)
        for text,fn in [('新增期限',lambda:self.edit_tracking(True)),('編輯期限',self.edit_tracking),('移除期限',self.remove_tracking)]:self.extra_button('deadline_tracking',tools,text,fn)
        self.tracking_filter=QComboBox();self.tracking_filter.addItems(['全部','未完成','已完成']);tools.addWidget(self.tracking_filter);tools.addStretch()
        self.tracking_table=ProjectTable(0,len(TRACKING_COLUMNS));self.tracking_table.setMinimumHeight(120);self.tracking_table.setHorizontalHeaderLabels([v for k,v in TRACKING_COLUMNS]);self.tracking_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.tracking_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.tracking_table.setWordWrap(True);layout.addWidget(self.tracking_table,2)
        for i,width in enumerate([75,110,175,180,140,420,140,140]):self.tracking_table.setColumnWidth(i,width)
        self.upcoming_table.setColumnWidth(0,140);self.upcoming_table.setColumnWidth(1,500)
        self.tracking_filter.currentIndexChanged.connect(self.refresh_tracking)
        self.upcoming_table.cellClicked.connect(self.locate_tracking)
        self.tracking_table.cellDoubleClicked.connect(lambda *_:self.edit_tracking())
        self._tracking_day=None;self.deadline_timer=QTimer(self);self.deadline_timer.setInterval(30000);self.deadline_timer.timeout.connect(self.refresh_tracking_date);self.deadline_timer.start()
        self._tracking_activation=lambda *_:self.refresh_tracking_date()
        QApplication.instance().applicationStateChanged.connect(self._tracking_activation)
        self.diary_tabs.setCurrentIndex(min(1,max(0,int(self.settings.value('diary/subpage',0)))))
        self.diary_tabs.currentChanged.connect(lambda i:self.settings.setValue('diary/subpage',i))

    def refresh_tracking_date(self):
        if self._tracking_day!=date.today():self.refresh_tracking()

    def refresh_tracking(self,*_,today=None):
        today=today or date.today();self._tracking_day=today
        rows=self.session.pages['deadline_tracking'] if self.session else []
        selected=self.tracking_table.currentItem();selected=selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self.tracking_table.setRowCount(0)
        for row in sorted(rows,key=lambda r:r['number']):
            if self.tracking_filter.currentIndex()==1 and row['completed_date']:continue
            if self.tracking_filter.currentIndex()==2 and not row['completed_date']:continue
            status=deadline_status(row,today);i=self.tracking_table.rowCount();self.tracking_table.insertRow(i)
            for j,(key,title) in enumerate(TRACKING_COLUMNS):
                value=status['text'] if key=='alert' else status['overdue_date'] if key=='overdue_date' else row[key]
                item=QTableWidgetItem(str(value));item.setData(Qt.ItemDataRole.UserRole,row['id'])
                if key!='work':item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if key=='alert':
                    item.setBackground(QColor(status['color']));item.setForeground(QColor(status['foreground']));font=item.font();font.setBold(status['bold']);item.setFont(font)
                    if status['state']=='completed':item.setToolTip('完成時逾期：'+str(status['days'])+' 天')
                self.tracking_table.setItem(i,j,item)
            if selected==row['id']:self.tracking_table.setCurrentCell(i,0)
        self.tracking_table.resizeRowsToContents();due=upcoming(rows,today);self.upcoming_table.setRowCount(len(due))
        self.upcoming_empty.setVisible(not due)
        for i,row in enumerate(due):
            for j,value in enumerate([row['due_date'],row['work'],str(deadline_status(row,today)['remaining'])]):
                item=QTableWidgetItem(value);item.setData(Qt.ItemDataRole.UserRole,row['id']);self.upcoming_table.setItem(i,j,item)
        self.upcoming_table.resizeRowsToContents()

    def locate_tracking(self,row,column=0):
        rid=self.upcoming_table.item(row,0).data(Qt.ItemDataRole.UserRole);self.tracking_filter.setCurrentIndex(0)
        for i in range(self.tracking_table.rowCount()):
            if self.tracking_table.item(i,0).data(Qt.ItemDataRole.UserRole)==rid:self.tracking_table.setCurrentCell(i,0);self.tracking_table.scrollToItem(self.tracking_table.item(i,0));break

    def edit_tracking(self,new=False):
        if not self.session or 'deadline_tracking' not in self.session.unlocked:return
        rows=deepcopy(self.session.pages['deadline_tracking']);item=self.tracking_table.currentItem();rid=item.data(Qt.ItemDataRole.UserRole) if item else None
        row=dict(id=uuid.uuid4().hex,number=max((r['number'] for r in rows),default=0)+1,issued_at='',document_no='',due_date='',work='',completed_date='') if new else next((r for r in rows if r['id']==rid),None)
        if row is None:return
        dialog=QDialog(self);dialog.setWindowTitle('新增期限' if new else '編輯期限');form=QFormLayout(dialog);fields={}
        for key,title in TRACKING_COLUMNS:
            if key in ('alert','overdue_date'):continue
            if key=='number':field=QSpinBox();field.setRange(1,999999999);field.setValue(row[key])
            elif key=='work':field=QPlainTextEdit(row[key])
            elif key=='issued_at':field=IssuedField(row[key])
            elif key in ('due_date','completed_date'):field=DateField();field.setText(row[key])
            else:field=QLineEdit(row[key])
            field.setObjectName('tracking-'+key);fields[key]=field;form.addRow(title,field)
        derived=QLabel();form.addRow('逾期日（自動）',derived)
        def update_date():derived.setText(deadline_status(dict(due_date=fields['due_date'].text(),completed_date=''))['overdue_date'])
        fields['due_date'].textChanged.connect(update_date);update_date()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);form.addRow(buttons);buttons.rejected.connect(dialog.reject)
        def save():
            result=deepcopy(row)
            for key,field in fields.items():result[key]=field.value() if key=='number' else field.toPlainText().strip() if key=='work' else field.text().strip()
            value=[r for r in rows if r['id']!=result['id']]+[result]
            try:validate_tracking(value);self.commit_extra('deadline_tracking',value)
            except ValueError as exc:QMessageBox.warning(dialog,'期限欄位錯誤',str(exc));return
            dialog.accept()
        buttons.accepted.connect(save);dialog.resize(700,600);dialog.exec()

    def remove_tracking(self):
        item=self.tracking_table.currentItem()
        if not item:return
        if QMessageBox.question(self,'移除期限','只移除選取紀錄，可回復動作復原。')==QMessageBox.StandardButton.Yes:self.commit_extra('deadline_tracking',[r for r in self.session.pages['deadline_tracking'] if r['id']!=item.data(Qt.ItemDataRole.UserRole)])
