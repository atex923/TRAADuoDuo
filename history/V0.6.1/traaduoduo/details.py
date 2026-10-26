"""Backward-compatible page defaults and warranty dates."""
from copy import deepcopy
from datetime import date
import calendar
from .finance import normalize_costs
from .billing import normalize_billing
STATES = ['預算編製','規劃中','招標中','施工中','停工中','復工中','竣工前變更','竣工查驗','初驗中','驗收中','竣工辦理','決算中','結案中','保固中','移交管理單位中','保固期滿']
EXTRA_BASIC = dict(status='規劃中', description='', workday_finish='', calendar_finish='', actual_finish='', initial_days='', initial_expected='', initial_actual='', acceptance_days='', acceptance_expected='', acceptance_actual='', warranty_years='', warranty_end='', settlement='', warranty_note='')
GUARANTEES = dict(bid_amount='', difference_amount='', performance_amount='', performance_manual=False, performance_rate='10', performance_posted='', performance_form='', warranty_amount='', warranty_manual=False, warranty_rate='3', warranty_posted='', warranty_form='', refund_amount='', inspection='', refunded='')

def warranty_end(day, years):
    if not day or years == '':
        return ''
    start = date.fromisoformat(day)
    value = int(years)
    if value < 0 or value > 100:
        raise ValueError('保固年限須介於 0 至 100 年')
    year = start.year + value
    return date(year, start.month, min(start.day, calendar.monthrange(year,start.month)[1])).isoformat()

def normalize_pages(pages):
    result = deepcopy(pages)
    result['basic'] = dict(EXTRA_BASIC, **result['basic'])
    if result['basic']['mode'] == '工作天':
        result['basic']['mode'] = '工作日'
    result['guarantees'] = dict(GUARANTEES, **result.get('guarantees', {}))
    for prefix in ('performance','warranty'):
        result['guarantees'].setdefault(prefix+'_auto_amount','')
    result['costs']=normalize_costs(result.get('costs',{}))
    result['weather']=[list(row)+(['1' if str(row[3]).strip()=='-1' else '0'] if len(row)==4 else []) for row in result.get('weather',[])]
    result.setdefault('bids',[])
    from .advanced_data import normalize_extra
    return normalize_extra(normalize_billing(result))
