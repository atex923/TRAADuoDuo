"""Date-entry dialogs; cancel never inserts a row or today's date."""
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog,QVBoxLayout,QGridLayout,QCalendarWidget,QLabel,QLineEdit,QDialogButtonBox
from .domain import decimal
from .scheduling import weather_text

class DateEntryDialog(QDialog):
    def __init__(self,parent,key,existing=None):
        super().__init__(parent); self.key=key; self.row=None
        self.setObjectName('calendarEntryDialog'); self.setWindowTitle('晴雨紀錄' if key=='weather' else '新增日期')
        layout=QVBoxLayout(self); self.calendar=QCalendarWidget()
        self.calendar.setSelectedDate(QDate.fromString(existing[0],'yyyy-MM-dd') if existing else QDate.currentDate())
        layout.addWidget(self.calendar); grid=QGridLayout(); layout.addLayout(grid); self.fields={}
        for i,(field,label) in enumerate([('am','上午'),('pm','下午'),('nc','不計工期'),('note','備註')] if key=='weather' else [('note','說明')]):
            widget=QLineEdit(); widget.setObjectName('calendar_'+field); widget.setAccessibleName(label)
            self.fields[field]=widget; grid.addWidget(QLabel(label),i,0); grid.addWidget(widget,i,1)
            widget.textChanged.connect(self.refresh)
        self.result_label=QLabel(); self.result_label.setWordWrap(True); layout.addWidget(self.result_label)
        self.error=QLabel(); self.error.setStyleSheet('color:#bd1b1b'); layout.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.submit); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('儲存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        if existing:
            values=dict(am=existing[1],pm=existing[2],note=existing[3],nc=existing[4] if len(existing)>4 else '0') if key=='weather' else dict(note=existing[1])
            for field,value in values.items(): self.fields[field].setText(value)
        elif key=='weather':
            for field in ('am','pm','nc'): self.fields[field].setText('0')
        self.refresh(); self.resize(480,520 if key=='weather' else 410)

    def candidate(self):
        day=self.calendar.selectedDate().toString('yyyy-MM-dd')
        if self.key!='weather': return [day,self.fields['note'].text()]
        am,pm,nc=(self.fields[k].text().strip() or '0' for k in ('am','pm','nc'))
        if decimal(am) not in (0,1) or decimal(pm) not in (0,decimal('.5')) or decimal(nc) not in (0,1):
            raise ValueError('上午填0或1、下午填0或0.5、不計工期填0或1。')
        return [day,am,pm,self.fields['note'].text(),nc]

    def refresh(self):
        if self.key!='weather' or 'nc' not in self.fields or not hasattr(self,'result_label'): return
        disabled=self.fields['am'].text().strip()=='1'
        for key in ('pm','nc','note'): self.fields[key].setDisabled(disabled)
        try: self.result_label.setText(weather_text(self.candidate()))
        except (ValueError,ArithmeticError): self.result_label.setText('請輸入有效的晴雨扣除值')

    def submit(self):
        try:
            self.row=self.candidate()
            pages=self.parent().session.pages
            if any(r[0]==self.row[0] for r in pages[self.key]):
                raise ValueError('同一表日期不可重複，請編輯既有紀錄。')
        except (ValueError,ArithmeticError) as exc:
            self.error.setText(str(exc)); return
        self.accept()
