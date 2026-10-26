"""Local UI preferences; never stored in project business data."""
import json
from .presentation import compact_header
from PySide6.QtCore import QObject, QEvent, Qt, QTimer
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTreeWidget, QLineEdit, QComboBox, QPlainTextEdit, QWidget, QDialog, QApplication


class LayoutSettings(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window=window
        self.settings=window.settings
        self.drag=None
        self.defaults={}

    def width(self,key,default):
        try: return max(70,min(1600,int(self.settings.value('widths/'+key,default))))
        except (ValueError,TypeError): return default

    def table(self,table,key,fields=None):
        if table.property('widthSettingsInstalled'): return
        table.setProperty('widthSettingsInstalled',True)
        table.setProperty('widthSettingsKey',key)
        header=table.header() if isinstance(table,QTreeWidget) else table.horizontalHeader()
        compact_header(header)
        fields=fields or [str(i) for i in range(table.columnCount())]
        defaults=[header.sectionSize(i) for i in range(len(fields))]
        self.defaults[key]=(table,fields,defaults)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i,f in enumerate(fields): header.resizeSection(i,self.width(key+'/'+f,defaults[i]))
        header.sectionResized.connect(lambda i,old,new:self.remember(key+'/'+fields[i],new) if i<len(fields) else None)

    def remember(self,key,width):
        self.settings.setValue('widths/'+key,int(width)); self.settings.sync()

    def field(self,widget,key,default=None):
        if widget.property('widthSettingsInstalled'): return
        widget.setProperty('widthSettingsInstalled',True)
        widget.setProperty('widthSettingsKey',key)
        widget.setProperty('resizableFormField',True)
        default=default or max(180,widget.sizeHint().width())
        self.defaults[key]=(widget,default)
        widget.setFixedWidth(self.width(key,default))
        widget.setMouseTracking(True); widget.installEventFilter(self)
        widget.setToolTip(widget.toolTip()+'\n右緣拖曳調整欄寬；調整後自動記憶。')

    def eventFilter(self,obj,event):
        kind=event.type()
        if kind==QEvent.Type.Show and isinstance(obj,QDialog) and self.window.isAncestorOf(obj):
            self.dialog(obj)
        if not isinstance(obj,QWidget) or not obj.property('resizableFormField'): return False
        if kind==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton and event.position().x()>=obj.width()-8:
            self.drag=(obj,event.globalPosition().x(),obj.width()); obj.grabMouse(); return True
        if kind==QEvent.Type.MouseMove:
            if self.drag and self.drag[0] is obj:
                obj.setFixedWidth(max(70,min(1600,int(self.drag[2]+event.globalPosition().x()-self.drag[1])))); return True
            obj.setCursor(Qt.CursorShape.SizeHorCursor if event.position().x()>=obj.width()-8 else Qt.CursorShape.IBeamCursor if isinstance(obj,QLineEdit) else Qt.CursorShape.ArrowCursor)
        if kind==QEvent.Type.MouseButtonRelease and self.drag and self.drag[0] is obj:
            self.remember(obj.property('widthSettingsKey'),obj.width()); self.drag=None; obj.releaseMouse(); return True
        if kind==QEvent.Type.Leave and not self.drag: obj.unsetCursor()
        return False

    def install(self):
        w=self.window
        QApplication.instance().installEventFilter(self)
        for key,fields in [('basic',w.fields),('guarantees',w.guarantee_fields)]:
            for name,field in fields.items():
                if isinstance(field,(QLineEdit,QComboBox,QPlainTextEdit)):
                    self.field(field,key+'/'+name,360 if name in ('name','description','warranty_note') else 240)
                    if key=='basic':
                        field.ensurePolished();baseline=74 if isinstance(field,QPlainTextEdit) else field.sizeHint().height()
                        field.setFixedHeight(max(field.fontMetrics().height(),baseline-round(3*field.logicalDpiY()/72)))
        for kind,fields in w.cost_fields.items():
            for name,field in fields.items(): self.field(field,'costs/'+kind+'/'+name,220)
        for key,table in w.tables.items(): self.table(table,'calendar/'+key)
        for key,table in w.payment_tables.items(): self.table(table,'billing/'+key,[f for f,_ in w.payment_columns[key]])
        for key,table in w.extension_tables.items(): self.table(table,'extensions/'+key)
        self.table(w.bid_table,'bids')
        self.table(w.allocation_table,'allocations')
        for key,combo in w.payment_periods.items(): self.field(combo,'billing/'+key+'/period',240)

    def reset(self):
        if self.window.tabs.currentIndex()==1 and self.window.calendar_tabs.currentWidget() is self.window.calendar_page:
            self.window.calendar.reset_widths();return
        page=self.window.tabs.currentWidget()
        if hasattr(page,'currentWidget'): page=page.currentWidget()
        for key,record in list(self.defaults.items()):
            widget=record[0]
            if widget is not page and not page.isAncestorOf(widget): continue
            if len(record)==2:
                self.settings.remove('widths/'+key); widget.setFixedWidth(record[1])
            else:
                header=widget.header() if isinstance(widget,QTreeWidget) else widget.horizontalHeader()
                for i,(field,width) in enumerate(zip(record[1],record[2])):
                    header.resizeSection(i,width); self.settings.remove('widths/'+key+'/'+field)
        self.settings.sync()

    def dialog(self,dialog):
        for i,field in enumerate(dialog.findChildren(QWidget)):
            if isinstance(field,(QLineEdit,QComboBox,QPlainTextEdit)) and not field.property('widthSettingsInstalled'):
                key='dialogs/'+dialog.windowTitle()+'/'+(field.objectName() or field.accessibleName() or str(i))
                self.field(field,key,240)
