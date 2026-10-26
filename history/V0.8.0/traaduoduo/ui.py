from concurrent.futures import ThreadPoolExecutor,CancelledError
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
import calendar
import logging
import sys

from PySide6.QtCore import Qt, QTimer, QDate, QSettings, Signal, QEvent
from PySide6.QtGui import QIcon, QColor, QTextCharFormat, QPixmap, QFont,QPen
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QGridLayout, QLabel, QPushButton, QTabWidget, QLineEdit,
    QComboBox, QGroupBox, QScrollArea, QDialog, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QCalendarWidget,
    QInputDialog, QListWidget, QPlainTextEdit, QTabBar, QSizePolicy,QBoxLayout,QTableView)

from . import VERSION, APP_NAME,DISPLAY_VERSION
from .store import ProjectStore, DEFAULT_BASIC
from .session import EditSession
from .domain import calculate_day, calculate_finish, count_workdays
from .importer import preview_database
from .domain import decimal
from .forms import StageForms, LockSwitch, BottomGroups, ProjectTable,info_button
from .calendar_forms import DateEntryDialog
from .scheduling import working_calendar,weather_text,LINKED_DATES,deadlines
from .migrations import SCHEMA_VERSION
from .finance_forms import FinanceForms
from .billing_forms import BillingForms
from .billing import PAYMENT_KEYS
from .advanced_forms import AdvancedForms
from .layout_settings import LayoutSettings
from .aa_import import HEADERS
from .idle_save import IdleSaving,InputActivity
from .desktop_features import DesktopFeatures
from .export_forms import ExportForms

ROOT = Path(__file__).resolve().parent.parent


class MonthCalendar(QCalendarWidget):
    navigate = Signal(int)

    def __init__(self):
        super().__init__()
        self.day_details={}
        self.width_drag=None
        self.calendar_settings=None;self._compact_pending=False
        # Calendar uses an internal item view, which receives real key/wheel events.
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)

    def compact_rows(self):
        self._compact_pending=False
        view=self.findChild(QTableView,'qt_calendar_calendarview')
        if not view:return
        height=view.fontMetrics().height()+round(3*self.logicalDpiY()/72)
        header=view.verticalHeader();header.setMinimumSectionSize(1);header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        view.setRowHeight(0,height)
        for row in range(1,view.model().rowCount()):view.setRowHeight(row,max(50,(view.viewport().height()-height)//6))
        view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if not self.width_drag:
            visible=[col for col in range(view.model().columnCount()) if not view.isColumnHidden(col)]
            for col in visible:
                saved=self.calendar_settings.value(f'widths/calendar/weekdays/{col}',None) if self.calendar_settings else None
                view.setColumnWidth(col,int(saved) if saved is not None else max(70,view.viewport().width()//len(visible)))

    def bind_width_settings(self,settings):
        self.calendar_settings=settings;QTimer.singleShot(0,self.compact_rows)

    def reset_widths(self):
        if self.calendar_settings:self.calendar_settings.remove('widths/calendar/weekdays')
        self.compact_rows()

    def resizeEvent(self,event):
        super().resizeEvent(event);self.compact_rows()

    def paintCell(self,painter,rect,day):
        info=self.day_details.get(day.toString('yyyy-MM-dd'))
        if info is None:
            painter.save()
            painter.fillRect(rect,QColor('#f4f2e8'))
            painter.setPen(QColor('#999999'))
            painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,str(day.day()))
            self.paint_border(painter,rect,day)
            painter.restore()
            return
        painter.save()
        painter.fillRect(rect,QColor('#ffffff'))
        height=max(10,rect.height()//5)
        header=rect.adjusted(0,0,0,-rect.height()+height)
        painter.fillRect(header,QColor('#fce4d6' if info['holiday'] else '#f4cccc' if day.dayOfWeek()>=6 else '#d9edf7'))
        painter.setPen(QColor('#111111'))
        font=QFont(self.font())
        font.setPixelSize(max(9,min(12,height-2)))
        painter.setFont(font)
        painter.drawText(header,Qt.AlignmentFlag.AlignCenter,str(day.day()))
        details=rect.adjusted(0,height,0,0)
        if info['holiday'] or info['railway']:
            painter.fillRect(details,QColor('#FFE6FF'))
        elif info['weather']:
            painter.fillRect(details,QColor('#D0D0D0'))
        lines=[info['holiday'] or info.get('makeup',''),info['railway'],info['weather'],info['work']+' 日' if info['work'] else '']
        font.setPixelSize(max(8,min(11,height-2)))
        painter.setFont(font)
        for index,text in enumerate(lines,1):
            row=rect.adjusted(3,index*height,-2,-rect.height()+(index+1)*height)
            if index==3 and info['weather']:
                painter.fillRect(row,QColor('#D0D0D0'))
            painter.drawText(row,Qt.AlignmentFlag.AlignVCenter,painter.fontMetrics().elidedText(text,Qt.TextElideMode.ElideRight,row.width()))
        self.paint_border(painter,rect,day)
        painter.restore()

    def paint_border(self,painter,rect,day):
        width=2*self.logicalDpiY()/72 if day==QDate.currentDate() else 1
        pen=QPen(QColor('#316ac5' if day in (self.selectedDate(),QDate.currentDate()) else '#c4ccc7'));pen.setWidthF(width);painter.setPen(pen)
        inset=max(1,round(width/2));painter.drawRect(rect.adjusted(inset,inset,-inset,-inset))

    def eventFilter(self, watched, event):
        view=self.findChild(QTableView,'qt_calendar_calendarview')
        if view and watched is view.viewport() and event.type() in (QEvent.Type.Resize,QEvent.Type.Show) and not self._compact_pending:
            self._compact_pending=True;QTimer.singleShot(0,self.compact_rows)
        if view and watched is view.viewport() and event.type() in (QEvent.Type.MouseButtonPress,QEvent.Type.MouseMove,QEvent.Type.MouseButtonRelease):
            pos=event.position();col=view.columnAt(int(pos.x()));row=view.rowAt(int(pos.y()))
            edge=col>=0 and abs(view.columnViewportPosition(col)+view.columnWidth(col)-pos.x())<7
            if event.type()==QEvent.Type.MouseButtonPress and row==0 and edge:
                self.width_drag=(col,pos.x(),view.columnWidth(col));return True
            if event.type()==QEvent.Type.MouseMove:
                if self.width_drag:
                    col,x,width=self.width_drag;view.setColumnWidth(col,max(70,int(width+pos.x()-x)));return True
                watched.setCursor(Qt.CursorShape.SizeHorCursor if row==0 and edge else Qt.CursorShape.ArrowCursor)
            if event.type()==QEvent.Type.MouseButtonRelease and self.width_drag:
                if self.calendar_settings:
                    for c in range(view.model().columnCount()):self.calendar_settings.setValue(f'widths/calendar/weekdays/{c}',view.columnWidth(c))
                    self.calendar_settings.sync()
                self.width_drag=None;return True
        if event.type() == QEvent.Type.Wheel and event.angleDelta().y():
            self.navigate.emit(-1 if event.angleDelta().y() > 0 else 1)
            return True
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.navigate.emit(-1 if event.key() == Qt.Key.Key_Up else 1)
            return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        if event.angleDelta().y():
            self.navigate.emit(-1 if event.angleDelta().y() > 0 else 1)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.navigate.emit(-1 if event.key() == Qt.Key.Key_Up else 1)
            event.accept()
        else:
            super().keyPressEvent(event)


class Window(ExportForms,DesktopFeatures,IdleSaving, AdvancedForms, BillingForms, FinanceForms, StageForms, QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        if sys.platform=='darwin':
            QApplication.instance().setFont(QFont('PingFang TC',10))
        self.settings = settings or QSettings('TRAADuoDuo', 'TRAADuoDuo')
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='project-io')
        self.future = None
        self._auto_job=None;self._auto_after=[]
        self.store = None
        self.session = None
        self.revision = 0
        self.loading = False
        self.path = ''
        self.setWindowTitle(f'{APP_NAME}  TRAADuoDuo {DISPLAY_VERSION}')
        self.setWindowIcon(QIcon(str(ROOT / 'assets/app_icon.png')))
        self.resize(1160, 800)
        self.setMinimumSize(860, 650)
        self.setStyleSheet((ROOT / 'assets/winxp.qss').read_text(encoding='utf-8'))
        self.body = QWidget()
        self.setCentralWidget(self.body)
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(16, 12, 16, 8)
        banner = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QPixmap(str(ROOT / 'assets/app_icon.png')).scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        banner.addWidget(icon)
        title = QLabel(f'{APP_NAME}  <small>TRAADuoDuo {DISPLAY_VERSION}</small><br><small>工程資料・施工日曆・案件管理</small>')
        title.setObjectName('title')
        banner.addWidget(title, 1)
        about = QPushButton('關於')
        about.clicked.connect(self.about)
        layout.addLayout(banner)
        self.edit_toolbar = QWidget()
        self.edit_toolbar.setObjectName('editToolbar')
        toolbar = QHBoxLayout(self.edit_toolbar)
        toolbar.setContentsMargins(6,5,6,5)
        toolbar.setSpacing(4)
        self.save_button = self.button('儲存', lambda: self.save())
        self.new_button = self.button('新增工程案', self.new_project)
        self.undo_button = self.button('回復動作', self.undo)
        self.print_button = self.button('匯出', self.export_report_dialog)
        self.print_button.setEnabled(False)
        self.print_button.setToolTip('依目前工程與頁面匯出 PDF／Excel')
        self.db_button = self.button('資料庫', self.database_panel)
        self.db_button.setText('選擇／管理')
        for button in (self.save_button, self.new_button, self.undo_button, self.print_button):
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.database_toolbar = QWidget()
        self.database_toolbar.setObjectName('databaseToolbar')
        db_controls = QHBoxLayout(self.database_toolbar)
        db_controls.setContentsMargins(8, 5, 8, 5)
        db_controls.setSpacing(6)
        db_controls.addWidget(QLabel('資料庫'))
        db_controls.addWidget(self.db_button)
        manage = self.button('工程管理', self.manage_projects)
        db_controls.addWidget(manage)
        self.project_selector = QComboBox()
        self.project_selector.setMinimumWidth(120)
        self.project_selector.setMaximumWidth(360)
        self.project_selector.setFixedHeight(28)
        self.project_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.project_selector.setToolTip('目前資料庫中的工程；選取即可切換')
        self.project_selector.activated.connect(lambda index: self.switch_project(self.project_selector.itemData(index)))
        db_controls.addWidget(self.project_selector, 1)
        legacy = self.button('載入舊資料庫', self.import_database)
        db_controls.addWidget(legacy)
        db_controls.addStretch()
        self.tab_header = QWidget()
        header = QHBoxLayout(self.tab_header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.primary_tabs = QTabBar()
        self.primary_tabs.setObjectName('primaryTabs')
        self.secondary_tabs = QTabBar()
        self.secondary_tabs.setObjectName('secondaryTabs')
        self.tab_divider = QLabel('│')
        self.tab_divider.setStyleSheet('color: #9eafa5; font-size: 20px;')
        for bar in (self.primary_tabs, self.secondary_tabs):
            bar.setExpanding(False)
            bar.setUsesScrollButtons(True)
            bar.setElideMode(Qt.TextElideMode.ElideNone)
            bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            bar.setFixedHeight(32)
        self.primary_tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        header.addWidget(self.primary_tabs)
        header.addWidget(self.tab_divider)
        header.addWidget(self.secondary_tabs, 1)
        header.setAlignment(Qt.AlignmentFlag.AlignLeft)
        header.addStretch(1)
        layout.addWidget(self.tab_header)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.basic_tabs = QTabWidget()
        self.tabs.addTab(self.basic_tabs, '基本資料')
        self.editors = {}
        self.locks = {}
        self.fields = {}
        self.tables = {}
        self.build_stage_basic()
        self.build_costs()
        self.build_guarantees()
        self.build_bids()
        for name in ('變更契約',):
            self.basic_tabs.addTab(self.placeholder(name,'後續階段開放；既有資料保留。'),name)
        self.calendar_tabs = QTabWidget()
        self.tabs.addTab(self.calendar_tabs, '施工日曆')
        merged=QScrollArea();merged.setWidgetResizable(True);merged_body=QWidget();merged.setWidget(merged_body);merged_layout=QHBoxLayout(merged_body)
        self.calendar_tabs.addTab(merged,'假期補班與疏運表')
        self.calendar_group_layout=merged_layout
        for key,title in [('holidays','假期表'),('makeup','補班日表'),('railway','鐵路疏運表')]:
            self.build_table(key,title,merged_layout)
        for key, name in [('weather', '晴雨表')]:
            self.build_table(key, name)
        self.build_calendar()
        self.billing_tabs=QTabWidget()
        self.tabs.addTab(self.billing_tabs,'工程計價')
        self.build_billing()
        self.build_advanced()
        for index in range(self.tabs.count()):
            self.primary_tabs.addTab(self.tabs.tabText(index))
        self.primary_tabs.setMaximumWidth(self.primary_tabs.sizeHint().width())
        self.primary_tabs.setFixedWidth(self.primary_tabs.sizeHint().width())
        # Keep the original page containers and indices; only move navigation.
        for widget in (self.tabs, self.basic_tabs, self.calendar_tabs,self.billing_tabs,self.detail_tabs,self.diary_tabs):
            widget.tabBar().hide()
        self.primary_tabs.currentChanged.connect(self.tabs.setCurrentIndex)
        self.secondary_tabs.currentChanged.connect(self.select_subpage)
        self.tabs.currentChanged.connect(self.sync_tab_header)
        self.basic_tabs.currentChanged.connect(self.sync_tab_header)
        self.calendar_tabs.currentChanged.connect(self.sync_tab_header)
        self.billing_tabs.currentChanged.connect(self.sync_tab_header)
        self.detail_tabs.currentChanged.connect(self.sync_tab_header)
        self.diary_tabs.currentChanged.connect(self.sync_tab_header)
        self.diary_tabs.currentChanged.connect(self.update_actions)
        self.sync_tab_header()
        self.about_toolbar=QWidget()
        self.about_toolbar.setObjectName('aboutToolbar')
        about_layout=QHBoxLayout(self.about_toolbar)
        about_layout.setContentsMargins(6,5,6,5)
        about_layout.addWidget(about)
        self.bottom_groups=BottomGroups(self.edit_toolbar,self.database_toolbar,self.about_toolbar)
        layout.addWidget(self.bottom_groups)
        self.message = QLabel('尚未開啟工程；請新增工程案或選擇資料庫。')
        self.db_label = QLabel('資料庫：未開啟')
        self.statusBar().addWidget(self.message, 1)
        self.statusBar().addPermanentWidget(self.db_label)
        self.poll = QTimer(self)
        self.poll.setInterval(40)
        self.poll.timeout.connect(self.poll_io)
        self.poll.start()
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(60000)
        self.autosave.timeout.connect(self.idle_timeout)
        self.input_activity=InputActivity(self);QApplication.instance().installEventFilter(self.input_activity)
        self.poll.timeout.connect(self.poll_background_save)
        self.tabs.currentChanged.connect(self.update_actions)
        self.tabs.currentChanged.connect(lambda index: self.refresh_calendar() if index==1 else None)
        self.basic_tabs.currentChanged.connect(self.update_actions)
        self.calendar_tabs.currentChanged.connect(self.update_actions)
        self.billing_tabs.currentChanged.connect(self.update_actions)
        self.layout_settings=LayoutSettings(self); self.layout_settings.install()
        for key,ui in self.detail_ui.items():
            self.layout_settings.table(ui['tree'],'details/'+key,HEADERS)
            for i in range(16):ui['tree'].setColumnHidden(i,self.settings.value(f'details/{key}/hidden/{i}',False,type=bool))
        self.layout_settings.table(self.diary_table,'diary',['date','description','note'])
        for key,ui in self.asset_ui.items():self.layout_settings.table(ui['table'],key,[k for k,v in ui['fields']])
        self.layout_settings.table(self.tracking_table,'deadline_tracking',['number','alert','issued_at','document_no','due_date','work','completed_date','overdue_date'])
        self.layout_settings.table(self.upcoming_table,'deadline_upcoming',['due_date','work','remaining'])
        self.calendar.bind_width_settings(self.settings)
        reset=self.button('還原欄寬',self.layout_settings.reset);toolbar.addWidget(reset)
        self.update_actions()

        self.install_tray()

    def button(self, text, handler):
        button = QPushButton(text)
        button.setFixedSize(88, 28)
        button.clicked.connect(handler)
        return button

    def resizeEvent(self,event):
        super().resizeEvent(event)
        for name,threshold in (('basic_columns',1100),('cost_columns',1320),('management_columns',1320),('calendar_group_layout',1320)):
            layout=getattr(self,name,None)
            if layout:
                layout.setDirection(QBoxLayout.Direction.TopToBottom if self.width()<threshold else QBoxLayout.Direction.LeftToRight)

    def active_subtabs(self):
        if self.tabs.currentIndex()==4:return self.diary_tabs
        if self.tabs.currentIndex() == 0:
            return self.basic_tabs
        if self.tabs.currentIndex() == 1:
            return self.calendar_tabs
        if self.tabs.currentIndex() == 2:
            return self.billing_tabs
        if self.tabs.currentIndex() == 3:
            return self.detail_tabs
        return None

    def sync_tab_header(self, *_):
        self.primary_tabs.blockSignals(True)
        self.primary_tabs.setCurrentIndex(self.tabs.currentIndex())
        self.primary_tabs.blockSignals(False)
        source = self.active_subtabs()
        self.secondary_tabs.blockSignals(True)
        while self.secondary_tabs.count():
            self.secondary_tabs.removeTab(0)
        if source:
            for index in range(source.count()):
                self.secondary_tabs.addTab(source.tabText(index))
                self.secondary_tabs.setTabToolTip(index, source.tabText(index))
            self.secondary_tabs.setCurrentIndex(source.currentIndex())
        self.secondary_tabs.blockSignals(False)
        # Cocoa centers tabs inside an expanding QTabBar; constrain its content
        # width and put surplus space in the trailing layout stretch instead.
        self.secondary_tabs.setMaximumWidth(max(0,self.secondary_tabs.sizeHint().width()))
        self.secondary_tabs.setVisible(source is not None)
        self.tab_divider.setVisible(source is not None)

    def select_subpage(self, index):
        source = self.active_subtabs()
        if source and index >= 0:
            source.setCurrentIndex(index)

    def placeholder(self, title, description):
        widget = QWidget()
        box = QVBoxLayout(widget)
        box.addStretch()
        heading = QLabel(title)
        heading.setObjectName('placeholderTitle')
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(description)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(heading)
        box.addWidget(label)
        box.addStretch()
        return widget

    def edit_page(self, key):
        outer = QWidget()
        layout = QVBoxLayout(outer)
        row = QHBoxLayout()
        state = LockSwitch()
        state.clicked.connect(lambda: self.toggle_lock(key))
        self.locks[key] = state
        row.addWidget(state)
        row.addWidget(QLabel('鎖定可捲動／複製　·　自動儲存　·　復原 10 次'))
        row.addStretch()
        layout.addLayout(row)
        content = QWidget()
        self.editors[key] = content
        layout.addWidget(content, 1)
        return outer, content

    def basic_edited(self):
        self.input_activity.touch()
        self.message.setText('尚有變更；輸入完成後自動儲存')

    def capture_basic(self):
        self.capture_form('basic')
        self.capture_form('guarantees')
        self.capture_costs()

    def build_table(self, key, title, target=None):
        outer, content = self.edit_page(key)
        outer.setProperty('calendarPage',key)
        layout = QVBoxLayout(content)
        row = QHBoxLayout()
        add = QPushButton('新增日期')
        remove = QPushButton('移除選取列')
        add.clicked.connect(lambda: self.add_row(key))
        remove.clicked.connect(lambda: self.remove_row(key))
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        layout.addLayout(row)
        table = ProjectTable(0, 5 if key == 'weather' else 2)
        table.setHorizontalHeaderLabels(['日期', '上午', '下午', '不計工期', '備註'] if key == 'weather' else ['日期', '說明'])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        metrics=table.fontMetrics()
        table.setColumnWidth(0,metrics.horizontalAdvance('YYYY-MM-DD')+metrics.horizontalAdvance('中')*3+20)
        table.setColumnWidth(4 if key=='weather' else 1,metrics.horizontalAdvance('中')*10+20)
        table.cellClicked.connect(lambda *_,k=key:setattr(self,'_calendar_table_key',k))
        table.focused.connect(lambda k=key:setattr(self,'_calendar_table_key',k))
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSortingEnabled(True)
        table.itemChanged.connect(lambda _: self.capture_table(key))
        self.tables[key] = table
        layout.addWidget(table)
        text = '日期 YYYY-MM-DD；同一表日期不可重複。'
        if key == 'weather':
            text += ' 上午1全日不計，下午0.5半日不計；不計工期1全日排除。舊上午0.5保留原先全日扣除語意。'
        elif key in ('holidays', 'railway'):
            text += ' 本表列入的日期全部不計工期。'
        info = info_button(content,title,text)
        row.addWidget(info)
        if target is None:
            self.calendar_tabs.addTab(outer, title)
        else:
            group=QGroupBox(title); group.setObjectName('holidayGroup')
            group_layout=QVBoxLayout(group); group_layout.addWidget(outer); target.addWidget(group,1)

    def capture_table(self, key):
        if self.loading or not self.session or key not in self.session.unlocked:
            return
        table = self.tables[key]
        value = [[table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())]
                 for r in range(table.rowCount())]
        if key=='weather':
            value=[[r[0],r[1],r[2],r[4],r[3]] for r in value]
        self.session.change(key, value)
        if key=='weather': self.apply_weather_cells()
        self.changed()

    def add_row(self, key):
        self._calendar_table_key=key
        if not self.session or key not in self.session.unlocked:
            return
        dialog=DateEntryDialog(self,key)
        if dialog.exec()!=QDialog.DialogCode.Accepted or dialog.row is None:
            return
        rows = deepcopy(self.session.pages[key]); rows.append(dialog.row)
        self.session.change(key, rows)
        self.populate_table(key)
        self.changed()

    def remove_row(self, key):
        self._calendar_table_key=key
        if not self.session or key not in self.session.unlocked:
            return
        selected = {self.tables[key].item(item.row(),0).text() for item in self.tables[key].selectedItems() if self.tables[key].item(item.row(),0)}
        self.capture_table(key)
        self.session.change(key, [r for r in self.session.pages[key] if r[0] not in selected])
        self.populate_table(key)
        self.changed()

    def build_calendar(self):
        page = QWidget()
        page.setProperty('calendarPage','ledger')
        self.calendar_page=page
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        previous, following = QPushButton('◀ 上一月'), QPushButton('下一月 ▶')
        previous.clicked.connect(lambda: self.move_month(-1))
        following.clicked.connect(lambda: self.move_month(1))
        self.month_input=QLineEdit()
        self.month_input.setFixedWidth(108)
        self.month_input.setPlaceholderText('YYYY-MM')
        self.month_input.setToolTip('西元年份及月份，例如 2026-10；Enter 跳至該月')
        self.month_input.returnPressed.connect(self.jump_month)
        generate=QPushButton('產生施工曆')
        generate.clicked.connect(self.jump_month)
        self.month_label = QLabel()
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.addWidget(previous)
        controls.addWidget(self.month_input)
        controls.addWidget(generate)
        controls.addWidget(self.month_label, 1)
        controls.addWidget(following)
        layout.addLayout(controls)
        self.calendar = MonthCalendar()
        self.calendar.setNavigationBarVisible(False)
        self.calendar.setGridVisible(True)
        self.calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.navigate.connect(self.move_month)
        self.calendar.currentPageChanged.connect(self.refresh_calendar)
        self.calendar.selectionChanged.connect(self.refresh_calendar)
        layout.addWidget(self.calendar, 1)
        self.calendar_summary = QLabel('開啟工程後顯示工期統計。')
        self.calendar_summary.setWordWrap(True)
        layout.addWidget(self.calendar_summary)
        self.calendar_tabs.addTab(page, '施工曆')
        self.refresh_calendar()

    def move_month(self, delta):
        shown = QDate(self.calendar.yearShown(), self.calendar.monthShown(), 1).addMonths(delta)
        self.calendar.setCurrentPage(shown.year(), shown.month())

    def jump_month(self):
        shown=QDate.fromString(self.month_input.text()+'-01','yyyy-MM-dd')
        if not shown.isValid():
            self.message.setText('月份請輸入 YYYY-MM')
            return
        self.calendar.setCurrentPage(shown.year(),shown.month())
        self.refresh_calendar()

    def refresh_calendar(self, *_):
        year, month = self.calendar.yearShown(), self.calendar.monthShown()
        self.month_label.setText(f'{year} 年 {month} 月')
        self.month_input.setText(f'{year:04d}-{month:02d}')
        if not self.session:
            return
        if self.tabs.currentIndex()!=1:
            return
        try:
            context = working_calendar(self.session.pages)
            basic=self.session.pages['basic']
            start=date.fromisoformat(basic['start']) if basic['start'] else None
            target=decimal(basic['days'] or '0')
            finish=None
            if start and target>0:
                cache_key=(self.store.project_id,repr(context),basic['start'],basic['days'])
                if getattr(self,'_finish_key',None)!=cache_key:
                    self._finish_value=calculate_finish(start,basic['days'],context)
                    self._finish_key=cache_key
                finish=self._finish_value
            first=date(year,month,1)
            running=min(target,count_workdays(start,first-timedelta(days=1),context)) if finish and start<first else decimal(0)
            holiday_names=dict(self.session.pages['holidays'])
            makeup_names=dict(self.session.pages['makeup'])
            railway_names=dict(self.session.pages['railway'])
            weather_rows={r[0]:r for r in self.session.pages['weather']}
            self.calendar.day_details={}
            total = 0
            for day in range(1, calendar.monthrange(year, month)[1] + 1):
                value, reason = calculate_day(date(year, month, day), context)
                key=f'{year:04d}-{month:02d}-{day:02d}'
                weather=weather_rows.get(key)
                current=date(year,month,day)
                cumulative=''
                active=bool(finish and start<=current<=finish)
                daily=min(value,max(decimal(0),target-running)) if active else decimal(0)
                if active:
                    running+=daily
                    cumulative=format(running.normalize(),'f')
                self.calendar.day_details[key]=dict(holiday=holiday_names.get(key,''),makeup=('補班：'+makeup_names[key] if key in makeup_names else ''),railway=railway_names.get(key,''),weather=(weather_text(weather) if weather else ''),work=cumulative,daily=format(daily.normalize(),'f') if active else '')
                total += daily
                fmt = QTextCharFormat()
                fmt.setBackground(QColor('#e2efdd' if value else '#eeeae1'))
                fmt.setToolTip((f'{daily} 日：{reason}' if active else '非工程計算範圍')+f'\n假日：{holiday_names.get(key,"")}\n疏運：{railway_names.get(key,"")}')
                self.calendar.setDateTextFormat(QDate(year, month, day), fmt)
            chosen = self.calendar.selectedDate().toPython()
            value, reason = calculate_day(chosen, context)
            text = f'本月工程可計工期：{total} 日　｜　{chosen}：'
            text += ('已達契約工期' if finish and chosen>finish else f'{value} 日，{reason}' if finish and start<=chosen else '非工程計算範圍')
            basic = self.session.pages['basic']
            if basic['start'] and decimal(basic['days'] or '0') > 0:
                start = date.fromisoformat(basic['start'])
                cache_key=(self.store.project_id,repr(context),basic['start'],basic['days'])
                if getattr(self,'_finish_key',None)!=cache_key:
                    self._finish_value=calculate_finish(start,basic['days'],context)
                    self._finish_key=cache_key
                finish = self._finish_value
                text += f'\n依目前規則推算竣工：{finish}'
                if start<=chosen<=finish:
                    text+=f'　｜　開工至選取日累計：{min(target,count_workdays(start, chosen, context))} 日'
            elif decimal(basic['days'] or '0') == 0:
                text += '\n契約工期尚未設定，請補填後再推算竣工。'
            self.calendar_summary.setText(text)
            self.calendar.updateCells()
        except (ValueError, ArithmeticError,OverflowError) as exc:
            self.calendar_summary.setText(f'請修正輸入後再計算：{exc}')

    def changed(self):
        try:
            self.session.reconcile()
            self.refresh_finance()
            for key in (*LINKED_DATES,'warranty_end'):
                self.fields[key].setText(self.session.pages['basic'].get(key,''))
            self.refresh_deadline_notice()
            self.refresh_calendar()
        except (ValueError,ArithmeticError,KeyError,OverflowError) as exc:
            self.message.setText('資料尚未完成：'+str(exc))
            try: deadlines(self.session.pages)
            except (ValueError,ArithmeticError,KeyError,OverflowError):
                for key in LINKED_DATES: self.fields[key].clear()
        if self.session.dirty():
            self.message.setText('尚有變更，等待自動儲存…')
            self.input_activity.touch()
        self.update_actions()

    def current_page(self):
        if self.tabs.currentIndex() == 0 and self.basic_tabs.currentIndex() == 0:
            return 'basic'
        if self.tabs.currentIndex()==0 and self.basic_tabs.currentIndex()==2:
            return 'guarantees'
        if self.tabs.currentIndex()==0 and self.basic_tabs.currentIndex()==1:
            return 'costs'
        if self.tabs.currentIndex()==0 and self.basic_tabs.currentIndex()==3:
            return 'bids'
        if self.tabs.currentIndex() == 1:
            page=self.calendar_tabs.currentWidget()
            key=page.property('calendarPage') if page else None
            if key=='ledger': return None
            return key or getattr(self,'_calendar_table_key','holidays')
        if self.tabs.currentIndex()==2:
            return PAYMENT_KEYS[self.billing_tabs.currentIndex()]
        if self.tabs.currentIndex()==4:return 'deadline_tracking' if self.diary_tabs.currentIndex()==1 else 'diary'
        if self.tabs.currentIndex() in (3,4,5,6):
            return ['details','diary','documents','photos'][self.tabs.currentIndex()-3]
        return None

    def update_actions(self, *_):
        ready = self.session is not None and self.future is None and not getattr(self, 'archived', False)
        self.print_button.setEnabled(self.session is not None and self.future is None)
        for key, widget in self.editors.items():
            editable=bool(ready and key in self.session.unlocked)
            widget.setEnabled(True)
            self.locks[key].setEnabled(ready)
            self.locks[key].blockSignals(True)
            self.locks[key].setChecked(editable)
            self.locks[key].setText('可編輯' if editable else '已鎖定')
            self.locks[key].blockSignals(False)
            if key in self.tables:
                self.tables[key].setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers if editable else QAbstractItemView.EditTrigger.NoEditTriggers)
                for button in widget.findChildren(QPushButton):
                    if button.objectName()!='fieldInfo':
                        button.setEnabled(editable)
        self.apply_form_locks(ready)
        self.apply_finance_locks(ready)
        self.apply_billing_locks(ready)
        self.apply_advanced_locks(ready)
        key = self.current_page()
        self.undo_button.setEnabled(bool(ready and key and key in self.session.unlocked and self.session.history[key]))
        self.save_button.setEnabled(ready)

    def toggle_lock(self, key):
        if key in ('holidays','makeup','railway'): self._calendar_table_key=key
        if not self.session or self.future or getattr(self,'archived',False):
            return
        if key in self.session.unlocked:
            self.capture_basic()
            self.save(after=lambda: self.lock_page(key))
        else:
            self.session.unlocked.add(key)
            self.update_actions()

    def lock_page(self, key):
        self.session.unlocked.discard(key)
        self.update_actions()

    def undo(self):
        key = self.current_page()
        if key:
            self.session.undo(key)
            self.session.reconcile()
            self.populate()
            self.changed()

    def populate_table(self, key):
        self.loading = True
        table = self.tables[key]
        sorting=table.isSortingEnabled()
        table.setSortingEnabled(False)
        table.setRowCount(len(self.session.pages[key]))
        for r, row in enumerate(self.session.pages[key]):
            values=([row[0],row[1],row[2],row[4] if len(row)>4 else '0',row[3]] if key=='weather' else row)
            for c, value in enumerate(values):
                item=QTableWidgetItem(str(value))
                if c==0: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(r, c, item)
        table.setSortingEnabled(sorting)
        table.sortItems(0,Qt.SortOrder.AscendingOrder)
        self.loading = False
        if key=='weather': self.apply_weather_cells()

    def apply_weather_cells(self):
        table=self.tables['weather']
        table.blockSignals(True)
        for r in range(table.rowCount()):
            am=table.item(r,1)
            if not am: continue
            disabled=am.text().strip()=='1'
            for c in (2,3,4):
                item=table.item(r,c)
                if item:
                    flags=Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsEnabled
                    if not disabled: flags|=Qt.ItemFlag.ItemIsEditable
                    item.setFlags(flags); item.setBackground(QColor('#D0D0D0' if disabled else '#FFFFFF'))
        table.blockSignals(False)

    def populate(self):
        self.populate_stage_forms()
        self.populate_finance()
        self.populate_billing()
        self.populate_advanced()
        for key in self.tables:
            self.populate_table(key)
        self.refresh_calendar()
        self.update_actions()

    def io(self, operation, success):
        if self._auto_job is not None:
            self._auto_after.append(lambda:self.io(operation,success));return
        if self.future is not None:
            return
        self.autosave.stop()
        self.body.setEnabled(False)
        self.message.setText('處理中…')
        self.callback = success
        self.future = self.pool.submit(operation)

    def poll_io(self):
        if self.future is None or not self.future.done():
            return
        future, callback = self.future, self.callback
        self.future = None
        self.body.setEnabled(True)
        try:
            callback(future.result())
        except CancelledError:
            self.message.setText('已取消庫存，清單與原檔未改動')
        except Exception as exc:
            logging.exception('Project operation failed')
            self.message.setText(f'操作失敗：{exc}；目前編輯內容仍保留')
            QMessageBox.warning(self, '操作未完成', str(exc))
        finally:
            progress=getattr(self,'_asset_progress',None)
            if progress:
                progress.reset();progress.deleteLater();self._asset_progress=None
        self.update_actions()

    def save(self, auto=False, after=None):
        if self._auto_job is not None:
            self._auto_after.append(lambda:self.save(auto=auto,after=after));return
        if auto and after is None:
            self.start_background_save();return
        if self.future is not None:
            return
        if not self.session:
            if after:
                after()
            return
        self.capture_basic()
        self.autosave.stop()
        try:
            self.session.validate()
        except (ValueError, ArithmeticError, KeyError) as exc:
            self.message.setText(f'尚未儲存：{exc}')
            if not auto:
                QMessageBox.warning(self, '請檢查資料', str(exc))
            return
        dirty = self.session.dirty()
        if not dirty:
            if after:
                after()
            return
        snapshot = deepcopy(self.session.pages)
        store, revision = self.store, self.revision
        def done(result):
            self.revision, stamp = result
            self.session.saved = snapshot
            self.update_actions()
            clock = datetime.fromisoformat(stamp).astimezone().strftime('%H:%M:%S')
            self.message.setText(f'{"自動儲存" if auto else "已儲存"}：{clock}')
            self.refresh_calendar()
            if after:
                after()
        self.io(lambda: store.save(dirty, revision), done)

    def adopt(self, payload):
        self.project_selector.blockSignals(True)
        self.project_selector.clear()
        for project in payload.get('projects', []):
            self.project_selector.addItem(project['name'] + ('（封存）' if project['archived'] else ''), project['project_id'])
        self.project_selector.setCurrentIndex(self.project_selector.findData(payload['metadata']['project_id']))
        self.project_selector.blockSignals(False)
        if payload['pages'] is None:
            self.path = payload['path']
            self.store = ProjectStore(self.path)
            self.session = None
            self.archived = False
            self.settings.setValue('last_project', self.path)
            self.settings.remove('last_project_id')
            self.db_label.setText('資料庫：' + Path(self.path).name)
            self.message.setText('統一資料庫已開啟；請新增工程或載入舊資料庫。')
            self.clear_stage_forms()
            self.clear_finance()
            self.clear_billing()
            self.populate_advanced()
            self.loading = True
            for field in self.fields.values():
                if isinstance(field, QLineEdit):
                    field.clear()
            for table in self.tables.values():
                table.setRowCount(0)
            self.loading = False
            self.update_actions()
            return
        session = EditSession(payload['pages'])
        session.validate()
        self.path = payload['path']
        self.store = ProjectStore(self.path, payload['metadata']['project_id'])
        self.session = session
        self.archived = payload['metadata'].get('archived') == '1'
        self.revision = int(payload['metadata']['revision'])
        self.settings.setValue('last_project', self.path)
        self.settings.setValue('last_project_id', payload['metadata']['project_id'])
        self.db_label.setText('資料庫：' + Path(self.path).name)
        self.db_label.setToolTip(self.path)
        self.message.setText('工程已開啟；每頁預設鎖定')
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())
        self.populate()

    def open_path(self, path):
        last = self.settings.value('last_project_id', '') if str(path) == self.settings.value('last_project', '') else ''
        def load():
            import sqlite3
            from contextlib import closing
            from .store import APPLICATION_ID
            with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
                app_id = conn.execute('PRAGMA application_id').fetchone()[0]
                version = conn.execute('PRAGMA user_version').fetchone()[0]
            if app_id == APPLICATION_ID and version == SCHEMA_VERSION:
                return ('library', ProjectStore(path).open_result(last))
            return ('legacy', preview_database(path))
        def done(result):
            kind, payload = result
            if kind == 'library':
                self.adopt(payload)
            else:
                self.show_import(payload)
        self.save(after=lambda: self.io(load, done))

    def switch_project(self, project_id):
        # Keep the selector aligned with the displayed draft until loading succeeds.
        self.project_selector.setCurrentIndex(self.project_selector.findData(self.store.project_id))
        path = self.path
        def load():
            store = ProjectStore(path, project_id)
            payload = store.load()
            store.remember()
            return payload
        self.save(after=lambda: self.io(load, self.adopt))

    def choose_project(self):
        path, _ = QFileDialog.getOpenFileName(self, '選擇工程資料庫', str(Path(self.path).parent) if self.path else '', '工程資料庫 (*.db *.sqlite);;所有檔案 (*)')
        if path:
            self.open_path(path)

    def new_project(self):
        if self.store:
            name, ok = QInputDialog.getText(self, '新增工程', '工程名稱')
            if ok and name.strip():
                self.save(after=lambda: self.io(lambda: self.store.add_project(name.strip()), self.adopt))
            return
        self.new_database()

    def new_database(self):
        path, _ = QFileDialog.getSaveFileName(self, '新增統一資料庫', 'TRAADuoDuo.db', 'SQLite (*.db)')
        if path:
            if Path(path).exists():
                QMessageBox.warning(self, '檔案已存在', '請使用新檔名；本程式不覆寫既有資料庫。')
                return
            self.save(after=lambda: self.io(lambda: ProjectStore.create(path), self.adopt))

    def backup(self):
        if not self.store:
            return
        name = f'{Path(self.path).stem}_backup_{datetime.now():%Y%m%d_%H%M%S}.db'
        path, _ = QFileDialog.getSaveFileName(self, '備份資料庫', str(Path(self.path).with_name(name)), 'SQLite (*.db)')
        if path:
            self.save(after=lambda: self.io(lambda: self.store.backup(path), lambda result: self.message.setText('備份完成：' + result)))

    def database_panel(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('資料庫功能')
        box = QVBoxLayout(dialog)
        label = QLabel(self.path or '尚未開啟工程')
        label.setWordWrap(True)
        box.addWidget(label)
        for title, action in [('選擇資料庫／重新連結', self.choose_project), ('新增統一資料庫', self.new_database), ('工程管理', self.manage_projects), ('匯入舊資料庫', self.import_database), ('匯出目前工程', self.export_project), ('匯出匯入報告', self.export_report), ('備份資料庫', self.backup)]:
            button = QPushButton(title)
            button.setEnabled(bool(self.store) or title in ('選擇資料庫／重新連結', '新增統一資料庫', '匯入舊資料庫', '工程管理'))
            button.clicked.connect(lambda checked=False, action=action: (dialog.accept(), action()))
            box.addWidget(button)
        dialog.resize(440, 200)
        dialog.exec()

    def manage_projects(self):
        if not self.store:
            self.database_panel()
            return
        self.save(after=lambda: self.io(self.store.list_projects, self.show_projects))

    def show_projects(self, projects):
        dialog = QDialog(self)
        dialog.setWindowTitle('統一資料庫・工程管理')
        box = QVBoxLayout(dialog)
        search = QLineEdit()
        search.setPlaceholderText('搜尋工程名稱、編號、承攬商')
        box.addWidget(search)
        table = QTableWidget(len(projects), 6)
        table.setHorizontalHeaderLabels(['工程名稱','編號','承攬商','工期','最近儲存','狀態'])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, p in enumerate(projects):
            for col, value in enumerate([p['name'],p['number'],p['contractor'],p['days'],p['saved_at'],'已封存' if p['archived'] else '使用中']):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, p['project_id'])
                table.setItem(row, col, item)
        table.setSortingEnabled(True)
        def filter_rows(text):
            for row in range(table.rowCount()):
                table.setRowHidden(row, text.casefold() not in ' '.join(table.item(row,c).text() for c in range(3)).casefold())
        search.textChanged.connect(filter_rows)
        box.addWidget(table)
        row = QHBoxLayout()
        box.addLayout(row)
        def selected():
            index = table.currentRow()
            return table.item(index,0).data(Qt.ItemDataRole.UserRole) if index >= 0 and not table.isRowHidden(index) else None
        def open_selected():
            pid = selected()
            if pid:
                dialog.accept()
                self.switch_project(pid)
        def archive_selected():
            pid = selected()
            if pid:
                p = next(p for p in projects if p['project_id'] == pid)
                dialog.accept()
                self.io(lambda: self.store.archive(pid, not p['archived']), lambda _: self.switch_project(self.store.project_id))
        for title, handler in [('開啟工程',open_selected),('封存／恢復',archive_selected),('新增工程',lambda: (dialog.accept(),self.new_project())),('匯入',lambda: (dialog.accept(),self.import_database()))]:
            button = QPushButton(title)
            button.clicked.connect(handler)
            row.addWidget(button)
        table.cellDoubleClicked.connect(lambda *_: open_selected())
        dialog.resize(1000, 500)
        dialog.exec()

    def import_database(self):
        path, _ = QFileDialog.getOpenFileName(self, '匯入 TR_FxWork／TRAADuoDuo 舊工程', '', 'SQLite (*.db *.sqlite);;所有檔案 (*)')
        if path:
            self.save(after=lambda: self.io(lambda: preview_database(path), self.show_import))

    def show_import(self, preview):
        dialog = QDialog(self)
        dialog.setWindowTitle('匯入預覽・選擇工程')
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel(preview['kind'] + '：選取工程後確認匯入；原檔保持不變。'))
        listing = QListWidget()
        listing.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for item in preview['projects']:
            listing.addItem(item['pages']['basic']['name'])
            if item.get('errors'):
                entry = listing.item(listing.count()-1)
                entry.setText(entry.text() + '（資料異常，暫停匯入）')
                entry.setFlags(entry.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
        listing.selectAll()
        box.addWidget(listing)
        report = QPlainTextEdit()
        report.setReadOnly(True)
        report.setPlainText('\n\n'.join(p['pages']['basic']['name'] + '\n' + '\n'.join(p['report']) for p in preview['projects']))
        box.addWidget(report)
        button = QPushButton('備份並確認匯入選取工程')
        box.addWidget(button)
        def run():
            selected = [preview['projects'][listing.row(i)] for i in listing.selectedItems()]
            if not selected:
                return
            destination = None
            target = self.store
            if not target:
                destination, _ = QFileDialog.getSaveFileName(self, '建立新版統一資料庫（來源唯讀保留）', str(Path(preview['source']).with_name('TRAADuoDuo_V041_統一.db')) if preview.get('source') else 'TRAADuoDuo_V041_統一.db', 'SQLite (*.db)')
                if not destination:
                    return
                if Path(destination).exists():
                    QMessageBox.warning(self, '檔案已存在', '請選擇新的統一資料庫檔名；原檔不覆寫。')
                    return
            dialog.accept()
            def operation():
                store = target or ProjectStore.create_library(destination)
                result = store.import_preview(dict(preview, projects=selected))
                active = ProjectStore(store.path, result['ids'][0])
                active.remember()
                result['payload'] = active.load()
                return result
            def done(result):
                self.adopt(result['payload'])
                QMessageBox.information(self, '匯入完成', f"已匯入 {len(result['ids'])} 個工程\n匯入前整庫備份：{result['backup']}\n原始資料與報告可由資料庫功能匯出。")
            self.io(operation, done)
        button.clicked.connect(run)
        dialog.resize(800, 600)
        dialog.exec()

    def export_project(self):
        if self.store:
            path, _ = QFileDialog.getSaveFileName(self, '匯出目前工程', '工程匯出.db', 'SQLite (*.db)')
            if path:
                self.save(after=lambda: self.io(lambda: self.store.export_project(path), lambda p: self.message.setText('工程匯出完成：' + p)))

    def export_report(self):
        if self.store:
            path, _ = QFileDialog.getSaveFileName(self, '匯出原始資料與匯入報告', '匯入報告.json', 'JSON (*.json)')
            if path:
                self.io(lambda: self.store.export_report(path), lambda p: self.message.setText('報告匯出完成：' + p))

    def about(self):
        DesktopFeatures.about(self)

    def closeEvent(self, event):
        if self._auto_job is not None:
            event.ignore();self._auto_after.append(self.close);return
        if self.future is not None:
            event.ignore()
            self.message.setText('正在處理資料，完成後請再關閉')
            return
        self.capture_basic()
        if self.session and self.session.dirty():
            choice = QMessageBox.question(self, '尚未儲存', '關閉前是否儲存變更？',
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if choice == QMessageBox.StandardButton.Save:
                event.ignore()
                self.save(after=self.close)
                return
            if choice == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        self.autosave.stop()
        self.deadline_timer.stop()
        self.poll.stop()
        if self.tray:self.tray.hide()
        QApplication.instance().applicationStateChanged.disconnect(self._tracking_activation)
        QApplication.instance().removeEventFilter(self.layout_settings)
        QApplication.instance().removeEventFilter(self.input_activity)
        self.pool.shutdown(wait=False)
        self.thumbnail_timer.stop();self.thumbnail_pool.shutdown(wait=False,cancel_futures=True)
        for ui in self.asset_ui.values():ui['pdf'].clear()
        event.accept()
