"""Use only the reference DB.init_schema AST; never launch the legacy GUI."""
import ast
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from traaduoduo.importer import preview_database
from traaduoduo.store import ProjectStore

source = Path(sys.argv[1])
tree = ast.parse(source.read_text(encoding='utf-8-sig'))
db_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DB')
method = next(n for n in db_class.body if isinstance(n, ast.FunctionDef) and n.name == 'init_schema')
namespace = {'sqlite3': sqlite3}
for name in ('PROJECT_EXTRA_FIELDS','PAYMENT_CONTRACT_FIELDS','PAYMENT_OTHER_FIELDS','PAYMENT_ADMIN_FIELDS','PROGRESS_ESTIMATE_FIELDS'):
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t,ast.Name) and t.id == name for t in n.targets))
    namespace[name] = ast.literal_eval(assignment.value)
exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'reference.db'
    with closing(sqlite3.connect(path)) as conn:
        class Fixture:
            pass
        fixture = Fixture()
        fixture.conn = conn
        namespace['init_schema'](fixture)
        with conn:
            conn.execute("INSERT INTO projects(name,exec_no,actual_start,contract_days,day_type) VALUES('原始 schema 工程','REF-01','2026-10-01',100,'工作日')")
            conn.execute("INSERT INTO holidays(project_id,day,name) VALUES(1,'2026-10-10','假期')")
            conn.execute("INSERT INTO weather(project_id,day,morning,afternoon,note) VALUES(1,'2026-10-13',0,0.5,'雨')")
            conn.execute("INSERT INTO payment_contract(project_id,period_no,billing_amount_untaxed,billing_business_tax,owner_payment_date) VALUES(1,'2','100.01','5.0005','2026-10-16')")
            conn.execute("INSERT INTO payment_other(project_id,period_no,payment_date,payment_item,payment_amount) VALUES(1,'3','2026-10-17','管理費','200')")
            conn.execute("INSERT INTO payment_admin(project_id,period_no,payment_date,travel_fee_billing,overtime_fee_billing,other_fee_billing,tax_amount) VALUES(1,'4','2026-10-18','10','20','30','3.0001')")
            conn.execute("UPDATE projects SET admin_alloc1_0c12='100',admin_alloc1_0c11='50',admin_alloc1_0c14='50' WHERE id=1")
    before = path.read_bytes()
    preview = preview_database(path)
    target = Path(directory) / 'target.db'
    ProjectStore.create(target)
    ids = ProjectStore(target).import_preview(preview)['ids']
    result = ProjectStore(target, ids[0]).load()
    assert result['pages']['basic']['number'] == 'REF-01'
    assert result['pages']['weather'] == [['2026-10-13','0','0.5','雨','0']]
    assert result['pages']['contract_payments'][0]['amount']=='100.01'
    assert result['pages']['other_payments'][0]['stage']==''
    assert result['pages']['admin_payments']['rows'][0]['amount']=='60'
    assert result['pages']['admin_payments']['rows'][0]['tax']=='3.0001'
    assert result['pages']['admin_payments']['allocations'][0]['0C12']=='100'
    assert path.read_bytes() == before
    print('TR_FxWork original init_schema: calendar + three payment types + allocations preview/import passed; source bytes unchanged.')
