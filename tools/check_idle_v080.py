"""Real 60-second idle gate, isolated data and settings, no clock mocking."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,tempfile,time,json
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from traaduoduo.ui import Window
from traaduoduo.store import ProjectStore
from traaduoduo.instance import MacInstance
app=QApplication([])
with tempfile.TemporaryDirectory(prefix='traa-idle-') as directory:
    root=Path(directory);guard=MacInstance(root);assert guard.owner
    path=root/'test.db';payload=ProjectStore.create(path,'閒置儲存 QA');w=Window(QSettings(str(root/'settings.ini'),QSettings.Format.IniFormat));w.adopt(payload);w.show();app.processEvents();w.toggle_lock('basic');field=w.fields['number'];field.setFocus();QTest.keyClicks(field,'IDLE-60');start=time.monotonic();position=field.cursorPosition()
    QTest.qWait(59000);assert ProjectStore(path).load()['pages']['basic']['number']=='';print('59 seconds: no write',flush=True)
    QTest.qWait(3500)
    deadline=time.monotonic()+5
    while w._auto_job is not None and time.monotonic()<deadline:QTest.qWait(20)
    assert ProjectStore(path).load()['pages']['basic']['number']=='IDLE-60';assert field.hasFocus() and field.cursorPosition()==position and w.body.isEnabled()
    print(json.dumps(dict(elapsed_seconds=round(time.monotonic()-start,2),after_59_seconds='not saved',after_60_seconds='saved',focus_preserved=True,cursor_preserved=True),ensure_ascii=False),flush=True)
    w.session.saved=deepcopy(w.session.pages);w.close();guard.close()
