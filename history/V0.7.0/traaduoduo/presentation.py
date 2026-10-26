"""Local presentation only: formatted money never changes stored precision."""
from decimal import Decimal, ROUND_HALF_UP
from PySide6.QtWidgets import QLineEdit


def money(value, places=2):
    if value is None or value=='': return ''
    number=Decimal(str(value).replace(',',''))
    return format(number.quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP),f',.{places}f')


class MoneyField(QLineEdit):
    def __init__(self, places=2):
        super().__init__(); self.places=places; self.raw=''; self.edited=False
        self.textEdited.connect(self.mark_edited)

    def mark_edited(self): self.edited=True

    def value(self):
        return self.text().replace(',','').strip() if self.edited else self.raw

    def setText(self, text):
        self.raw=('' if text is None else str(text)).replace(',','').strip(); self.edited=False
        try: display=money(self.raw,self.places)
        except (ValueError,ArithmeticError): display=str(text)
        super().setText(display)

    def clear(self): self.setText('')

    def focusInEvent(self,event):
        if not self.isReadOnly():
            self.raw=self.value(); self.edited=False; super().setText(self.raw)
        super().focusInEvent(event)

    def focusOutEvent(self,event):
        self.setText(self.value()); super().focusOutEvent(event)


def compact_field(field):
    field.ensurePolished()
    padding=round(3*field.logicalDpiY()/72)
    field.setFixedHeight(field.fontMetrics().height()+padding)
    field.setStyleSheet(field.styleSheet()+';padding-top:0px;padding-bottom:0px;')
