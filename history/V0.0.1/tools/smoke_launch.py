"""Exercise the real entry point with isolated settings/logs and timed close."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QSettings, QTimer
from traaduoduo.ui import Window
from traaduoduo.app import main

with tempfile.TemporaryDirectory() as directory:
    class SmokeWindow(Window):
        def __init__(self):
            super().__init__(QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat))

        def show(self):
            super().show()
            QTimer.singleShot(400, self.close)

    with patch('traaduoduo.app.Window', SmokeWindow), patch('traaduoduo.app.QStandardPaths.writableLocation', return_value=directory):
        result = main()
        assert result == 0
print('Real entry point: launched and closed successfully (offscreen).')
