"""Render this program's UI using Qt, without accessing real projects."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QSettings, QDate
from PySide6.QtWidgets import QApplication
from traaduoduo.ui import Window, ROOT
from traaduoduo.store import ProjectStore

app = QApplication([])
target = ROOT / 'docs/screenshots'
target.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / '示範工程.db'
    payload = ProjectStore.create(path, '鐵路站區環境改善工程（示範）')
    basic = dict(payload['pages']['basic'], number='TR-DEMO-001', contract='DEMO-2026-001',
                 contractor='示範營造有限公司', start='2026-09-01', days='100')
    ProjectStore(path).save({'basic': basic, 'holidays': [['2026-09-25', '示範假期']],
                            'weather': [['2026-09-23', '0', '.5', '午後降雨']]}, 0)
    settings = QSettings(str(Path(directory) / 'preview.ini'), QSettings.Format.IniFormat)
    window = Window(settings)
    window.adopt(ProjectStore(path).load())
    window.show()
    app.processEvents()
    window.grab().save(str(target / 'main.png'))
    window.tabs.setCurrentIndex(1)
    window.calendar_tabs.setCurrentIndex(4)
    window.calendar.setSelectedDate(QDate(2026, 9, 23))
    app.processEvents()
    window.grab().save(str(target / 'calendar.png'))
    window.close()
print(target)
