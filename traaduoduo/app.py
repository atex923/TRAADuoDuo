import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
from PySide6.QtCore import QTimer, QStandardPaths
from PySide6.QtWidgets import QApplication
from .ui import Window


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setOrganizationName('TRAADuoDuo')
    app.setApplicationName('TRAADuoDuo')
    directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(directory / 'app.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')])
    window = Window()
    window.show()
    last = args.project or window.settings.value('last_project', '')
    if last and Path(last).is_file():
        QTimer.singleShot(0, lambda: window.open_path(last))
    elif last:
        window.message.setText('上次資料庫不存在；請重新選擇或新增工程案')
    return app.exec()
