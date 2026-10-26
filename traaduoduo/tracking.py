"""Calendar-date deadline rules; display refreshes never change business data."""
from datetime import date,datetime,timedelta
import re

TRACKING_COLUMNS=[('number','項次'),('alert','警示'),('issued_at','發文時間'),('document_no','文號'),('due_date','限期日'),('work','限期工作'),('completed_date','完成日'),('overdue_date','逾期日')]
DOCUMENT_COLUMNS=[('number','項次'),('name','文件名稱'),('document_no','文件文號'),('document_date','文件日期'),('stock','庫存檔'),('category','分類'),('status','狀態'),('note','備註')]
PHOTO_COLUMNS=[('name','照片名稱'),('stock','庫存檔'),('category','分類'),('status','狀態'),('note','備註')]

def iso_day(value):
    day=date.fromisoformat(value)
    if day.isoformat()!=value:raise ValueError('日期須為 YYYY-MM-DD')
    return day

def normalize_documents(value):
    from copy import deepcopy
    result=deepcopy(value)
    used=[r['number'] for r in result['rows'] if type(r.get('number')) is int and r['number']>0]
    next_number=max(used,default=0)+1
    for row in result['rows']:
        if 'number' not in row:row['number']=next_number;next_number+=1
        row.setdefault('document_no','');row.setdefault('document_date','')
    return result

def document_order(rows,mode):
    rows=list(rows)
    if mode==1:rows.sort(key=lambda r:r['name'].casefold())
    elif mode==2:rows.sort(key=lambda r:(not bool(r.get('capture_date')),r.get('capture_date',''),r['name'].casefold()))
    elif mode in (3,4):rows.sort(key=lambda r:r['number'],reverse=mode==4)
    elif mode==5:rows.sort(key=lambda r:(not bool(r.get('document_date')),r.get('document_date',''),r['number']))
    return rows

def validate_tracking(rows):
    numbers=set();ids=set()
    for row in rows:
        if not isinstance(row.get('id'),str) or not row['id'] or row['id'] in ids:raise ValueError('期限工作識別須唯一且不可空白')
        if type(row.get('number')) is not int or row['number']<1 or row['number'] in numbers:raise ValueError('期限項次須為不重複正整數')
        numbers.add(row['number']);ids.add(row['id'])
        if not isinstance(row.get('work'),str) or not row['work'].strip():raise ValueError('請填寫限期工作')
        for field in ('due_date','completed_date','issued_at','document_no'):
            if not isinstance(row.get(field),str):raise ValueError('期限欄位格式不完整')
        due=iso_day(row['due_date'])
        if due==date.max:raise ValueError('限期日需可推算下一日')
        if row['completed_date']:iso_day(row['completed_date'])
        issued=row['issued_at']
        if issued:
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',issued):iso_day(issued)
            elif re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}',issued):datetime.strptime(issued,'%Y-%m-%d %H:%M')
            else:raise ValueError('發文時間請用 YYYY-MM-DD，或 YYYY-MM-DD HH:MM')

def deadline_status(row,today=None):
    today=today or date.today()
    try:
        due=iso_day(row['due_date']);overdue=due+timedelta(days=1)
        completed=iso_day(row['completed_date']) if row.get('completed_date') else None
    except (ValueError,TypeError,KeyError,OverflowError):
        return dict(state='invalid',text='待設定',color='#E0E0E0',foreground='#333333',bold=False,days=0,overdue_date='',remaining=None)
    end=completed or today;days=max(0,(end-overdue).days+1)
    state='completed' if completed else 'overdue' if today>=overdue else 'due' if today==due else 'pending'
    colors={'completed':'#E0E0E0','overdue':'#D32F2F','due':'#FFA500','pending':'#FFF2CC'}
    text={'completed':'已完成','overdue':f'{days} 天','due':'今日到期','pending':'未到期'}[state]
    return dict(state=state,text=text,color=colors[state],foreground='#FFFFFF' if state=='overdue' else '#333333',bold=state=='overdue',days=days,overdue_date=overdue.isoformat(),remaining=(due-today).days)

def upcoming(rows,today=None):
    today=today or date.today()
    return sorted([r for r in rows if not r.get('completed_date') and (s:=deadline_status(r,today))['remaining'] is not None and 0<=s['remaining']<=5],key=lambda r:(r['due_date'],r['number']))
