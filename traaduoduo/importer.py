"""Read-only legacy preview. Mappings follow TR_FxWork V0.3.4.3 DB source."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from .store import APPLICATION_ID, DEFAULT_BASIC, PAGE_KEYS
from .session import EditSession
from .details import normalize_pages
from .finance import map_legacy_finance
from .billing import map_legacy_billing


def preview_database(path):
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('來源資料庫完整性檢查失敗')
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        app_id = conn.execute('PRAGMA application_id').fetchone()[0]
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        result = []
        if app_id == APPLICATION_ID and version == 1:
            meta = dict(conn.execute('SELECT key,value FROM metadata'))
            pages = {r['page_id']: json.loads(r['payload']) for r in conn.execute('SELECT * FROM pages')}
            result.append(dict(source_key='traaduoduo:' + meta['project_id'], pages=pages,
                               raw={'metadata': meta, 'pages': pages}, report=['TRAADuoDuo schema 1：全部五個資料頁轉換']))
            kind = 'TRAADuoDuo V0.0.1/V0.0.2'
        elif app_id == APPLICATION_ID and version in (2, 3, 4, 5, 6, 7, 8, 9, 10):
            for project in conn.execute('SELECT * FROM projects'):
                pid = project['project_id']
                pages = {r['page_id']: json.loads(r['payload']) for r in conn.execute('SELECT * FROM pages WHERE project_id=?', (pid,))}
                if version>=4:
                    pages['bids']=[dict(json.loads(r['payload']),id=r['record_id'],awarded=bool(r['awarded'])) for r in conn.execute('SELECT * FROM bids WHERE project_id=? ORDER BY rowid',(pid,))]
                if version>=5:
                    from .store import ProjectStore
                    pages=ProjectStore._read_pages(conn,pid,version)
                raw = {'project': dict(project), 'pages':pages, 'imports': [dict(r) for r in conn.execute('SELECT * FROM imports WHERE project_id=?', (pid,))]}
                report=['統一資料庫工程匯入為新工程；原封存狀態保存在原始紀錄']
                if version<=9:report.append('V0.8：工程費用依新公式重算，舊費用值另存 historical_v070；分攤有效期改由同階段提撥期數連動，人工生效期保留為歷史欄。事記本依原清單順序保留。')
                if version<=8:report.append('schema 9：文件依原順序補入項次，文號與文件日期留白；大事記完整移至事記本，期限追蹤另建空清單。來源不改寫。')
                if version<=6:
                    report.append('V0.5 工期與費用使用新連動規則；舊總額、預定日期與晴雨原值保留供差異核對，來源不改寫。')
                if version<=5:
                    report.append('依確認規則：各階段提撥限一筆，分攤與支用都截至所選期；舊全階段模式轉為按期，原值保留於快照。分攤未填生效期不猜填。')
                if version<=4:
                    candidates=[]
                    for evidence in raw['imports']:
                        if evidence['source_key'].startswith('tr_fxwork:'):
                            snapshot=json.loads(evidence['raw_payload'])
                            legacy_id=evidence['source_key'].rsplit(':',1)[-1]
                            matched=[p for p in snapshot.get('projects',[]) if str(p['id'])==legacy_id]
                            if len(matched)==1:
                                candidates.append((matched[0],snapshot))
                    if len(candidates)==1:
                        pages=map_legacy_billing(*candidates[0],pages,report)
                        report.append('已從此工程唯一的 TR_FxWork 原始匯入快照補回計價；未覆寫其他新版頁面。')
                    elif candidates:
                        report.append('此工程有多個舊來源快照，不猜選計價來源；原始快照保留，請直接匯入指定舊庫。')
                result.append(dict(source_key='traaduoduo:' + pid, pages=pages, raw=raw,
                                   report=report))
            kind = 'TRAADuoDuo 統一資料庫'
        elif app_id == 0 and {'projects', 'holidays', 'workdays', 'railway', 'weather'} <= tables:
            required = {'id', 'name', 'exec_no', 'budget_no', 'award_date', 'planned_start', 'actual_start', 'contract_days', 'day_type'}
            columns = {r[1] for r in conn.execute('PRAGMA table_info(projects)')}
            if not required <= columns:
                raise ValueError('TR_FxWork 欄位不符合已核對的 V0.3.4.3 格式')
            # Capture the entire read transaction, including unmapped data, as evidence.
            raw = {}
            for table in sorted(tables):
                quoted = '"' + table.replace('"', '""') + '"'
                raw[table] = [dict(r) for r in conn.execute('SELECT * FROM ' + quoted)]
            digest = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            for p in raw['projects']:
                if p.get('password_hash'):
                    raise ValueError('來源含密碼保護工程；請先在 TR_FxWork 正式解除保護再匯入')
                pid = p['id']
                basic = dict(DEFAULT_BASIC, name=p['name'], number=p.get('exec_no') or '',
                             award=p.get('award_date') or '', start=p.get('actual_start') or p.get('planned_start') or '',
                             days=str(p['contract_days']), mode=p['day_type'])
                pages = dict(basic=basic, holidays=[], makeup=[], railway=[], weather=[])
                report = ['exec_no→工程編號；award_date→決標日期；actual_start 優先於 planned_start。',
                          'budget_no 與其餘未對應欄位及資料表保存在原始資料紀錄；可匯出 JSON 報告。',
                          '假期/補班/輸運採共用日期及各工程排除設定，依來源程式的 SQL MAX 聚合。']
                for table, page, exclude, field in [('holidays','holidays','holiday_project_excludes','name'),
                        ('workdays','makeup','workday_project_excludes','name'), ('railway','railway','railway_project_excludes','note')]:
                    excluded = {r['day'] for r in raw.get(exclude, []) if r['project_id'] == pid and r['excluded']}
                    grouped = {}
                    for r in raw[table]:
                        day = r['day']
                        if not day or not day.strip():
                            report.append(f'{table} 空白日期未轉入工曆；保存在原始紀錄')
                            continue
                        grouped.setdefault(day, []).append(r.get(field) or '')
                    pages[page] = [[d, max(names)] for d, names in sorted(grouped.items()) if d not in excluded]
                for r in raw['weather']:
                    if r['project_id'] == pid:
                        if r.get('typhoon') or r.get('site'):
                            report.append(f"{r['day']}：天氣/場地欄位保存在原始紀錄，未映射到新版編輯欄位")
                        pages['weather'].append([r['day'], str(r['morning'] or 0), str(r['afternoon'] or 0), r.get('note') or ''])
                pages=map_legacy_finance(p,raw,pages,report)
                pages=map_legacy_billing(p,raw,pages,report)
                result.append(dict(source_key=f'tr_fxwork:{digest}:{pid}', pages=pages, raw=raw, report=report))
            kind = 'TR_FxWork V0.3.4.3 相容格式'
        else:
            raise ValueError('不支援此來源格式；未修改原檔')
        if not result:
            raise ValueError('來源沒有工程')
        for item in result:
            item['pages'] = normalize_pages(item['pages'])
            for asset_key in ('documents','photos'):
                for asset in item['pages'][asset_key]['rows']:
                    if asset.get('managed'):
                        from .asset_store import managed_path
                        linked=managed_path(path,asset['managed'])
                        asset['source']=str(linked);asset['stock']=False;asset['managed']='';asset['versions']=[]
                        item['report'].append('文件／照片庫存轉為來源庫的唯讀連結；勾選庫存檔才複製到目標 Docstore。')
            item['errors'] = []
            try:
                if set(item['pages']) != PAGE_KEYS:
                    raise ValueError('來源工程頁不完整')
                EditSession(item['pages']).validate()
            except (ValueError, ArithmeticError, KeyError, TypeError, IndexError) as exc:
                item['errors'].append(str(exc))
                item['report'].append('暫停匯入：' + str(exc) + '。請在來源程式修正，再重新預覽。')
            item['report'].append('筆數：' + '、'.join(f'{k}={len(v["rows"]) if k=="admin_payments" else len(v)}' for k,v in item['pages'].items() if k not in ('basic','guarantees','costs')))
        return {'source': str(path), 'kind': kind, 'projects': result}
