"""Read-only source verification with an isolated destination. Prints counts only."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from traaduoduo.importer import preview_database
from traaduoduo.store import ProjectStore

source=Path(sys.argv[1]).resolve()
before=hashlib.sha256(source.read_bytes()).hexdigest()
preview=preview_database(source)
report={'projects':len(preview['projects']),'errors':[p['errors'] for p in preview['projects']],
        'mapped':[{key:len(p['pages'][key]['rows']) if key=='admin_payments' else len(p['pages'][key])
                   for key in ('contract_payments','other_payments','admin_payments')} for p in preview['projects']]}
if not any(p['errors'] for p in preview['projects']):
    with tempfile.TemporaryDirectory() as directory:
        target=Path(directory)/'validation.db'; store=ProjectStore.create_library(target)
        ids=store.import_preview(preview)['ids']
        for index,pid in enumerate(ids):
            loaded=ProjectStore(target,pid).load()
            for key in ('contract_payments','other_payments','admin_payments'):
                assert loaded['pages'][key]==preview['projects'][index]['pages'][key]
            assert loaded['pages']['bids']==preview['projects'][index]['pages']['bids']
            with ProjectStore(target,pid).connect() as connection:
                raw=json.loads(connection.execute('SELECT raw_payload FROM imports WHERE project_id=?',(pid,)).fetchone()[0])
                assert raw==preview['projects'][index]['raw']
        report['isolated_imported']=len(ids)
        report['bid_annotations_and_raw_snapshots_preserved']=True
report['source_sha256_unchanged']=before==hashlib.sha256(source.read_bytes()).hexdigest()
assert report['source_sha256_unchanged']
print(json.dumps(report,ensure_ascii=False,indent=2))
if any(report['errors']):
    raise SystemExit(2)
