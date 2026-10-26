"""Five isolated offscreen runs; compare version paths without opening user DBs."""
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys

script = '''
import json,sys,tempfile,time
from pathlib import Path
start=time.perf_counter()
sys.path.insert(0,sys.argv[1])
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from traaduoduo.ui import Window
from traaduoduo.store import ProjectStore
qt=time.perf_counter()
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    settings=QSettings(str(Path(d)/'qa.ini'),QSettings.Format.IniFormat)
    build=time.perf_counter()
    w=Window(settings)
    w.show()
    app.processEvents()
    shown=time.perf_counter()
    count=int(sys.argv[2])
    if count:
        payload=ProjectStore.create(Path(d)/'qa.db','QA工程')
        store=ProjectStore(payload['path'],payload['metadata']['project_id'])
        for index in range(count-1):
            store.add_project('工程'+str(index+2))
        basic=dict(payload['pages']['basic'], start='2026-01-01',days='30000' if count==1 else '100')
        store.save({'basic':basic},0)
    ready=time.perf_counter()
    if count:
        w.adopt(store.open_result())
    app.processEvents()
    adopted=time.perf_counter()
    w.close()
    print(json.dumps(dict(import_ms=(qt-start)*1000,window_ms=(shown-build)*1000,open_ms=(adopted-ready)*1000)))
'''
for path in sys.argv[1:]:
    for count in (0,1,100):
        rows=[]
        for _ in range(5):
            result=subprocess.run([sys.executable,'-c',script,str(Path(path).resolve()),str(count)],
                env=dict(os.environ,QT_QPA_PLATFORM='offscreen',PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,check=True)
            rows.append(json.loads(result.stdout.strip().splitlines()[-1]))
        print(json.dumps(dict(version=Path(path).resolve().name,projects=count,runs=5,median_ms={k:round(statistics.median(r[k] for r in rows),2) for k in rows[0]},max_ms={k:round(max(r[k] for r in rows),2) for k in rows[0]}),ensure_ascii=False))
