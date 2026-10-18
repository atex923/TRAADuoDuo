"""Inclusive deadlines; the working ledger is independent of finish mode."""
from datetime import date, timedelta
from .domain import CalendarContext, calculate_finish, decimal

LINKED_DATES = ('workday_finish','calendar_finish','initial_expected','acceptance_expected')

def working_calendar(pages):
    return CalendarContext('工作日',
        {date.fromisoformat(r[0]) for r in pages['holidays']},
        {date.fromisoformat(r[0]) for r in pages['makeup']},
        {date.fromisoformat(r[0]) for r in pages['railway']},
        {date.fromisoformat(r[0]): tuple(r[1:]) for r in pages['weather']})

def deadlines(pages):
    basic=pages['basic']; result=dict.fromkeys(LINKED_DATES,'')
    result['workdayA']=''
    if not basic['start'] or not basic['days']:
        return result
    start=date.fromisoformat(basic['start']); days=decimal(basic['days'])
    if days==0:
        return result
    if days<0 or days!=days.to_integral_value() or days>36600:
        raise ValueError('契約工期須為 0 至 36600 的整數')
    calendar_finish=start+timedelta(days=int(days)-1)
    work_finish=calculate_finish(start,days,working_calendar(pages))
    result.update(workday_finish=work_finish.isoformat(),calendar_finish=calendar_finish.isoformat(),
                  workdayA=str((work_finish-calendar_finish).days))
    base=work_finish if basic['mode']=='工作日' else calendar_finish
    if basic['initial_days']!='':
        initial=base+timedelta(days=int(basic['initial_days']))
        result['initial_expected']=initial.isoformat()
        if basic['acceptance_days']!='':
            result['acceptance_expected']=(initial+timedelta(days=int(basic['acceptance_days']))).isoformat()
    return result

def weather_text(row):
    am,pm,note=row[1:4]; nc=row[4] if len(row)>4 else ('1' if note.strip()=='-1' else '0')
    if decimal(am or '0')>=1:
        return '上午:雨天,全日不計'
    if decimal(nc or '0')==1 or note.strip()=='-1':
        return '不計工期,'+('' if note.strip()=='-1' else note)
    parts=[]
    if decimal(am or '0')>0:
        parts.append('上午:雨天,全日不計（舊值）')
    if decimal(pm or '0')>0:
        parts.append('下午:雨天')
    if note:
        parts.append(note)
    return ','.join(parts)
