"""Create a source-only release with a verified, self-contained hash manifest."""
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
excluded={'__pycache__','.git','.venv','deliverables','history'}
files=sorted(p for p in root.rglob('*') if p.is_file() and not any(part in excluded for part in p.relative_to(root).parts) and p.suffix not in ('.pyc','.db','.log') and p.name not in ('.DS_Store','SHA256_MANIFEST.json'))
manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
manifest_path=root/'SHA256_MANIFEST.json';manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
from traaduoduo import VERSION
target=root/'deliverables';target.mkdir(exist_ok=True);archive_path=target/('TRAADuoDuo_'+VERSION+'.zip')
with ZipFile(archive_path,'w',ZIP_DEFLATED) as archive:
    for path in files+[manifest_path]:archive.write(path,'TRAADuoDuo_'+VERSION+'/'+path.relative_to(root).as_posix())
with ZipFile(archive_path) as archive:
    assert archive.testzip() is None
    for name,digest in manifest.items():assert hashlib.sha256(archive.read('TRAADuoDuo_'+VERSION+'/'+name)).hexdigest()==digest,name
digest=hashlib.sha256(archive_path.read_bytes()).hexdigest()
(target/'SHA256.txt').write_text(digest+'  '+archive_path.name+'\n',encoding='utf-8')
print(json.dumps(dict(archive=str(archive_path),source_files=len(files),sha256=digest,bytes=archive_path.stat().st_size),ensure_ascii=False))
