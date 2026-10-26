"""Continuous read-only PDF pages; highlights/bookmarks live outside the PDF."""
from PySide6.QtCore import Qt, QSize, QRectF, Signal, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QScrollArea,QLabel,QPushButton,QComboBox,QInputDialog
from PySide6.QtPdf import QPdfDocument

class PdfPage(QLabel):
    marked=Signal(int,object)
    def __init__(self,page,rectangles):
        super().__init__(); self.page=page; self.rectangles=rectangles; self.anchor=None; self.marking=False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('background:white;')
    def mousePressEvent(self,event):
        if self.marking and event.button()==Qt.MouseButton.LeftButton: self.anchor=event.position()
        else: super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        if self.anchor is not None:
            rect=QRectF(self.anchor,event.position()).normalized().intersected(QRectF(self.rect()))
            self.anchor=None
            if rect.width()>4 and rect.height()>4:
                normalized=[rect.x()/self.width(),rect.y()/self.height(),rect.width()/self.width(),rect.height()/self.height()]
                self.marked.emit(self.page,normalized)
        else: super().mouseReleaseEvent(event)
    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(255,220,0,90))
        for x,y,w,h in self.rectangles: painter.drawRect(QRectF(x*self.width(),y*self.height(),w*self.width(),h*self.height()))

class PdfReader(QWidget):
    annotated=Signal(object)
    positionChanged=Signal(int,float)
    def __init__(self):
        super().__init__(); self.doc=QPdfDocument(self); self.notes=dict(bookmarks=[],highlights=[]); self.can_edit=False
        self.pages=[]; self.factor=1.; self.loaded=set(); self.marking=False
        layout=QVBoxLayout(self); controls=QHBoxLayout()
        self.zoom=QComboBox(); self.zoom.addItems(['60%','80%','100%','125%','150%']); self.zoom.setCurrentText('100%')
        self.zoom.currentTextChanged.connect(self.change_zoom); controls.addWidget(self.zoom)
        self.bookmarks=QComboBox(); self.bookmarks.addItem('書籤／跳頁'); self.bookmarks.activated.connect(self.goto_bookmark); controls.addWidget(self.bookmarks,1)
        self.bookmark=QPushButton('加入書籤'); self.bookmark.clicked.connect(self.add_bookmark); controls.addWidget(self.bookmark)
        self.highlight=QPushButton('重點標記'); self.highlight.setCheckable(True); self.highlight.toggled.connect(self.toggle_marking); controls.addWidget(self.highlight)
        layout.addLayout(controls); self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); layout.addWidget(self.scroll)
        self.body=QWidget(); self.stack=QVBoxLayout(self.body); self.stack.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.scroll.setWidget(self.body); self.scroll.verticalScrollBar().valueChanged.connect(self.visible_pages)
    def load(self,path,notes=None,page=0,zoom=1.):
        self.clear(); self.notes=notes or dict(bookmarks=[],highlights=[]); self.factor=zoom
        error=self.doc.load(str(path))
        if error!=QPdfDocument.Error.None_: raise ValueError('PDF 無法載入（可能損壞、加密或格式不支援）')
        self.zoom.blockSignals(True); self.zoom.setCurrentText(str(round(zoom*100))+'%'); self.zoom.blockSignals(False)
        self.build(); self.refresh_bookmarks(); QTimer.singleShot(0,lambda:self.goto(page))
    def clear(self):
        for page in self.pages: self.stack.removeWidget(page); page.deleteLater()
        self.pages=[]; self.loaded=set(); self.doc.close()
    def build(self):
        for page in self.pages: self.stack.removeWidget(page); page.deleteLater()
        self.pages=[]; self.loaded=set()
        for i in range(self.doc.pageCount()):
            marks=[m['rect'] for m in self.notes.get('highlights',[]) if m['page']==i]
            page=PdfPage(i,marks); size=self.doc.pagePointSize(i)*self.factor
            page.setFixedSize(max(1,round(size.width())),max(1,round(size.height())))
            page.marking=self.marking and self.can_edit; page.marked.connect(self.add_highlight)
            self.pages.append(page); self.stack.addWidget(page)
        QTimer.singleShot(0,self.visible_pages)
    def current_page(self):
        y=self.scroll.verticalScrollBar().value()
        return max(0,next((i for i,p in enumerate(self.pages) if p.y()+p.height()>y),len(self.pages)-1))
    def visible_pages(self,*_):
        if not self.pages:return
        y=self.scroll.verticalScrollBar().value(); bottom=y+self.scroll.viewport().height()
        for i,page in enumerate(self.pages):
            if page.y()+page.height()<y-500 or page.y()>bottom+500:
                if i in self.loaded: page.clear(); self.loaded.remove(i)
            elif i not in self.loaded:
                page.setPixmap(QPixmap.fromImage(self.doc.render(i,page.size()))); self.loaded.add(i)
        self.positionChanged.emit(self.current_page(),self.factor)
    def goto(self,page):
        if self.pages:
            self.scroll.verticalScrollBar().setValue(self.pages[max(0,min(int(page),len(self.pages)-1))].y()); self.visible_pages()
    def change_zoom(self,text):
        page=self.current_page(); self.factor=float(text.strip('%'))/100; self.build(); QTimer.singleShot(0,lambda:self.goto(page))
    def set_editable(self,value):
        self.can_edit=value; self.bookmark.setEnabled(value); self.highlight.setEnabled(value)
        for page in self.pages: page.marking=self.marking and value
    def toggle_marking(self,value):
        self.marking=value
        for page in self.pages: page.marking=value and self.can_edit
    def refresh_bookmarks(self):
        self.bookmarks.clear(); self.bookmarks.addItem('書籤／跳頁',None)
        for mark in self.notes.get('bookmarks',[]): self.bookmarks.addItem(f"第 {mark['page']+1} 頁　{mark['name']}",mark['page'])
    def goto_bookmark(self,index):
        page=self.bookmarks.itemData(index)
        if page is not None:self.goto(page)
    def add_bookmark(self):
        if not self.can_edit:return
        name,ok=QInputDialog.getText(self,'新增 PDF 書籤','書籤名稱')
        if ok and name.strip():
            self.notes.setdefault('bookmarks',[]).append(dict(page=self.current_page(),name=name.strip())); self.refresh_bookmarks(); self.annotated.emit(self.notes)
    def add_highlight(self,page,rect):
        if not self.can_edit:return
        self.notes.setdefault('highlights',[]).append(dict(page=page,rect=rect)); self.pages[page].rectangles.append(rect); self.pages[page].update(); self.annotated.emit(self.notes)
