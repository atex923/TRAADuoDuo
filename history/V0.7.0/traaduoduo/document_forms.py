"""Document metadata and local view preferences, independent of asset identity."""
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QFormLayout,QVBoxLayout,QLineEdit,QPlainTextEdit,QSpinBox,QComboBox,QDialogButtonBox,QMessageBox,QCheckBox,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QAbstractItemView
from .forms import DateField
from .tracking import DOCUMENT_COLUMNS

class DocumentForms:
    def asset_column(self,key,field):return [k for k,v in self.asset_ui[key]['fields']].index(field)

    def edit_document(self,row):
        if not self.session or 'documents' not in self.session.unlocked:return
        dialog=QDialog(self);dialog.setWindowTitle('文件資料與重新連結');form=QFormLayout(dialog);fields={}
        for key,title in [('number','項次'),('name','文件名稱'),('document_no','文件文號'),('document_date','文件日期'),('source','來源路徑'),('note','備註')]:
            if key=='number':field=QSpinBox();field.setRange(1,999999999);field.setValue(row[key])
            elif key=='document_date':field=DateField();field.setText(row[key])
            elif key=='note':field=QPlainTextEdit(row[key])
            else:field=QLineEdit(row[key])
            field.setObjectName('document-'+key);fields[key]=field;form.addRow(title,field)
        category=QComboBox();category.addItem('未分類','')
        for c in self.session.pages['documents']['categories']:category.addItem(c['name'],c['id'])
        category.setCurrentIndex(max(0,category.findData(row['category'])));form.addRow('分類',category)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);form.addRow(buttons);buttons.rejected.connect(dialog.reject)
        def save():
            result=deepcopy(row)
            for key,field in fields.items():result[key]=field.value() if key=='number' else field.toPlainText() if key=='note' else field.text().strip()
            result['category']=category.currentData()
            if not result['name']:QMessageBox.warning(dialog,'資料不完整','請填寫文件名稱');return
            if result['source']!=row['source'] and not Path(result['source']).is_file():QMessageBox.warning(dialog,'重新連結失敗','來源檔不存在，原連結未改動。');return
            try:self.replace_asset('documents',result)
            except ValueError as exc:QMessageBox.warning(dialog,'文件欄位錯誤',str(exc));return
            dialog.accept()
        buttons.accepted.connect(save);dialog.resize(700,550);dialog.exec()

    def set_document_columns(self,hidden):
        hidden=set(hidden)
        if {'number','name'}<=hidden:raise ValueError('項次與文件名稱至少保留一欄')
        for i,(key,title) in enumerate(DOCUMENT_COLUMNS):
            self.asset_ui['documents']['table'].setColumnHidden(i,key in hidden);self.settings.setValue('documents/hidden/'+key,key in hidden)

    def choose_document_columns(self):
        dialog=QDialog(self);dialog.setWindowTitle('文件庫顯示欄位');layout=QVBoxLayout(dialog);checks={}
        for i,(key,title) in enumerate(DOCUMENT_COLUMNS):
            check=QCheckBox(title);check.setChecked(not self.asset_ui['documents']['table'].isColumnHidden(i));checks[key]=check;layout.addWidget(check)
        all_button=QPushButton('全部顯示');all_button.clicked.connect(lambda:[c.setChecked(True) for c in checks.values()]);layout.addWidget(all_button)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.RestoreDefaults);layout.addWidget(buttons);buttons.rejected.connect(dialog.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(lambda:[c.setChecked(True) for c in checks.values()])
        def accept():
            try:self.set_document_columns([key for key,c in checks.items() if not c.isChecked()])
            except ValueError as exc:QMessageBox.warning(dialog,'請保留識別欄',str(exc));return
            dialog.accept()
        buttons.accepted.connect(accept);dialog.exec()

    def apply_document_numbering(self,ids):
        ui=self.asset_ui['documents'];value=deepcopy(self.session.pages['documents'])
        if ui['filter'] or len(ids)!=len(value['rows']) or set(ids)!={r['id'] for r in value['rows']}:raise ValueError('請在全部文件檢視完整清單後重編')
        numbers={rid:i+1 for i,rid in enumerate(ids)}
        for row in value['rows']:row['number']=numbers[row['id']]
        self.commit_extra('documents',value);ui['sort'].setCurrentIndex(3)

    def renumber_documents(self):
        ui=self.asset_ui['documents']
        if ui['filter']:QMessageBox.information(self,'請切換全部文件','分類篩選中不可重新編項次。');return
        table=ui['table'];ids=[table.item(i,0).data(Qt.ItemDataRole.UserRole) for i in range(table.rowCount())]
        rows={r['id']:r for r in self.session.pages['documents']['rows']}
        box=QDialog(self);box.setWindowTitle('確認重新編項次');layout=QVBoxLayout(box);layout.addWidget(QLabel(f'共 {len(ids)} 筆，依目前顯示順序重編；不改檔案名稱或連結，可回復。'))
        preview=QTableWidget(len(ids),3);preview.setHorizontalHeaderLabels(['原項次','新項次','文件名稱']);preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);preview.setColumnWidth(2,360);layout.addWidget(preview)
        for i,rid in enumerate(ids):
            for j,value in enumerate([rows[rid]['number'],i+1,rows[rid]['name']]):preview.setItem(i,j,QTableWidgetItem(str(value)))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(box.accept);buttons.rejected.connect(box.reject);buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True);layout.addWidget(buttons);box.resize(700,440)
        if box.exec()==QDialog.DialogCode.Accepted:self.apply_document_numbering(ids)
