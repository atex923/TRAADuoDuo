"""Idle background writes preserve editors and acknowledge only their snapshot."""
from copy import deepcopy
import time
from PySide6.QtCore import QObject,QEvent
from PySide6.QtWidgets import QApplication,QWidget,QAbstractItemView,QLineEdit

class InputActivity(QObject):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.composing=False;self.last_input=time.monotonic()
    def eventFilter(self,obj,event):
        w=self.window
        if not isinstance(obj,QWidget) or not w.isAncestorOf(obj):return False
        if obj.property('viewOnlyInput'):return False
        if event.type()==QEvent.Type.InputMethod:
            self.composing=bool(event.preeditString());self.touch()
        elif event.type() in (QEvent.Type.KeyPress,QEvent.Type.Drop):self.touch()
        return False
    def touch(self):
        self.last_input=time.monotonic()
        if self.window.session:self.window.autosave.start(60000)
    def blocked(self):
        if self.composing or QApplication.activeModalWidget():return True
        obj=QApplication.focusWidget()
        while obj and obj is not self.window:
            if isinstance(obj,QAbstractItemView) and obj.state()==QAbstractItemView.State.EditingState:return True
            obj=obj.parentWidget()
        return False

class IdleSaving:
    def idle_timeout(self):
        if self.input_activity.blocked():self.autosave.start();return
        elapsed=time.monotonic()-self.input_activity.last_input
        if elapsed<60:self.autosave.start(max(1,round((60-elapsed)*1000)));return
        self.start_background_save()
    def start_background_save(self):
        if not self.session or self.future is not None or self._auto_job is not None:return
        if self.input_activity.blocked():self.autosave.start();return
        focus=QApplication.focusWidget();state=(focus.text(),focus.cursorPosition(),focus.selectionStart(),len(focus.selectedText())) if isinstance(focus,QLineEdit) else None
        self.capture_basic();self.autosave.stop()
        if state and focus.text()==state[0]:
            if state[2]>=0:focus.setSelection(state[2],state[3])
            else:focus.setCursorPosition(state[1])
        try:self.session.validate()
        except (ValueError,ArithmeticError,KeyError) as exc:self.message.setText('尚未自動儲存：'+str(exc));return
        if not self.session.dirty():return
        snapshot=deepcopy(self.session.pages);store=self.store;revision=self.revision
        self._auto_job=(self.pool.submit(store.save,snapshot,revision),store,snapshot,self.session)
        self.message.setText('背景儲存中…可繼續輸入')
    def poll_background_save(self):
        if self._auto_job is None or not self._auto_job[0].done():return
        future,store,snapshot,session=self._auto_job;self._auto_job=None
        try:
            revision,stamp=future.result()
            if self.session is session:
                self.revision=revision;session.saved=snapshot
                self.message.setText('自動儲存完成；另有新變更待存' if session.dirty() else '自動儲存完成')
                if session.dirty():self.autosave.start()
        except Exception as exc:self.message.setText('自動儲存失敗，草稿仍保留：'+str(exc))
        self.update_actions()
        waiting,self._auto_after=self._auto_after,[]
        for action in waiting:action()
