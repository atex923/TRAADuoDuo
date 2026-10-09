from copy import deepcopy
from collections import defaultdict, deque
from datetime import date
from .domain import CalendarContext, decimal


def validate_page(page, value):
    if page == 'basic':
        if not value['name'].strip():
            raise ValueError('工程名稱不可空白')
        if decimal(value['days']) <= 0 or decimal(value['days']) > 36600:
            raise ValueError('工期須介於 0 與 36600 之間')
        if value['mode'] not in ('工作日', '日曆天'):
            raise ValueError('未知工期模式')
        for key in ('award', 'signed', 'start', 'finish'):
            if value[key]:
                date.fromisoformat(value[key])
        if value['start'] and value['finish'] and value['finish'] < value['start']:
            raise ValueError('預定竣工不可早於開工')
    else:
        seen = set()
        for row in value:
            day = date.fromisoformat(row[0])
            if day in seen:
                raise ValueError('同一表不可有重複日期')
            seen.add(day)
            if page == 'weather':
                if decimal(row[1]) < 0 or decimal(row[2]) < 0:
                    raise ValueError('晴雨扣除值不可為負數')


class EditSession:
    def __init__(self, pages):
        self.pages = deepcopy(pages)
        self.saved = deepcopy(pages)
        self.unlocked = set()
        self.history = defaultdict(lambda: deque(maxlen=10))

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
            {date.fromisoformat(r[0]): (r[1], r[2], r[3]) for r in self.pages['weather']})
