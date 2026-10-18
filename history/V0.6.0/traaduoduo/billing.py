"""Stage-three ledger calculations. Decimal strings are authoritative, not totals."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from .domain import decimal

STAGES = [('first','第一期提撥（開工）','60%'),('second','第二期提撥（工進60%）','30%'),
          ('third','第三期提撥（工進80%）','10%'),('final','末期結算（驗收）','負數檢查')]
CATEGORIES = [('0C12','0C12差費'),('0C11','0C11加班費'),('0C14','0C14其他費')]
CONTRACT_MONEY = [('estimated','估驗金額（稅）'),('amount','計價金額'),('tax','計價稅金'),
                  ('paid','實發金額'),('paid_tax','實發稅金'),('retention','保留款')]
DATES = [('submitted','估驗送件日期'),('payment_date','計價日期'),('reviewed','送審日期')]
PAYMENT_KEYS = ('contract_payments','other_payments','admin_payments')

def empty_admin():
    return dict(rows=[],allocations=[dict(stage=s,period='',**{c:'' for c,_ in CATEGORIES}) for s,_,_ in STAGES],available_basis='period')

def new_record(kind,rid,period):
    row=dict(id=rid,period=period,payment_date='',note='')
    if kind=='other_payments':
        row.update(item='0A',stage='',amount='',tax='')
    else:
        row.update({k:'' for k,_ in CONTRACT_MONEY+DATES})
        if kind=='admin_payments':
            row.update({c:'' for c,_ in CATEGORIES})
    return row

def normalize_billing(pages):
    result=deepcopy(pages)
    result.setdefault('contract_payments',[])
    result.setdefault('other_payments',[])
    admin=empty_admin(); admin.update(result.get('admin_payments',{}))
    if admin['available_basis']=='all':
        admin['available_basis']='period'
    result['admin_payments']=admin
    return result

def number(value):
    return decimal(str(value).replace(',','').strip())

def total(rows,key):
    return sum((number(r[key]) for r in rows if r.get(key,'')!=''),Decimal(0))

def fmt(value):
    return '' if value is None or value=='' else format(number(value),',f')

def through(rows,period=None):
    return [r for r in rows if period is None or r['period']<=period]

def period_options(rows):
    return sorted({r['period'] for r in rows})

def validate_billing(key,value):
    rows=value['rows'] if key=='admin_payments' else value
    ids=set(); transfers={}
    for row in rows:
        if not isinstance(row['id'],str) or not row['id'] or row['id'] in ids:
            raise ValueError('計價紀錄 ID 不可空白或重複')
        ids.add(row['id'])
        if type(row['period']) is not int or row['period']<1:
            raise ValueError('計價期數須為正整數')
        keys=[('amount',''),('tax','')] if key=='other_payments' else CONTRACT_MONEY
        if key=='admin_payments':
            keys=keys+CATEGORIES
        for field,_ in keys:
            if row[field]!='':
                try: number(row[field])
                except (ValueError,ArithmeticError) as exc:
                    raise ValueError(f'計價紀錄 {row["id"]} 的 {field} 不是有效金額；原值保留，請核對來源') from exc
        for field,_ in ([('payment_date','')] if key=='other_payments' else DATES):
            if row[field]:
                date.fromisoformat(row[field])
        if key=='other_payments':
            if row['item'] not in ('transfer','0A','legacy') or row['stage'] not in ('',*[s for s,_,_ in STAGES]):
                raise ValueError('未知計價項目或提撥階段')
            if row['item']!='transfer' and row['stage']:
                raise ValueError('非管理費提撥不可指定提撥階段')
            if row['item']=='transfer' and row['stage']:
                stage=row['stage']
                if stage in transfers:
                    label=next(label for code,label,_ in STAGES if code==stage)
                    raise ValueError(f'{label}每階段限一筆管理費提撥；衝突紀錄 {transfers[stage]}、{row["id"]}。未自動合併或刪除。')
                transfers[stage]=row['id']
        elif key=='admin_payments':
            expected=sum((number(row[c]) for c,_ in CATEGORIES if row[c]!=''),Decimal(0))
            has_amount=any(row[c]!='' for c,_ in CATEGORIES)
            if (has_amount and row['amount']=='') or (row['amount']!='' and number(row['amount'])!=expected):
                raise ValueError('管理費計價合計須等於三費別合計')
    if key=='admin_payments':
        if value['available_basis']!='period':
            raise ValueError('可支用額的分攤與支用都必須截至所選期')
        stages=set()
        for allocation in value['allocations']:
            stage=allocation['stage']
            if stage not in {s for s,_,_ in STAGES} or stage in stages:
                raise ValueError('分攤階段不可重複或未知')
            stages.add(stage)
            if allocation['period']!='' and (type(allocation['period']) is not int or allocation['period']<1):
                raise ValueError('分攤生效期數須為正整數或留空')
            for c,_ in CATEGORIES:
                if allocation[c]!='':
                    number(allocation[c])
        if stages!={s for s,_,_ in STAGES}:
            raise ValueError('四階段分攤資料不完整')

def allocation_filled(allocation):
    # An explicitly saved zero is filled; a blank remains unfilled.
    return all(allocation[c]!='' for c,_ in CATEGORIES)

def stage_summary(pages):
    result=[]; running_transfer=Decimal(0); running_allocation=Decimal(0)
    allocations={a['stage']:a for a in pages['admin_payments']['allocations']}
    for stage,label,ratio in STAGES:
        rows=[r for r in pages['other_payments'] if r['item']=='transfer' and r['stage']==stage]
        allocation=allocations[stage]
        transfer=total(rows,'amount'); allocated=sum((number(allocation[c]) for c,_ in CATEGORIES if allocation[c]!=''),Decimal(0))
        running_transfer+=transfer; running_allocation+=allocated
        warnings=[]
        filled=allocation_filled(allocation)
        if rows and not filled:
            warnings.append('待分攤')
        if filled and transfer!=allocated:
            warnings.append('提撥與分攤不一致')
        if filled and not rows:
            warnings.append('尚無對應提撥')
        if stage=='final':
            if any(number(r['amount'])>0 for r in rows if r['amount']!=''):
                warnings.append('末期提撥含正數')
            if any(number(allocation[c])>0 for c,_ in CATEGORIES if allocation[c]!=''):
                warnings.append('末期分攤含正數')
            if rows and transfer==0:
                warnings.append('末期提撥為0，請核對')
        result.append(dict(stage=stage,label=label,ratio=ratio,transfer=transfer,allocated=allocated,
                           allocation=allocation,filled=filled,running_transfer=running_transfer,
                           running_allocation=running_allocation,warnings=warnings))
    return result

def summary(pages,key,period=None):
    rows=through(pages[key]['rows'] if key=='admin_payments' else pages[key],period)
    result={k:total(rows,k) for k in ('amount','tax','paid','paid_tax','retention')}
    if key=='other_payments':
        result['transfer']=total([r for r in rows if r['item']=='transfer'],'amount')
        result['0A']=total([r for r in rows if r['item']=='0A'],'amount')
    if key=='admin_payments':
        admin=pages[key]
        allocations=[a for a in admin['allocations'] if a['period']!='' and (period is None or a['period']<=period)]
        result['undated_allocations']=sum(any(a[c]!='' for c,_ in CATEGORIES) and a['period']=='' for a in admin['allocations'])
        for c,_ in CATEGORIES:
            result[c]=total(rows,c)
            result[c+'_available']=total(allocations,c)-result[c]
    return result

def warnings(pages):
    messages=[]
    preceding=True
    allocations={a['stage']:a for a in pages['admin_payments']['allocations']}
    for stage,label,_ in STAGES:
        allocation=allocations[stage]
        if not preceding and any(allocation[c]!='' for c,_ in CATEGORIES):
            messages.append(label+'：歷史越序分攤已保留；先補齊前階段及生效期再編輯')
        preceding=preceding and allocation_filled(allocation) and allocation['period']!=''
    for row in pages['other_payments']:
        if row['item']=='transfer' and not row['stage']:
            messages.append(f"第{row['period']}期管理費提撥尚未對應階段")
        if row['item']=='legacy':
            messages.append(f"第{row['period']}期舊計價項目待分類（原值已保留）")
    for stage in stage_summary(pages):
        messages.extend(stage['label']+'：'+s for s in stage['warnings'])
    if any(any(a[c]!='' for c,_ in CATEGORIES) and a['period']=='' for a in pages['admin_payments']['allocations']):
        messages.append('部分分攤未填生效期，未納入可支用額（包含全部期別）；請核對並填寫生效期')
    for c,label in CATEGORIES:
        if summary(pages,'admin_payments')[c+'_available']<0:
            messages.append(label+'可支用額為負，請核對')
    return messages

def map_legacy_billing(project,raw,pages,report):
    """Only verified fields; never use historical cumulative values as ledger rows."""
    from .finance import legacy_money
    pages=normalize_billing(pages); pid=project['id']
    mapping={'estimated':'estimated_amount_taxed','amount':'billing_amount_untaxed','tax':'billing_business_tax',
             'paid':'paid_amount_untaxed','paid_tax':'paid_business_tax','retention':'retention_amount',
             'submitted':'contractor_submit_date','payment_date':'owner_payment_date','reviewed':'supervision_submit_date'}
    for table,key in [('payment_contract','contract_payments'),('payment_other','other_payments'),('payment_admin','admin_payments')]:
        records=[]
        for source in raw.get(table,[]):
            if source.get('project_id')!=pid:
                continue
            try:
                period=int(source.get('period_no') or '')
            except (ValueError,TypeError):
                period=0  # Refuse import rather than silently invent a business period.
            row=new_record(key,'legacy-'+table+'-'+str(source['id']),period)
            row['note']=source.get('note') or ''
            if key=='contract_payments':
                for target,column in mapping.items():
                    row[target]=(source[column] or '') if target in {k for k,_ in DATES} else legacy_money(source.get(column))
            elif key=='other_payments':
                label=source.get('payment_item') or source.get('item') or ''
                row.update(payment_date=source.get('payment_date') or source.get('day') or '',
                           amount=legacy_money(source.get('payment_amount')),
                           tax='',item='transfer' if label in ('管理費','管理費提撥') else '0A' if label=='0A計價' else 'legacy',legacy_item=label)
            else:
                row['payment_date']=source.get('payment_date') or source.get('day') or ''
                for target,column in [('0C12','travel_fee_billing'),('0C11','overtime_fee_billing'),('0C14','other_fee_billing'),('tax','tax_amount')]:
                    row[target]=legacy_money(source.get(column))
                try:
                    row['amount']=str(sum((number(row[c]) for c,_ in CATEGORIES if row[c]!=''),Decimal(0))) if any(row[c]!='' for c,_ in CATEGORIES) else ''
                except (ValueError,ArithmeticError):
                    row['amount']=''
                    report.append('管理費支用 '+row['id']+' 含無法辨識金額；保留原欄位，預覽標示錯誤而不猜算合計。')
            records.append(row)
        if key=='admin_payments':
            pages[key]['rows']=records
        else:
            pages[key]=records
        if records:
            report.append(f'{table}→{key}：{len(records)}筆；累計由明細重算，額外欄位留在原始快照。空白或非正整數期別須先在來源修正。')
    admin=pages['admin_payments']
    for index,allocation in enumerate(admin['allocations'],1):
        for c,_ in CATEGORIES:
            value=project.get(f'admin_alloc{index}_{c.lower()}')
            if value not in (None,''):
                allocation[c]=legacy_money(value)
    if raw.get('payment_other'):
        report.append('舊提撥不按日期猜階段；請在新頁人工對應。缺少的稅金留空，未知項目待分類。')
    report.append('明確的金額格式（千分位、NT$／$前綴、元後綴）僅移除裝飾；未辨識字串不猜值，來源原字串保留於快照。')
    return pages
