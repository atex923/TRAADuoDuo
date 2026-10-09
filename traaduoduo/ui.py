from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
import calendar
import logging

from PySide6.QtCore import Qt, QTimer, QDate, QSettings, Signal, QEvent
from PySide6.QtGui import QIcon, QColor, QTextCharFormat, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QGridLayout, QLabel, QPushButton, QTabWidget, QLineEdit,
    QComboBox, QGroupBox, QScrollArea, QDialog, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QCalendarWidget)

from . import VERSION, APP_NAME
from .store import ProjectStore, DEFAULT_BASIC
from .session import EditSession
from .domain import calculate_day, calculate_finish, count_workdays

ROOT = Path(__file__).resolve().parent.parent


class MonthCalendar(QCalendarWidget):
    navigate = Signal(int)

    def __init__(self):
        super().__init__()
        # Calendar uses an internal item view, which receives real key/wheel events.
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
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


class Window(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or QSettings('TRAADuoDuo', 'TRAADuoDuo')
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='project-io')
        self.future = None
        self.store = None
        self.session = None
        self.revision = 0
        self.loading = False
        self.path = ''
        self.setWindowTitle(f'{APP_NAME}  TRAADuoDuo {VERSION}')
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
        title = QLabel(f'{APP_NAME}  <small>TRAADuoDuo {VERSION}</small><br><small>工程資料・施工日曆・案件管理</small>')
        title.setObjectName('title')
        banner.addWidget(title, 1)
        about = QPushButton('關於')
        about.clicked.connect(self.about)
        banner.addWidget(about)
        layout.addLayout(banner)
        toolbar = QHBoxLayout()
        self.save_button = self.button('儲存', lambda: self.save())
        self.new_button = self.button('新增工程案', self.new_project)
        self.undo_button = self.button('回復動作', self.undo)
        self.print_button = self.button('列印', lambda: None)
        self.print_button.setEnabled(False)
        self.print_button.setToolTip('本版尚未提供列印')
        self.db_button = self.button('資料庫', self.database_panel)
        for button in (self.save_button, self.new_button, self.undo_button, self.print_button, self.db_button):
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.basic_tabs = QTabWidget()
        self.tabs.addTab(self.basic_tabs, '基本資料')
        self.editors = {}
        self.locks = {}
        self.fields = {}
        self.tables = {}
        self.build_basic()
        for name in ('保證金', '工程費用', '變更契約'):
            self.basic_tabs.addTab(self.placeholder(name, '後續版本開放；本版先提供基本資料與工曆。'), name)
        self.calendar_tabs = QTabWidget()
        self.tabs.addTab(self.calendar_tabs, '施工日曆')
        for key, name in [('holidays', '假期表'), ('makeup', '補班日表'), ('railway', '鐵路輸運表'), ('weather', '晴雨表')]:
            self.build_table(key, name)
        self.build_calendar()
        for name in ('詳細表', '大事記', '文件庫', '照片庫'):
            self.tabs.addTab(self.placeholder(name, '此模組已列入後續開發規劃，本版尚未啟用。'), name)
        self.circle = QLabel('協力圈：尚未設定  ｜  DesktopWoof 期限交換於後續版本提供')
        self.circle.setObjectName('circle')
        layout.addWidget(self.circle)
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
        self.autosave.setInterval(1200)
        self.autosave.timeout.connect(lambda: self.save(auto=True))
        self.tabs.currentChanged.connect(self.update_actions)
        self.basic_tabs.currentChanged.connect(self.update_actions)
        self.calendar_tabs.currentChanged.connect(self.update_actions)
        self.update_actions()

    def button(self, text, handler):
        button = QPushButton(text)
        button.setFixedSize(108, 34)
        button.clicked.connect(handler)
        return button

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
        state = QPushButton('解鎖編輯')
        state.clicked.connect(lambda: self.toggle_lock(key))
        self.locks[key] = state
        row.addWidget(state)
        row.addWidget(QLabel('預設鎖定  ·  編輯後自動儲存  ·  每頁可回復 10 次'))
        row.addStretch()
        layout.addLayout(row)
        content = QWidget()
        self.editors[key] = content
        layout.addWidget(content, 1)
        return outer, content

    def build_basic(self):
        outer, content = self.edit_page('basic')
        self.basic_tabs.addTab(outer, '基本資料')
        layout = QVBoxLayout(content)
        group = QGroupBox('工程識別與契約資料')
        form = QGridLayout(group)
        names = [('name', '工程名稱'), ('number', '工程編號'), ('contract', '採購契約號'),
                 ('contractor', '承攬商'), ('award', '決標日期'), ('signed', '簽約日期'),
                 ('start', '開工日期'), ('finish', '預定竣工'), ('days', '契約工期'), ('mode', '工期模式')]
        for index, (key, label) in enumerate(names):
            field = QComboBox() if key == 'mode' else QLineEdit()
            if key == 'mode':
                field.addItems(['工作日', '日曆天'])
                field.currentTextChanged.connect(self.capture_basic)
            else:
                field.setMaxLength(300 if key == 'name' else 120)
                field.textEdited.connect(self.basic_edited)
                field.editingFinished.connect(self.capture_basic)
                if key in ('award', 'signed', 'start', 'finish'):
                    field.setPlaceholderText('YYYY-MM-DD（可留白）')
            self.fields[key] = field
            width = field.fontMetrics().horizontalAdvance('工') * (40 if key == 'name' else 20) + 24
            field.setMinimumWidth(width)
            if index == 0:
                form.addWidget(QLabel(label), 0, 0)
                form.addWidget(field, 0, 1, 1, 3)
            else:
                row, col = 1 + (index - 1) // 2, ((index - 1) % 2) * 2
                form.addWidget(QLabel(label), row, col)
                form.addWidget(field, row, col + 1)
        form.setVerticalSpacing(18)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(group)
        layout.addWidget(scroll)
        note = QLabel('日期可留白；有填寫時請使用西元 YYYY-MM-DD。\n工期由開工日當天起算；預定竣工保留手動填寫，計算結果不自動覆寫。')
        note.setWordWrap(True)
        layout.addWidget(note)

    def basic_edited(self):
        self.autosave.start()
        self.message.setText('尚有變更；輸入完成後自動儲存')

    def capture_basic(self):
        if self.loading or not self.session or 'basic' not in self.session.unlocked:
            return
        value = {key: widget.currentText() if isinstance(widget, QComboBox) else widget.text()
                 for key, widget in self.fields.items()}
        self.session.change('basic', value)
        self.changed()

    def build_table(self, key, title):
        outer, content = self.edit_page(key)
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
        table = QTableWidget(0, 4 if key == 'weather' else 2)
        table.setHorizontalHeaderLabels(['日期', '上午扣除值', '下午扣除值', '備註（-1 不計）'] if key == 'weather' else ['日期', '名稱／說明'])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.itemChanged.connect(lambda _: self.capture_table(key))
        self.tables[key] = table
        layout.addWidget(table)
        text = '日期 YYYY-MM-DD；同一表日期不可重複。'
        if key == 'weather':
            text += ' 沿用舊規則：上午 > 0 扣 1 日，下午 > 0 扣 0.5 日；上午 ≥ 1 合計扣 1 日。'
        elif key in ('holidays', 'railway'):
            text += ' 本表列入的日期全部不計工期。'
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.calendar_tabs.addTab(outer, title)

    def capture_table(self, key):
        if self.loading or not self.session or key not in self.session.unlocked:
            return
        table = self.tables[key]
        value = [[table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())]
                 for r in range(table.rowCount())]
        self.session.change(key, value)
        self.changed()

    def add_row(self, key):
        if not self.session or key not in self.session.unlocked:
            return
        rows = deepcopy(self.session.pages[key])
        rows.append([self.calendar.selectedDate().toString('yyyy-MM-dd'), '0', '0', ''] if key == 'weather'
                    else [self.calendar.selectedDate().toString('yyyy-MM-dd'), ''])
        self.session.change(key, rows)
        self.populate_table(key)
        self.changed()

    def remove_row(self, key):
        if not self.session or key not in self.session.unlocked:
            return
        selected = {item.row() for item in self.tables[key].selectedItems()}
        self.session.change(key, [r for i, r in enumerate(self.session.pages[key]) if i not in selected])
        self.populate_table(key)
        self.changed()

    def build_calendar(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        previous, following = QPushButton('◀ 上一月'), QPushButton('下一月 ▶')
        previous.clicked.connect(lambda: self.move_month(-1))
        following.clicked.connect(lambda: self.move_month(1))
        self.month_label = QLabel()
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.addWidget(previous)
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
        layout.addWidget(QLabel('綠色＝計入工期　灰色＝不計工期　｜　選擇日期可查看計算原因'))
        self.calendar_tabs.addTab(page, '施工日曆')
        self.refresh_calendar()

    def move_month(self, delta):
        shown = QDate(self.calendar.yearShown(), self.calendar.monthShown(), 1).addMonths(delta)
        self.calendar.setCurrentPage(shown.year(), shown.month())

    def refresh_calendar(self, *_):
        year, month = self.calendar.yearShown(), self.calendar.monthShown()
        self.month_label.setText(f'{year} 年 {month} 月')
        if not self.session:
            return
        try:
            context = self.session.calendar()
            total = 0
            for day in range(1, calendar.monthrange(year, month)[1] + 1):
                value, reason = calculate_day(date(year, month, day), context)
                total += value
                fmt = QTextCharFormat()
                fmt.setBackground(QColor('#e2efdd' if value else '#eeeae1'))
                fmt.setToolTip(f'{value} 日：{reason}')
                self.calendar.setDateTextFormat(QDate(year, month, day), fmt)
            chosen = self.calendar.selectedDate().toPython()
            value, reason = calculate_day(chosen, context)
            text = f'本月可計工期：{total} 日　｜　{chosen}：{value} 日，{reason}'
            basic = self.session.pages['basic']
            if basic['start']:
                start = date.fromisoformat(basic['start'])
                finish = calculate_finish(start, basic['days'], context)
                text += f'\n依目前規則推算竣工：{finish}　｜　開工至選取日累計：{count_workdays(start, chosen, context)} 日'
            self.calendar_summary.setText(text)
        except (ValueError, ArithmeticError) as exc:
            self.calendar_summary.setText(f'請修正輸入後再計算：{exc}')

    def changed(self):
        if self.session.dirty():
            self.message.setText('尚有變更，等待自動儲存…')
            self.autosave.start()
        self.update_actions()

    def current_page(self):
        if self.tabs.currentIndex() == 0 and self.basic_tabs.currentIndex() == 0:
            return 'basic'
        if self.tabs.currentIndex() == 1 and self.calendar_tabs.currentIndex() < 4:
            return ['holidays', 'makeup', 'railway', 'weather'][self.calendar_tabs.currentIndex()]
        return None

    def update_actions(self, *_):
        ready = self.session is not None and self.future is None
        for key, widget in self.editors.items():
            widget.setEnabled(ready and key in self.session.unlocked)
            self.locks[key].setEnabled(ready)
            self.locks[key].setText('鎖定此頁' if ready and key in self.session.unlocked else '解鎖編輯')
        key = self.current_page()
        self.undo_button.setEnabled(bool(ready and key and key in self.session.unlocked and self.session.history[key]))
        self.save_button.setEnabled(ready)

    def toggle_lock(self, key):
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
            self.populate()
            self.changed()

    def populate_table(self, key):
        self.loading = True
        table = self.tables[key]
        table.setRowCount(len(self.session.pages[key]))
        for r, row in enumerate(self.session.pages[key]):
            for c, value in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(str(value)))
        self.loading = False

    def populate(self):
        self.loading = True
        for key, widget in self.fields.items():
            value = self.session.pages['basic'][key]
            if isinstance(widget, QComboBox):
                widget.setCurrentText(value)
            else:
                widget.setText(value)
        self.loading = False
        for key in self.tables:
            self.populate_table(key)
        self.refresh_calendar()
        self.update_actions()

    def io(self, operation, success):
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
        except Exception as exc:
            logging.exception('Project operation failed')
            self.message.setText(f'操作失敗：{exc}；目前編輯內容仍保留')
            QMessageBox.warning(self, '操作未完成', str(exc))
        self.update_actions()

    def save(self, auto=False, after=None):
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
            clock = datetime.fromisoformat(stamp).astimezone().strftime('%H:%M:%S')
            self.message.setText(f'{"自動儲存" if auto else "已儲存"}：{clock}')
            self.refresh_calendar()
            if after:
                after()
        self.io(lambda: store.save(dirty, revision), done)

    def adopt(self, payload):
        session = EditSession(payload['pages'])
        session.validate()
        self.path = payload['path']
        self.store = ProjectStore(self.path)
        self.session = session
        self.revision = int(payload['metadata']['revision'])
        self.settings.setValue('last_project', self.path)
        self.db_label.setText('資料庫：' + Path(self.path).name)
        self.db_label.setToolTip(self.path)
        self.message.setText('工程已開啟；每頁預設鎖定')
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())
        self.populate()

    def open_path(self, path):
        self.save(after=lambda: self.io(lambda: ProjectStore(path).load(), self.adopt))

    def choose_project(self):
        path, _ = QFileDialog.getOpenFileName(self, '選擇工程資料庫', str(Path(self.path).parent) if self.path else '', '工程資料庫 (*.db *.sqlite);;所有檔案 (*)')
        if path:
            self.open_path(path)

    def new_project(self):
        path, _ = QFileDialog.getSaveFileName(self, '新增工程案（每工程獨立資料庫）', 'TRAADuoDuo.db', 'SQLite (*.db)')
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
        for title, action in [('選擇資料庫', self.choose_project), ('新增資料庫／工程案', self.new_project), ('備份資料庫', self.backup)]:
            button = QPushButton(title)
            button.setEnabled(bool(self.store) or title != '備份資料庫')
            button.clicked.connect(lambda checked=False, action=action: (dialog.accept(), action()))
            box.addWidget(button)
        dialog.resize(440, 200)
        dialog.exec()

    def about(self):
        box = QMessageBox(self)
        box.setWindowTitle('關於 TRAADuoDuo')
        box.setIconPixmap(QPixmap(str(ROOT / 'assets/app_icon.png')).scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        box.setText(f'{APP_NAME}\nTRAADuoDuo {VERSION}\n首版：案件資料、施工日曆與核心服務\n正式圖示由使用者提供')
        box.exec()

    def closeEvent(self, event):
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
        self.pool.shutdown(wait=False)
        event.accept()
