"""Unified advanced-page defaults and strict, project-local validations."""
from copy import deepcopy
from datetime import date
from .aa_import import TABLES
from .tracking import normalize_documents,validate_tracking,iso_day

EXTRA_KEYS={'details','diary','documents','photos','deadline_tracking'}

def normalize_extra(pages):
    result=deepcopy(pages)
    result.setdefault('details',{key:[] for key in TABLES})
    result.setdefault('diary',[])
    result.setdefault('deadline_tracking',[])
    for key in ('documents','photos'):
        result.setdefault(key,dict(categories=[],rows=[]))
    result['documents']=normalize_documents(result['documents'])
    return result

def validate_extra(key,value):
    if key=='details':
        if set(value)!=set(TABLES): raise ValueError('詳細表頁別不完整')
        for batches in value.values():
            seen=set()
            for batch in batches:
                if batch.get('errors'): raise ValueError('詳細表含匯入錯誤，未儲存')
                if batch['id'] in seen: raise ValueError('重複匯入批次')
                seen.add(batch['id'])
                ids=set()
                for row in batch['rows']:
                    if row['id'] in ids or len(row['values'])!=16: raise ValueError('詳細表紀錄不完整')
                    ids.add(row['id'])
    elif key=='deadline_tracking':
        validate_tracking(value)
    elif key=='diary':
        seen=set(); ids=set()
        for row in value:
            if type(row['number']) is not int or row['number']<1 or row['number'] in seen: raise ValueError('大事記項次須為不重複正整數')
            if row['id'] in ids: raise ValueError('大事記識別重複')
            seen.add(row['number']); ids.add(row['id']); date.fromisoformat(row['date'])
    else:
        if key=='documents':
            value=normalize_documents(value);numbers=set()
            for row in value['rows']:
                if type(row['number']) is not int or row['number']<1 or row['number'] in numbers:raise ValueError('文件項次須為不重複正整數')
                numbers.add(row['number'])
                if not isinstance(row['document_no'],str):raise ValueError('文件文號須為文字')
                if row['document_date']:iso_day(row['document_date'])
        categories={r['id']:r for r in value['categories']}
        if len(categories)!=len(value['categories']): raise ValueError('分類識別重複')
        for item in categories.values():
            seen={item['id']}; current=item.get('parent','')
            while current:
                if current in seen or current not in categories: raise ValueError('分類循環或上層不存在')
                seen.add(current); current=categories[current].get('parent','')
        ids=set()
        for row in value['rows']:
            if row['id'] in ids: raise ValueError('文件識別重複')
            ids.add(row['id'])
            if row.get('category') and row['category'] not in categories: raise ValueError('文件分類不存在')
            if row.get('stock') and not row.get('managed'): raise ValueError('庫存檔缺少驗證後的檔案路徑')
