import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView
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
        while self.window.future is not None and time.monotonic() < deadline:
            APP.processEvents()
            QTest.qWait(20)
        self.assertIsNone(self.window.future)

    def test_shell_lock_autosave_and_undo(self):
        w = self.window
        self.assertEqual(w.tabs.count(), 6)
        self.assertEqual(w.basic_tabs.count(), 4)
        self.assertEqual(w.calendar_tabs.count(), 5)
        self.assertFalse(w.fields['name'].isEnabled())
        self.assertFalse(w.print_button.isEnabled())
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
        w.calendar_tabs.setCurrentIndex(4)
        year, month = w.calendar.yearShown(), w.calendar.monthShown()
        w.move_month(1)
        QTest.keyClick(w.calendar.findChild(QAbstractItemView), Qt.Key.Key_Up)
        self.assertEqual((w.calendar.yearShown(), w.calendar.monthShown()), (year, month))
        self.assertFalse(w.session.dirty())
        w.toggle_lock('holidays')
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
        self.wait_io()
        self.assertEqual(ProjectStore(self.path).load()['pages']['basic']['number'], 'AUTO-123')

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
