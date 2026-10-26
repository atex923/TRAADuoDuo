"""Non-destructive link/Docstore lifecycle and verified portable backups."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import uuid
from zipfile import ZipFile, ZIP_DEFLATED
from .content_store import library_lock,verified_candidates,remember,check_cancel

def sha(path,cancel=None):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            check_cancel(cancel);h.update(block)
    return h.hexdigest()

def new_asset(path,category=''):
    path=Path(path).resolve()
    if not path.is_file(): raise ValueError('來源檔不存在或不是一般檔案')
    capture=''
    try:
        from PIL import Image
        with Image.open(path) as image:
            exif=image.getexif();capture=str(exif.get(36867) or exif.get_ifd(34665).get(36867) or '')
    except (ImportError,OSError,ValueError,KeyError,AttributeError):pass
    stat=path.stat()
    return dict(id=uuid.uuid4().hex,name=path.name,source=str(path),category=category,stock=False,managed='',sha256=sha(path),versions=[],note='',rotation=0,capture_date=capture,source_size=stat.st_size,source_mtime_ns=stat.st_mtime_ns)

def managed_path(database,relative):
    root=Path(database).resolve().parent/'Docstore'
    target=(Path(database).resolve().parent/relative).resolve()
    if not target.is_relative_to(root.resolve()): raise ValueError('庫存檔路徑超出 Docstore')
    return target

def available_path(database,row):
    if row.get('stock'):
        path=managed_path(database,row['managed'])
        if not path.is_file(): raise ValueError('庫存檔離線或遺失，請重新連結或還原備份')
        return path
    path=Path(row['source'])
    if not path.is_file(): raise ValueError('來源檔離線或遺失，請重新連結')
    return path

def inventory(database,project_id,key,row,cancel=None):
    source=Path(row['source']).resolve()
    if not source.is_file(): raise ValueError('來源離線，未建立庫存檔')
    check_cancel(cancel)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        library=conn.execute("SELECT value FROM metadata WHERE key='library_id'").fetchone()
        lid=library[0] if library else uuid.uuid4().hex
        if not library:
            conn.execute('INSERT INTO metadata VALUES(?,?)',('library_id',lid)); conn.commit()
        else:conn.commit()
    if any('/' in value or '\\' in value or value in ('.','..') for value in (lid,project_id,row['id'])): raise ValueError('檔案識別不合法')
    root=managed_path(database,str(Path('Docstore')/lid))
    with library_lock(root,cancel):
        stat=source.stat();before=sha(source,cancel)
        target,index,reused=verified_candidates(root,stat.st_size,before,sha,cancel)
        if target is None:
            target=root/'objects'/before[:2]/before/source.name
            # A corrupted existing object is preserved, never overwritten.
            if target.exists():target=target.parent/(uuid.uuid4().hex+'-'+source.name)
            target.parent.mkdir(parents=True,exist_ok=True)
            temp=target.with_name('.'+uuid.uuid4().hex+'.partial')
            try:
                with source.open('rb') as src,temp.open('xb') as out:
                    for block in iter(lambda:src.read(1024*1024),b''):
                        check_cancel(cancel);out.write(block)
                    out.flush();os.fsync(out.fileno())
                if sha(temp,cancel)!=before:raise ValueError('複製校驗失敗；未完成庫存')
                check_cancel(cancel)
                if sha(source,cancel)!=before:raise ValueError('來源在複製中變更；未完成庫存')
                os.replace(temp,target)
            finally:
                if temp.exists():temp.unlink()
        if sha(source,cancel)!=before:raise ValueError('來源在讀取中變更；未完成庫存')
        check_cancel(cancel);remember(root,index,before,target)
        relative=target.relative_to(Path(database).resolve().parent)
    result=deepcopy(row)
    if result.get('managed') and result['sha256']!=before:
        old=dict(path=result['managed'],sha256=result['sha256'])
        if old not in result['versions']:result['versions'].append(old)
    stat=source.stat();result.update(stock=True,managed=str(relative),sha256=before,source_size=stat.st_size,source_mtime_ns=stat.st_mtime_ns)
    result['inventory_reused']=reused
    return result

def portable_backup(store,destination):
    destination=Path(destination).resolve()
    if destination.exists(): raise ValueError('備份目標已存在，請使用新檔名')
    files={}; external=[]
    with store.connect() as conn:
        for pid,key,payload in conn.execute("SELECT project_id,page_id,payload FROM pages WHERE page_id IN ('documents','photos')"):
            for row in json.loads(payload)['rows']:
                if row.get('managed'): files[row['managed']]=row['sha256']
                for version in row.get('versions',[]): files[version['path']]=version['sha256']
                if not row.get('stock'): external.append(dict(project=pid,name=row['name'],path=row['source']))
    with tempfile.TemporaryDirectory(prefix='traa-backup-',dir=destination.parent) as directory:
        directory=Path(directory); database=directory/'library.db'; store.backup(database)
        manifest=dict(format='TRAADuoDuo-portable-1',database='library.db',files={'library.db':sha(database)},external_links=external)
        temp=directory/'archive.zip'
        with ZipFile(temp,'w',ZIP_DEFLATED) as archive:
            archive.write(database,'library.db')
            for relative,digest in files.items():
                path=managed_path(store.path,relative)
                if not path.is_file() or sha(path)!=digest: raise ValueError('庫存遺失或內容變更，備份未完成：'+relative)
                archive.write(path,Path(relative).as_posix()); manifest['files'][Path(relative).as_posix()]=digest
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        with ZipFile(temp) as archive:
            if archive.testzip(): raise ValueError('備份封裝校驗失敗')
            for name,digest in manifest['files'].items():
                h=hashlib.sha256()
                with archive.open(name) as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
                if h.hexdigest()!=digest:raise ValueError('備份內容與清單校驗不符：'+name)
        with destination.open('xb') as out, temp.open('rb') as src: shutil.copyfileobj(src,out)
    return dict(path=str(destination),files=len(manifest['files']),external=len(external))

def restore_backup(source,destination):
    destination=Path(destination).resolve()
    if destination.exists(): raise ValueError('還原資料夾必須是全新位置，不能覆蓋現有資料')
    with ZipFile(source) as archive:
        if len(archive.infolist())>100_000: raise ValueError('備份檔案數過多')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!='TRAADuoDuo-portable-1': raise ValueError('不是支援的可攜備份')
        if manifest.get('database')!='library.db': raise ValueError('備份資料庫名稱不符')
        for name in manifest['files']:
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or (name!='library.db' and not name.startswith('Docstore/')): raise ValueError('備份包含不安全的檔案路徑')
        with tempfile.TemporaryDirectory(prefix='traa-restore-',dir=destination.parent) as directory:
            directory=Path(directory); restored=directory/'restored'; restored.mkdir()
            for name,digest in manifest['files'].items():
                target=restored/name; target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(name) as src,target.open('xb') as out: shutil.copyfileobj(src,out)
                if sha(target)!=digest: raise ValueError('還原檔案校驗失敗：'+name)
            from .store import ProjectStore
            store=ProjectStore(restored/'library.db')
            with store.connect() as conn: store.validate(conn,full=True)
            os.rename(restored,destination)
    return str(destination/'library.db')
