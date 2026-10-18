"""Pure models and legacy-compatible calculation services. No GUI imports."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import re


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('數值必須為有限數字')
    return result


def money(value):
    return decimal(value).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP).quantize(
        Decimal('.01'), rounding=ROUND_HALF_UP)


@dataclass
class CalendarContext:
    mode: str = '工作日'
    holidays: set = field(default_factory=set)
    makeup: set = field(default_factory=set)
    railway: set = field(default_factory=set)
    weather: dict = field(default_factory=dict)


def calculate_day(day, context):
    if context.mode not in ('工作日', '日曆天'):
        raise ValueError('未知工期模式')
    if day in context.railway:
        return Decimal(0), '鐵路輸運停工'
    weather = context.weather.get(day, ('0', '0', '', '0'))
    morning, afternoon, note = weather[:3]
    no_count = weather[3] if len(weather)>3 else '0'
    if decimal(no_count or '0') == 1:
        return Decimal(0), '不計工期'
    if note.strip() == '-1':
        return Decimal(0), '晴雨備註 -1：不計工期'
    base = Decimal(int(context.mode == '日曆天' or day.weekday() < 5))
    reasons = ['日曆天' if context.mode == '日曆天' else ('平日' if base else '週末')]
    if day in context.makeup:
        base = Decimal(1)
        reasons.append('補班')
    if day in context.holidays:
        return Decimal(0), '假期：不計工期（優先於補班）'
    morning, afternoon = decimal(morning), decimal(afternoon)
    if morning < 0 or afternoon < 0:
        raise ValueError('晴雨扣除值不可小於零')
    deduction = Decimal(1) if morning >= 1 else Decimal(int(morning > 0)) + Decimal('.5') * int(afternoon > 0)
    if deduction:
        reasons.append(f'晴雨扣除 {deduction}')
    return max(Decimal(0), base - deduction), '、'.join(reasons)


def count_workdays(start, end, context):
    if (end - start).days > 36600:
        raise ValueError('計算範圍不可超過 100 年')
    total = Decimal(0)
    while start <= end:
        total += calculate_day(start, context)[0]
        start += timedelta(days=1)
    return total


def calculate_finish(start, days, context):
    remaining = decimal(days)
    if remaining <= 0 or remaining != remaining.to_integral_value():
        raise ValueError('工期須為正整數')
    if context.mode == '日曆天':
        return start + timedelta(days=int(remaining)-1)
    for offset in range(36600):
        current = start + timedelta(days=offset)
        remaining -= calculate_day(current, context)[0]
        if remaining <= 0:
            return current
    raise ValueError('100 年內無法完成，請檢查工期設定')


@dataclass
class BudgetItem:
    code: str
    quantity: Decimal = Decimal(1)
    unit_price: Decimal = Decimal(0)
    parent_id: str | None = None
    kind: str = 'rollup'  # rollup: sum children; analysis: sum children * quantity


def normalize_code(code):
    result = re.sub(r'\s+', '', str(code)).upper()
    if not result:
        raise ValueError('項次不可空白')
    return result


def resolve_parent(code, candidates):
    valid = [p for p in candidates if p != code and code.startswith(p)]
    return max(valid, key=len) if valid else None


def legacy_in_view(code, view):
    code = normalize_code(code)
    if view == 'summary':
        return 1 <= len(code) <= 3
    if view == 'detail':
        return code != '0' and 1 <= len(code) <= 5
    if view == 'analysis':
        return len(code) >= 6
    raise ValueError('未知 legacy 檢視')


def calculate_budget(items):
    nodes = {}
    for item in items:
        code = normalize_code(item.code)
        if code in nodes:
            raise ValueError(f'重複項次：{code}')
        if item.kind not in ('rollup', 'analysis'):
            raise ValueError('未知父項計算方式')
        nodes[code] = item
    children = {code: [] for code in nodes}
    for code, item in nodes.items():
        parent = normalize_code(item.parent_id) if item.parent_id is not None else resolve_parent(code, nodes)
        if parent is not None:
            if parent not in nodes:
                raise ValueError(f'找不到父項：{parent}')
            children[parent].append(code)
    result, trace, visiting = {}, {}, set()

    def visit(code):
        if code in visiting:
            raise ValueError('階層循環')
        if code in result:
            return result[code]
        visiting.add(code)
        item = nodes[code]
        if children[code]:
            subtotal = sum((visit(child) for child in children[code]), Decimal(0))
            value = subtotal * decimal(item.quantity) if item.kind == 'analysis' else subtotal
            trace[code] = {'children': children[code], 'subtotal': str(subtotal), 'mode': item.kind}
        else:
            value = decimal(item.quantity) * decimal(item.unit_price)
            trace[code] = {'quantity': str(item.quantity), 'unit_price': str(item.unit_price), 'mode': 'leaf'}
        result[code] = money(value)
        visiting.remove(code)
        return result[code]
    for code in nodes:
        visit(code)
    return result, trace


def rate_amount(base, rate):
    return money(decimal(base) * decimal(rate))
