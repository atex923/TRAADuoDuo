"""Windows title controls: explicit tray button, normal minimize, maximize, close."""
from PySide6.QtCore import Qt,QEvent
from PySide6.QtWidgets import QWidget,QHBoxLayout,QLabel,QPushButton,QApplication

class WindowTitleBar(QWidget):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.setObjectName('windowsTitleBar')
        self.setStyleSheet('#windowsTitleBar {background:#E5EEF5;} QPushButton {min-width:38px;max-width:38px;padding:0px;font-size:16pt;}')
        row=QHBoxLayout(self);row.setContentsMargins(8,0,0,0);row.setSpacing(0)
        title=QLabel(window.windowTitle());title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);row.addWidget(title,1)
        window.windowTitleChanged.connect(title.setText)
        self.buttons=[]
        for text,name,action in [('_','縮小到系統匣',window.minimize_to_tray),('─','最小化到工具列',window.showMinimized),('□','最大化／還原',self.toggle_maximized),('×','關閉',window.close)]:
            button=QPushButton(text);button.setObjectName(name);button.setAccessibleName(name);button.setToolTip(name);button.setFixedSize(38,32);button.clicked.connect(action);row.addWidget(button);self.buttons.append(button)
        self.setFixedHeight(32)
        QApplication.instance().installEventFilter(self)

    def toggle_maximized(self):
        if self.window.isMaximized():self.window.showNormal()
        else:self.window.showMaximized()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.window.windowHandle():self.window.windowHandle().startSystemMove();event.accept()
        else:super().mousePressEvent(event)

    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.toggle_maximized();event.accept()
        else:super().mouseDoubleClickEvent(event)

    def eventFilter(self,obj,event):
        w=self.window
        if event.type()!=QEvent.Type.MouseButtonPress or not isinstance(obj,QWidget) or (obj is not w and not w.isAncestorOf(obj)) or w.isMaximized():return False
        if event.button()!=Qt.MouseButton.LeftButton:return False
        p=w.mapFromGlobal(event.globalPosition().toPoint());edge=Qt.Edge(0)
        if p.x()<5:edge|=Qt.Edge.LeftEdge
        elif p.x()>=w.width()-5:edge|=Qt.Edge.RightEdge
        if p.y()<5:edge|=Qt.Edge.TopEdge
        elif p.y()>=w.height()-5:edge|=Qt.Edge.BottomEdge
        return bool(edge and w.windowHandle() and w.windowHandle().startSystemResize(edge))
