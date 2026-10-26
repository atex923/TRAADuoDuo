"""Library-scoped, non-destructive content reuse. Indexes are disposable caches."""
from contextlib import contextmanager
from concurrent.futures import CancelledError
import json
import os
from pathlib import Path
import time
import uuid


def check_cancel(cancel):
    if cancel is not None and cancel.is_set(): raise CancelledError('已取消庫存，清單未改動')


@contextmanager
def library_lock(root,cancel=None):
    # OS locks release on crashes; the lock file itself is never a live-PID marker.
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.inventory.lock').open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush()
        acquired=False;deadline=time.monotonic()+60
        try:
            while not acquired:
                check_cancel(cancel)
                try:
                    if os.name=='nt':
                        import msvcrt
                        stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    acquired=True
                except OSError:
                    if time.monotonic()>deadline:raise ValueError('其他庫存作業尚未完成，請稍後重試')
                    time.sleep(.05)
            yield
        finally:
            if acquired:
                if os.name=='nt':
                    stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def verified_candidates(root,source_size,digest,hash_file,cancel=None):
    """Only inspect this library. Never follow a candidate symlink outside it."""
    index_path=root/'.content-index.json'
    try:
        index=json.loads(index_path.read_text(encoding='utf-8'))
        if not isinstance(index,dict):index={}
    except (OSError,ValueError):index={}
    checked=set()
    def valid(path):
        check_cancel(cancel)
        try:
            if path.name.startswith('.') or path.name.endswith('.partial'):return False
            resolved=path.resolve()
            if not resolved.is_relative_to(root.resolve()) or path.is_symlink():return False
            if not path.is_file() or path.stat().st_size!=source_size:return False
            checked.add(resolved)
            return hash_file(path,cancel)==digest
        except OSError:return False
    cached=index.get(digest,[])
    if not isinstance(cached,list):cached=[]
    for name in cached:
        if isinstance(name,str) and valid(root/name):return root/name,index,True
    # Handles legacy, unindexed, and interrupted-but-complete inventory without deletion.
    for path in root.rglob('*'):
        check_cancel(cancel)
        if path.name.startswith('.') or path.name.endswith('.partial') or path.resolve() in checked:continue
        if valid(path):return path,index,True
    return None,index,False


def remember(root,index,digest,target):
    index[digest]=[target.relative_to(root).as_posix()]
    temp=root/('.index-'+uuid.uuid4().hex+'.partial')
    try:
        with temp.open('x',encoding='utf-8') as stream:
            json.dump(index,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,root/'.content-index.json')
    finally:
        if temp.exists():temp.unlink()
