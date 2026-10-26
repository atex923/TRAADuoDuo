import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView, QDialog, QDialogButtonBox, QLineEdit, QTableWidget, QPushButton, QListWidget
from traaduoduo.ui import Window
from traaduoduo.store import ProjectStore

APP = QApplication.instance() or QApplication([])


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'project.db'
        self.window = Window(QSettings(str(Path(self.temp.name) / 'settings.ini'), QSettings.Format.IniFormat))
        self.window.adopt(ProjectStore.create(self.path, 'UI 測試工程'))
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.autosave.stop()
        self.wait_io()
        self.window.session.saved = self.window.session.pages.copy()
        self.window.close()
        self.temp.cleanup()

    def wait_io(self):
        deadline = time.monotonic() + 5
        while (self.window.future is not None or self.window._auto_job is not None) and time.monotonic() < deadline:
            APP.processEvents()
            QTest.qWait(20)
        self.assertIsNone(self.window.future)
        self.assertIsNone(self.window._auto_job)

    def test_shell_lock_autosave_and_undo(self):
        w = self.window
        self.assertEqual(w.tabs.count(), 7)
        self.assertEqual(w.basic_tabs.count(), 5)
        self.assertEqual(w.calendar_tabs.count(), 3)
        self.assertTrue(w.fields['name'].isReadOnly())
        self.assertTrue(w.print_button.isEnabled())
        self.assertFalse(w.windowIcon().isNull())
        w.toggle_lock('basic')
        w.fields['name'].setText('已修改工程')
        w.capture_basic()
        w.save(auto=True)
        self.wait_io()
        self.assertEqual(ProjectStore(self.path).load()['pages']['basic']['name'], '已修改工程')
        self.assertFalse(w.session.dirty())
        w.undo()
        self.assertEqual(w.fields['name'].text(), 'UI 測試工程')
        w.save()
        self.wait_io()

    def test_calendar_navigation_and_table_edit(self):
        w = self.window
        w.tabs.setCurrentIndex(1)
        w.calendar_tabs.setCurrentWidget(w.calendar_page)
        year, month = w.calendar.yearShown(), w.calendar.monthShown()
        w.move_month(1)
        QTest.keyClick(w.calendar.findChild(QAbstractItemView), Qt.Key.Key_Up)
        self.assertEqual((w.calendar.yearShown(), w.calendar.monthShown()), (year, month))
        self.assertFalse(w.session.dirty())
        w.toggle_lock('holidays')
        def confirm_date():
            dialog=next(d for d in w.findChildren(QDialog) if d.isVisible())
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        QTimer.singleShot(0,confirm_date)
        w.add_row('holidays')
        w.save()
        self.wait_io()
        self.assertEqual(len(ProjectStore(self.path).load()['pages']['holidays']), 1)
        self.assertNotIn('weather', w.session.unlocked)

    def test_switch_flushes_and_resets_locks(self):
        other = Path(self.temp.name) / 'other.db'
        ProjectStore.create(other, '第二工程')
        w = self.window
        w.toggle_lock('basic')
        w.fields['name'].setText('切換前資料')
        w.capture_basic()
        w.open_path(other)
        self.wait_io()
        self.assertEqual(w.fields['name'].text(), '第二工程')
        self.assertFalse(w.session.unlocked)
        self.assertEqual(ProjectStore(self.path).load()['pages']['basic']['name'], '切換前資料')

    def test_real_timer_autosaves_typing(self):
        w = self.window
        w.toggle_lock('basic')
        w.fields['number'].setFocus()
        QTest.keyClicks(w.fields['number'], 'AUTO-123')
        QTest.qWait(1400)
        self.assertEqual(ProjectStore(self.path).load()['pages']['basic']['number'],'')
        w.input_activity.last_input-=60
        w.idle_timeout()
        self.wait_io()
        self.assertEqual(ProjectStore(self.path).load()['pages']['basic']['number'], 'AUTO-123')

    def test_unified_switch_save_failure_and_reopen(self):
        w = self.window
        second = w.store.add_project('統一乙工程')['metadata']['project_id']
        first = w.store.project_id
        w.toggle_lock('basic')
        w.fields['name'].setText('統一甲修改')
        w.switch_project(second)
        self.wait_io()
        self.assertEqual(w.fields['name'].text(), '統一乙工程')
        self.assertFalse(w.session.unlocked)
        self.assertEqual(ProjectStore(self.path, first).load()['pages']['basic']['name'], '統一甲修改')
        w.toggle_lock('basic')
        w.fields['name'].setText('未儲存乙')
        with patch.object(w.store, 'save', side_effect=OSError('disk full')), patch('traaduoduo.ui.QMessageBox.warning'), self.assertLogs(level='ERROR'):
            w.switch_project(first)
            self.wait_io()
        self.assertEqual(w.store.project_id, second)
        self.assertTrue(w.session.dirty())
        w.save()
        self.wait_io()
        w.open_path(str(self.path))
        self.wait_io()
        self.assertEqual(w.store.project_id, second)

    def test_archive_is_readonly(self):
        w = self.window
        w.store.archive(w.store.project_id)
        w.adopt(w.store.load())
        self.assertFalse(w.locks['basic'].isEnabled())
        self.assertTrue(w.fields['name'].isReadOnly())

    def test_compact_header_clicks_and_layer_visibility(self):
        w = self.window
        self.assertEqual(w.primary_tabs.count(),7)
        self.assertEqual(w.secondary_tabs.count(),5)
        self.assertTrue(w.tabs.tabBar().isHidden())
        self.assertTrue(w.basic_tabs.tabBar().isHidden())
        self.assertTrue(w.calendar_tabs.tabBar().isHidden())
        QTest.mouseClick(w.primary_tabs,Qt.MouseButton.LeftButton, pos=w.primary_tabs.tabRect(1).center())
        self.assertEqual(w.tabs.currentIndex(),1)
        self.assertEqual(w.secondary_tabs.count(),3)
        QTest.mouseClick(w.secondary_tabs,Qt.MouseButton.LeftButton,pos=w.secondary_tabs.tabRect(1).center())
        self.assertEqual(w.calendar_tabs.currentIndex(),1)
        self.assertEqual(w.current_page(),'weather')
        w.tabs.setCurrentIndex(3)
        self.assertFalse(w.secondary_tabs.isHidden())
        self.assertEqual(w.secondary_tabs.count(),4)
        self.assertFalse(w.tab_divider.isHidden())
        w.tabs.setCurrentIndex(4)
        self.assertFalse(w.secondary_tabs.isHidden())
        self.assertEqual(w.secondary_tabs.count(),2)
        w.primary_tabs.setCurrentIndex(1)
        self.assertFalse(w.secondary_tabs.isHidden())
        self.assertEqual(w.secondary_tabs.currentIndex(),1)

    def test_bottom_toolbar_and_narrow_window_bounds(self):
        w = self.window
        w.resize(860,650)
        APP.processEvents()
        self.assertLessEqual(w.save_button.height(),28)
        self.assertLessEqual(w.db_button.height(),28)
        self.assertLessEqual(w.primary_tabs.height(),32)
        self.assertGreater(w.bottom_groups.y(),w.tabs.y()+w.tabs.height())
        self.assertEqual(w.db_button.parent(),w.database_toolbar)
        self.assertGreaterEqual(w.primary_tabs.width(),100)
        self.assertGreaterEqual(w.secondary_tabs.width(),100)
        self.assertLessEqual(w.secondary_tabs.geometry().right(),w.tab_header.width())
        self.assertLessEqual(w.database_toolbar.geometry().right(),w.body.width())
        self.assertLess(w.secondary_tabs.x()-w.primary_tabs.geometry().right(),40)

    def test_cold_open_legacy_routes_to_preview_and_creates_library(self):
        from test_unified import UnifiedTests
        fixture = UnifiedTests('test_shared_database_isolation_and_revision')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source = fixture.legacy()
        before = source.read_bytes()
        w = self.window
        w.close()
        self.window = w = Window(QSettings(str(Path(self.temp.name)/'cold.ini'), QSettings.Format.IniFormat))
        w.show()
        self.assertIsNone(w.store)
        with patch.object(w,'show_import') as preview:
            w.open_path(source)
            self.wait_io()
        self.assertEqual(preview.call_count, 1)
        target = Path(self.temp.name)/'converted.db'
        def confirm():
            dialog = w.findChild(QDialog)
            next(b for b in dialog.findChildren(QPushButton) if b.text() == '備份並確認匯入選取工程').click()
        with patch('traaduoduo.ui.QFileDialog.getSaveFileName', return_value=(str(target),'')), patch('traaduoduo.ui.QMessageBox.information'):
            QTimer.singleShot(0,confirm)
            w.show_import(preview.call_args.args[0])
            self.wait_io()
        self.assertEqual(len(w.store.list_projects()), 2)
        self.assertEqual(w.project_selector.count(), 2)
        self.assertEqual(source.read_bytes(),before)
        other = 1 - w.project_selector.currentIndex()
        w.project_selector.activated.emit(other)
        self.wait_io()
        self.assertEqual(w.store.project_id,w.project_selector.itemData(other))

    def test_empty_library_open_and_create_project(self):
        target = Path(self.temp.name)/'empty.db'
        ProjectStore.create_library(target)
        w = self.window
        w.open_path(target)
        self.wait_io()
        self.assertIsNone(w.session)
        with patch('traaduoduo.ui.QInputDialog.getText',return_value=('新增實測工程',True)):
            w.new_project()
            self.wait_io()
        self.assertEqual(w.fields['name'].text(),'新增實測工程')
        self.assertEqual(w.project_selector.count(),1)

    def test_overview_search_and_switch_button(self):
        w = self.window
        pid = w.store.add_project('搜尋目標工程')['metadata']['project_id']
        def click_dialog():
            dialog = w.findChild(QDialog)
            search = dialog.findChild(QLineEdit)
            table = dialog.findChild(QTableWidget)
            search.setText('搜尋目標')
            visible = [r for r in range(table.rowCount()) if not table.isRowHidden(r)]
            self.assertEqual(len(visible), 1)
            table.selectRow(visible[0])
            next(b for b in dialog.findChildren(QPushButton) if b.text() == '開啟工程').click()
        QTimer.singleShot(0, click_dialog)
        w.show_projects(w.store.list_projects())
        self.wait_io()
        self.assertEqual(w.store.project_id, pid)

    def test_import_preview_disables_invalid_and_imports_selection(self):
        from copy import deepcopy
        w = self.window
        pages = deepcopy(w.session.pages)
        pages['basic']['name'] = '匯入預覽工程'
        good = dict(pages=pages,source_key='ui-test-good',report=['有效'],raw={},errors=[])
        bad = dict(good,source_key='ui-test-bad',errors=['工期異常'])
        def click_dialog():
            dialog = w.findChild(QDialog)
            listing = dialog.findChild(QListWidget)
            self.assertFalse(listing.item(1).flags() & Qt.ItemFlag.ItemIsEnabled)
            self.assertEqual(len(listing.selectedItems()), 1)
            next(b for b in dialog.findChildren(QPushButton) if b.text() == '備份並確認匯入選取工程').click()
        with patch('traaduoduo.ui.QMessageBox.information'):
            QTimer.singleShot(0,click_dialog)
            w.show_import(dict(kind='測試來源',projects=[good,bad]))
            self.wait_io()
        self.assertEqual(w.fields['name'].text(), '匯入預覽工程')
        self.assertEqual(len(w.store.list_projects()), 2)

    def test_save_failure_keeps_draft_and_revision(self):
        w = self.window
        w.toggle_lock('basic')
        w.fields['name'].setText('失敗仍保留草稿')
        w.capture_basic()
        with patch.object(w.store, 'save', side_effect=OSError('disk full')), patch('traaduoduo.ui.QMessageBox.warning'), self.assertLogs(level='ERROR'):
            w.save()
            self.wait_io()
        self.assertTrue(w.session.dirty())
        self.assertEqual(w.revision, 0)
        self.assertEqual(w.fields['name'].text(), '失敗仍保留草稿')
        self.assertIn('操作失敗', w.message.text())
        self.assertEqual(ProjectStore(self.path).load()['pages']['basic']['name'], 'UI 測試工程')


if __name__ == '__main__':
    unittest.main()
