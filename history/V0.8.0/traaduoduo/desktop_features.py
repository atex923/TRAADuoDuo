"""Desktop equivalents of the shared About content and Windows-only tray."""
import sys
from PySide6.QtCore import Qt,QEvent,QTimer,QUrl
from PySide6.QtGui import QAction,QDesktopServices,QPixmap
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QDialogButtonBox,QSystemTrayIcon,QMenu
from . import APP_NAME,DISPLAY_VERSION,DESIGNER,FEEDBACK_EMAIL

class DesktopFeatures:
    def about_dialog(self):
        dialog=QDialog(self);dialog.setWindowTitle('關於');layout=QVBoxLayout(dialog)
        icon=QLabel();icon.setPixmap(self.windowIcon().pixmap(96,96));layout.addWidget(icon)
        for value in [APP_NAME,'TRAADuoDuo',DISPLAY_VERSION,'程式設計者：'+DESIGNER]:layout.addWidget(QLabel(value))
        feedback=QPushButton();row=QHBoxLayout(feedback);row.setContentsMargins(12,4,12,4)
        leading=QLabel('使用回饋信箱');trailing=QLabel(FEEDBACK_EMAIL)
        for label in (leading,trailing):label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        row.addWidget(leading);row.addStretch();row.addWidget(trailing)
        feedback.setAccessibleName('使用回饋信箱，'+FEEDBACK_EMAIL);feedback.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('mailto:'+FEEDBACK_EMAIL)));layout.addWidget(feedback)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.resize(600,360);return dialog
    def about(self):self.about_dialog().exec()
    def install_tray(self):
        self.tray=None
        if sys.platform!='win32' or not QSystemTrayIcon.isSystemTrayAvailable():return
        self.tray=QSystemTrayIcon(self.windowIcon(),self);self.tray.setToolTip(APP_NAME+' '+DISPLAY_VERSION);self.tray_menu=QMenu(self)
        self.tray_menu.addAction('顯示主視窗',self.restore_from_tray)
        self.tray_menu.addAction('儲存',lambda:self.save())
        self.tray_option=QAction('最小化到系統匣',self);self.tray_option.setCheckable(True);self.tray_option.setChecked(self.settings.value('windows/minimizeToTray',True,type=bool));self.tray_option.toggled.connect(lambda value:self.settings.setValue('windows/minimizeToTray',value));self.tray_menu.addAction(self.tray_option)
        self.tray_menu.addAction('結束程式',self.close);self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda reason:self.restore_from_tray() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None);self.tray.show()
    def restore_from_tray(self):self.showNormal();self.raise_();self.activateWindow()
    def changeEvent(self,event):
        super().changeEvent(event)
        tray=getattr(self,'tray',None)
        if event.type()==QEvent.Type.WindowStateChange and self.isMinimized() and tray and tray.isVisible() and self.tray_option.isChecked() and QSystemTrayIcon.isSystemTrayAvailable():QTimer.singleShot(0,self.hide)
