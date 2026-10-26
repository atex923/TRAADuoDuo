"""Stage-two decimal calculations and linked values. No payment records."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
import re
from .domain import decimal

FIELDS = [('total','總工程預算／費用（含稅）'),('unfinished','未完工程'),('unfinished_tax','未完工程進項稅額'),
 ('award_total','發包工程費預算／契約金額（含稅）'),('work','發包工程／發包工程費金額'),('work_tax','進項稅額／營業稅'),
 ('base_price','底價'),('labor','包工費'),('management_amount','工程管理費'),('own_labor','自辦工費'),
 ('purchased_material','自購材料費'),('road_stock','路備材料費'),('road_purchase','路購材料費'),
 ('supervision','監理費'),('freight','運雜費'),('stamp_tax','印花稅'),('other_fees','其他費用'),('pollution','空污費')]
DERIVED_COSTS={'total','unfinished','other_fees','non_labor'}
COPY_KEYS={'own_labor','purchased_material','road_stock','road_purchase','supervision','freight','stamp_tax','pollution'}

def empty_costs():
    side={k:'' for k,_ in FIELDS}
    side.update(management_manual=False,management_adjustment='',non_labor='')
    return dict(budget=deepcopy(side),contract=deepcopy(side),extensions=[],guarantee_base='award_total',own_labor_copy='own_labor',calculation_revision=3,extensions_visible=True)

def normalize_costs(value):
    result=empty_costs()
    result.update(deepcopy(value))
    for side in ('budget','contract'):
        result[side]=dict(empty_costs()[side],**value.get(side,{}))
        if value and 'calculation_revision' not in value:
            result[side].setdefault('historical_totals',{key:value.get(side,{}).get(key,'') for key in ('total','unfinished')})
    if value and 'calculation_revision' not in value:
        result['source_settings_legacy']={key:value.get(key,result[key]) for key in ('guarantee_base','own_labor_copy')}
    result.setdefault('extensions_visible',True)
    if value and value.get('calculation_revision',0)<2:
        for kind in ('budget','contract'):result[kind].setdefault('historical_v070',deepcopy(value.get(kind,{})))
    if value and value.get('calculation_revision',0)<3:
        for kind in ('budget','contract'):result[kind].setdefault('historical_v080',deepcopy(value.get(kind,{})))
    result['calculation_revision']=3
    return result

def cost_totals(costs,kind):
    side=costs[kind]
    other=amount(side['pollution'] or '0')+sum((amount(r[kind] or '0') for r in costs['extensions']),Decimal(0))
    non=sum((amount(side[k] or '0') for k in ('own_labor','purchased_material','road_stock','road_purchase','supervision','freight')),Decimal(0))+other
    unfinished=amount(side['award_total'])+amount(side['management_amount'])+non-amount(side['unfinished_tax']) if all(side[k]!='' for k in ('award_total','management_amount','unfinished_tax')) else None
    total=unfinished+amount(side['unfinished_tax']) if unfinished is not None and side['unfinished_tax']!='' else None
    return {key:('' if val is None else text_amount(val)) for key,val in dict(other_fees=other,non_labor=non,unfinished=unfinished,total=total).items()}

def amount(text):
    value=decimal(str(text).replace(',','').strip())
    if value<0:
        raise ValueError('工程費用不可為負數')
    return value

def text_amount(value):
    return format(value,'f')

def format_money(value):
    return '' if value=='' or value is None else format(decimal(value).quantize(Decimal('.01'),rounding=ROUND_HALF_UP),',.2f')

def legacy_money(value):
    """Remove only explicit currency decoration. Unknown text stays invalid."""
    if value is None: return ''
    text=str(value).strip()
    match=re.fullmatch(r'(?:NT\$|\$)?\s*([+-]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*元?',text,re.IGNORECASE)
    return match.group(1).replace(',','') if match else text

def legacy_percent(value):
    text=str(value).strip()
    match=re.fullmatch(r'([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*[%％]?',text)
    return match.group(1) if match else text

def legacy_date(value):
    text=str(value or '').strip()
    match=re.fullmatch(r'(\d{4}-\d{2}-\d{2})\s*(?:\([^)]*\)|（[^）]*）)',text)
    if match:
        try: date.fromisoformat(match.group(1))
        except ValueError: return text,''
        return match.group(1),text
    return text,''

def management_fee(side,kind):
    main='labor'
    if side[main]=='':
        return None
    source=sum((amount(side[k] or '0') for k in (main,'own_labor','purchased_material','road_stock','road_purchase')),Decimal(0))
    bounds=[(0,5000000,'0.03'),(5000000,25000000,'0.015'),(25000000,100000000,'0.01'),(100000000,500000000,'0.007'),(500000000,None,'0.005')]
    tiers=[max(Decimal(0),(source if high is None else min(source,Decimal(high)))-Decimal(low))*Decimal(rate) for low,high,rate in bounds]
    total=sum(tiers,Decimal(0))
    default=(total/1000).to_integral_value(rounding=ROUND_FLOOR)*1000
    adjusted=amount(side['management_adjustment']) if side['management_manual'] and side['management_adjustment']!='' else (None if side['management_manual'] else default)
    return dict(source=source,tiers=tiers,total=total.quantize(Decimal('1'),rounding=ROUND_HALF_UP),raw_total=total,default=default,adjusted=adjusted)

def percent(numerator,denominator):
    if numerator=='' or denominator=='' or amount(denominator)==0:
        return '—'
    return f'{(amount(numerator)/amount(denominator)*100).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)}%'

def synchronize(pages):
    result=deepcopy(pages)
    costs=result['costs']
    for kind in ('budget','contract'):
        if kind=='budget':costs[kind]['award_total']=text_amount(amount(costs[kind]['work'])+amount(costs[kind]['work_tax'])) if costs[kind]['work']!='' and costs[kind]['work_tax']!='' else ''
        calculation=management_fee(costs[kind],kind)
        costs[kind]['management_amount']=costs[kind]['management_adjustment'] if costs[kind]['management_manual'] else (text_amount(calculation['adjusted']) if calculation and calculation['adjusted'] is not None else '')
        costs[kind].update(cost_totals(costs,kind))
    guarantees=result['guarantees']
    base=costs['contract'][costs['guarantee_base']]
    for prefix in ('performance','warranty'):
        guarantees[prefix+'_auto_amount']=text_amount((amount(base)*decimal(guarantees[prefix+'_rate'])/100).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)) if base!='' else ''
    basic=result['basic']
    from .scheduling import deadlines,LINKED_DATES
    if not basic.get('deadline_revision'):
        basic['historical_deadlines']={key:basic.get(key,'') for key in LINKED_DATES}
        basic['deadline_revision']=1
    basic.update(deadlines(result))
    awarded=[r for r in result['bids'] if r['awarded']]
    if awarded:
        if not basic.get('award_source','').startswith('bid:'):
            basic['award_legacy']=basic['award']
        basic['award']=awarded[0]['award_date']
        basic['award_source']='bid:'+awarded[0]['id']
    elif basic.get('award_source','').startswith('bid:'):
        basic['award']=basic.get('award_legacy','')
        basic['award_source']='legacy'
    return result

def validate_costs(costs):
    if costs['guarantee_base'] not in ('work','award_total') or costs['own_labor_copy'] not in ('own_labor','management_amount'):
        raise ValueError('未知費用來源')
    for kind in ('budget','contract'):
        side=costs[kind]
        if not isinstance(side['management_manual'],bool):
            raise ValueError('管理費覆寫須為勾選值')
        for key,_ in FIELDS:
            if side[key]!='':
                amount(side[key])
        if side['management_adjustment']!='':
            amount(side['management_adjustment'])
    ids=set()
    for item in costs['extensions']:
        if not item['id'] or item['id'] in ids or not item['label'].strip():
            raise ValueError('擴充項目 ID 不可重複，名稱不可空白')
        ids.add(item['id'])
        for kind in ('budget','contract'):
            if item[kind]!='':
                amount(item[kind])

def validate_bids(rows):
    ids=set()
    periods=set()
    awards=0
    for row in rows:
        if not row['id'] or row['id'] in ids or type(row['number']) is not int or row['number']<1 or row['number'] in periods:
            raise ValueError('招標 ID／次數不可重複，次數須為正整數')
        ids.add(row['id']); periods.add(row['number'])
        if type(row['awarded']) is not bool:
            raise ValueError('決標須為勾選值')
        awards+=int(row['awarded'])
        for key in ('review_start','review_end','online_start','online_end','opening','committee','award_date'):
            if row[key]:
                date.fromisoformat(row[key])
        for a,b in (('review_start','review_end'),('online_start','online_end')):
            if row[a] and row[b] and row[a]>row[b]:
                raise ValueError('起始日期不可晚於結束日期')
    if awards>1:
        raise ValueError('同一工程僅可有一筆決標')

def map_legacy_finance(project,raw,pages,report):
    """Map only named legacy columns; keep all original rows in raw evidence."""
    pages=deepcopy(pages)
    basic_mapping={'contractor':'contractor','contract':'purchase_contract_no','signed':'contract_date','description':'project_description',
                   'initial_actual':'actual_precheck_date','acceptance_actual':'actual_acceptance_date','warranty_years':'warranty_years','warranty_end':'warranty_end_date','settlement':'settlement_date','warranty_note':'warranty_note'}
    for key,source in basic_mapping.items():
        if project.get(source) not in (None,''):
            pages['basic'][key]=str(project[source])
    pages['guarantees']={}
    for key,source in [('difference_amount','deposit_difference'),('performance_amount','deposit_performance'),('performance_rate','performance_bond_rate'),('performance_form','performance_bond_type'),('warranty_amount','warranty_deposit'),('warranty_rate','warranty_rate'),('warranty_form','warranty_bond_type')]:
        if project.get(source) not in (None,''):
            pages['guarantees'][key]=(legacy_money(project[source]) if key.endswith('_amount') else legacy_percent(project[source]) if key.endswith('_rate') else str(project[source]))
    pages['guarantees']['performance_manual']=str(project.get('deposit_performance_manual') or '').lower() in ('1','true','yes')
    if pages['guarantees'].get('warranty_amount','')!='':
        pages['guarantees']['warranty_manual']=True
        report.append('舊保固金保留為手動歷史值；確認基數後可自行取消手動。')
    pages['costs']=empty_costs()
    mapping={'total':'total_amount','unfinished':'unfinished_amount','unfinished_tax':'input_tax',
             'award_total':'contract_total','work':'contract_amount','work_tax':'contract_tax','labor':'labor',
             'own_labor':'self_labor','purchased_material':'self_material','road_stock':'spare_material',
             'road_purchase':'railway_material','supervision':'supervision_fee','freight':'freight','pollution':'air_pollution_fee','base_price':'base_price'}
    for kind,prefix in [('budget','budget'),('contract','award')]:
        for key,suffix in mapping.items():
            value=project.get(prefix+'_'+suffix)
            if value not in (None,''):
                pages['costs'][kind][key]=legacy_money(value)
        manual=project.get(prefix+'_mgmt_fee')
        if manual not in (None,''):
            pages['costs'][kind]['management_manual']=True
            pages['costs'][kind]['management_adjustment']=legacy_money(manual)
    if project.get('budget_other') not in (None,'') or project.get('award_other') not in (None,''):
        pages['costs']['extensions'].append(dict(id='legacy-other',label='其他（舊版）',budget=legacy_money(project.get('budget_other')),contract=legacy_money(project.get('award_other'))))
    pages['bids']=[]
    for item in raw.get('bids',[]):
        if item.get('project_id')!=project['id']:
            continue
        online=str(item.get('online_date') or '').replace('～','~').split('~')
        try:
            number=int(item['round_no']) if item.get('round_no') not in (None,'') else 1
        except (ValueError,TypeError):
            number=0
        pages['bids'].append(dict(id='legacy-'+str(item['id']),number=number,awarded=bool(item.get('award_date')),
            review_start='',review_end='',online_start=online[0].strip() if len(online)<=2 else str(item['online_date']),online_end=online[1].strip() if len(online)==2 else '',
            opening=item.get('open_date') or '',committee='',award_date=item.get('award_date') or ''))
        row=pages['bids'][-1]; notes={}
        for key in ('online_start','online_end','opening','award_date'):
            day,note=legacy_date(row[key]); row[key]=day
            if note: notes[key]=note
        if notes:
            row['legacy_date_notes']=notes
            report.append('招標 '+row['id']+'：明確ISO日期後的括號備註另存於legacy_date_notes，完整原字串保留於快照。')
    if sum(r['awarded'] for r in pages['bids'])>1:
        for row in pages['bids']:
            row['awarded']=False
        report.append('來源有多筆決標日期；保留日期但不自動選唯一決標，請於新頁核對。')
    report.append('工程費用僅映射同名已核對欄位；舊管理費保留為手動調整。招標轉入次數、公開上網、開標及決標日期，其餘空白。')
    report.append('元金額及百分比的單位僅去除明確裝飾（10%→10，不除以100）；未知字串不猜值，來源保留。')
    pages['costs'].pop('calculation_revision',None)
    return pages
