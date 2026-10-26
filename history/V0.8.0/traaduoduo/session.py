from copy import deepcopy
from collections import defaultdict, deque
from datetime import date
from .domain import CalendarContext, decimal
from .details import STATES, GUARANTEES, warranty_end
from .finance import validate_costs,validate_bids,synchronize
from .billing import PAYMENT_KEYS,validate_billing


def validate_page(page, value):
    from .advanced_data import EXTRA_KEYS,validate_extra
    if page in EXTRA_KEYS:
        validate_extra(page,value)
    elif page in PAYMENT_KEYS:
        validate_billing(page,value)
    elif page=='costs':
        validate_costs(value)
    elif page=='bids':
        validate_bids(value)
    elif page == 'basic':
        if not value['name'].strip():
            raise ValueError('工程名稱不可空白')
        days=decimal(value['days'] or '0')
        if days < 0 or days > 36600 or days!=days.to_integral_value():
            raise ValueError('工期須介於 0 與 36600 之間；0 表示尚未設定')
        if value['mode'] not in ('工作日', '日曆天'):
            raise ValueError('未知工期模式')
        for key in ('award', 'signed', 'start', 'finish'):
            if value[key]:
                date.fromisoformat(value[key])
        # The hidden legacy finish is historical evidence, not the new deadline.
        if value.get('status','規劃中') not in STATES:
            raise ValueError('未知執行狀態')
        for key in ('workday_finish','calendar_finish','actual_finish','initial_expected','initial_actual','acceptance_expected','acceptance_actual','warranty_end','settlement'):
            if value.get(key):
                date.fromisoformat(value[key])
        for key in ('initial_days','acceptance_days','warranty_years'):
            if value.get(key,'') != '' and (not str(value[key]).isdigit() or int(value[key]) > (100 if key == 'warranty_years' else 36600)):
                raise ValueError('期限須為範圍內非負整數')
        warranty_end(value.get('acceptance_actual',''),value.get('warranty_years',''))
    elif page == 'guarantees':
        for key, default in GUARANTEES.items():
            data = value.get(key,default)
            if key.endswith('_amount') and data != '' and decimal(data) < 0:
                raise ValueError('保證金不可為負數')
            if key.endswith('_rate') and not 0 <= decimal(data) <= 100:
                raise ValueError('比例須介於 0 與 100%')
            if key.endswith('_manual') and not isinstance(data,bool):
                raise ValueError('手動覆寫須為勾選值')
            if (key.endswith('_posted') or key in ('inspection','refunded')) and data:
                date.fromisoformat(data)
    else:
        seen = set()
        for row in value:
            day = date.fromisoformat(row[0])
            if day in seen:
                raise ValueError('同一表不可有重複日期')
            seen.add(day)
            if page == 'weather':
                if len(row) not in (4,5):
                    raise ValueError('晴雨欄位不完整')
                if decimal(row[1]) < 0 or decimal(row[2]) < 0:
                    raise ValueError('晴雨扣除值不可為負數')
                if len(row)>4 and decimal(row[4] or '0') not in (0,1):
                    raise ValueError('不計工期須為 0 或 1')


class EditSession:
    def __init__(self, pages):
        from .details import normalize_pages
        self.pages = normalize_pages(pages)
        self.saved = deepcopy(self.pages)
        self.unlocked = set()
        self.history = defaultdict(lambda: deque(maxlen=10))

    def reconcile(self):
        validate_costs(self.pages['costs'])
        validate_bids(self.pages['bids'])
        self.pages=synchronize(self.pages)

    def change(self, page, value):
        if page not in self.unlocked:
            raise ValueError('此頁已鎖定')
        if value != self.pages[page]:
            self.history[page].append(deepcopy(self.pages[page]))
            self.pages[page] = deepcopy(value)

    def undo(self, page):
        if page not in self.unlocked:
            raise ValueError('請先解鎖此頁')
        if self.history[page]:
            self.pages[page] = self.history[page].pop()

    def dirty(self):
        return {key: deepcopy(value) for key, value in self.pages.items() if value != self.saved[key]}

    def validate(self):
        for key, value in self.pages.items():
            validate_page(key, value)

    def calendar(self):
        self.validate()
        return CalendarContext(self.pages['basic']['mode'],
            {date.fromisoformat(r[0]) for r in self.pages['holidays']},
            {date.fromisoformat(r[0]) for r in self.pages['makeup']},
            {date.fromisoformat(r[0]) for r in self.pages['railway']},
            {date.fromisoformat(r[0]): tuple(r[1:]) for r in self.pages['weather']})
