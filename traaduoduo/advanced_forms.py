"""AA revisions, diary, document and photo libraries in the unified project."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import datetime
from pathlib import Path
import uuid
from PySide6.QtCore import Qt,QDate,QSize,Signal,QTimer
from PySide6.QtGui import QDesktopServices,QImageReader,QPixmap,QIcon,QTransform,QTextDocument
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QSplitter,QTabWidget,QTreeWidget,QTreeWidgetItem,QPushButton,QComboBox,QLabel,QFileDialog,QMessageBox,QInputDialog,QDialog,QDialogButtonBox,QSpinBox,QCalendarWidget,QTableWidgetItem,QPlainTextEdit,QLineEdit,QScrollArea,QStyledItemDelegate,QAbstractItemView,QStackedWidget,QSizePolicy,QProgressDialog)
from .forms import ProjectTable
from .aa_import import HEADERS,TABLES,inspect_aa,sheets,format_decimal
from .advanced_data import EXTRA_KEYS,validate_extra
from .asset_store import new_asset,available_path,inventory,portable_backup,restore_backup,sha
from .pdf_reader import PdfReader

class FileTable(ProjectTable):
    filesDropped=Signal(object)
    def __init__(self,*args):
        super().__init__(*args); self.setAcceptDrops(True)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dragMoveEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dropEvent(self,event):
        self.filesDropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]); event.acceptProposedAction()

class DiaryDelegate(QStyledItemDelegate):
    def createEditor(self,parent,option,index):
        editor=QPlainTextEdit(parent)
        editor.textChanged.connect(lambda:self.parent().setRowHeight(index.row(),max(70,int(editor.document().size().height())+20)))
        return editor
    def setEditorData(self,editor,index):editor.setPlainText(str(index.data() or ''))
    def setModelData(self,editor,model,index):model.setData(index,editor.toPlainText())

class AdvancedForms:
    @staticmethod
    def toolstrip(layout):
        area=QScrollArea();area.setWidgetResizable(True);area.setFixedHeight(64)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body=QWidget();tools=QHBoxLayout(body);tools.setContentsMargins(0,0,0,0)
        area.setWidget(body);layout.addWidget(area);return tools

    def build_advanced(self):
        self.extra_buttons={key:[] for key in EXTRA_KEYS}; self.asset_ui={}; self.extra_loading=False
        self.thumbnail_pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='photo-thumbnails'); self.thumbnail_jobs=[]
        self.thumbnail_timer=QTimer(self); self.thumbnail_timer.setInterval(80); self.thumbnail_timer.timeout.connect(self.poll_thumbnails); self.thumbnail_timer.start()
        self.build_details(); self.build_diary()
        for key,title in [('documents','文件庫'),('photos','照片庫')]:self.build_assets(key,title)

    def extra_button(self,key,layout,text,callback):
        button=QPushButton(text); button.clicked.connect(callback); layout.addWidget(button); self.extra_buttons[key].append(button); return button

    def commit_extra(self,key,value,refresh=True):
        if not self.session or key not in self.session.unlocked:raise ValueError('請先解鎖此頁')
        validate_extra(key,value); self.session.change(key,value)
        if refresh:self.populate_advanced(key)
        self.changed()

    def build_details(self):
        outer,body=self.edit_page('details'); self.tabs.addTab(outer,'詳細表')
        layout=QVBoxLayout(body); self.detail_tabs=QTabWidget(); layout.addWidget(self.detail_tabs); self.detail_ui={}
        for key,title in TABLES.items():
            page=QWidget(); self.detail_tabs.addTab(page,title); column=QVBoxLayout(page); tools=self.toolstrip(column)
            self.extra_button('details',tools,'依序匯入 Excel',lambda checked=False,k=key:self.choose_aa(k))
            versions=QComboBox(); versions.setMinimumWidth(200); tools.addWidget(versions)
            levels=QComboBox(); levels.addItems(['全部層級','單價分析層']+['顯示至 '+str(i)+' 碼' for i in range(1,16)]); tools.addWidget(levels)
            levels.setCurrentIndex(int(self.settings.value('details/'+key+'/level',0)))
            levels.currentIndexChanged.connect(lambda index,k=key:self.settings.setValue('details/'+k+'/level',index))
            for text,fn in [('展開',lambda checked=False,k=key:self.detail_ui[k]['tree'].expandAll()),('收合',lambda checked=False,k=key:self.detail_ui[k]['tree'].collapseAll()),('顯示欄位',lambda checked=False,k=key:self.choose_detail_columns(k))]:
                button=QPushButton(text); button.clicked.connect(fn); tools.addWidget(button)
            tree=QTreeWidget(); tree.setColumnCount(16); tree.setHeaderLabels(HEADERS); tree.setRootIsDecorated(True);tree.setTreePosition(2)
            tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); tree.setAlternatingRowColors(True); column.addWidget(tree)
            for i in range(16):tree.setColumnWidth(i,280 if i in (3,5,13,14,15) else 150)
            info=QLabel(); info.setWordWrap(True); column.addWidget(info)
            self.detail_ui[key]=dict(versions=versions,levels=levels,tree=tree,info=info)
            versions.currentIndexChanged.connect(lambda *_,k=key:self.populate_detail(k)); levels.currentIndexChanged.connect(lambda *_,k=key:self.populate_detail(k))
            tree.itemExpanded.connect(lambda item,k=key:self.remember_detail_expansion(k)); tree.itemCollapsed.connect(lambda item,k=key:self.remember_detail_expansion(k))

    def choose_aa(self,key):
        if not self.session or 'details' not in self.session.unlocked:return
        path,_=QFileDialog.getOpenFileName(self,'讀入'+TABLES[key],'','AA Excel (*.xlsx)')
        if not path:return
        try:
            sheet,ok=QInputDialog.getItem(self,'選擇工作表','工作表',sheets(path),0,False)
            if not ok:return
            header,ok=QInputDialog.getInt(self,'表頭位置','表頭列（第一列為 1）',1,1,100)
            if not ok:return
        except Exception as exc:QMessageBox.warning(self,'無法讀取 Excel',str(exc));return
        pid=self.store.project_id
        self.io(lambda:inspect_aa(path,sheet,header),lambda batch:self.show_aa_preview(key,batch,pid))

    def show_aa_preview(self,key,batch,pid):
        if not self.session or self.store.project_id!=pid:return
        dialog=QDialog(self); dialog.setWindowTitle('匯入預覽：'+TABLES[key]); layout=QVBoxLayout(dialog)
        title=QLabel(f"工程：{self.session.pages['basic']['name']}\n{batch['filename']}／{batch['sheet']}　{len(batch['rows'])} 筆／最長 {batch['max_length']} 碼\n新增獨立修訂版，不覆蓋既有資料。")
        title.setWordWrap(True); layout.addWidget(title)
        preview=ProjectTable(min(100,len(batch['rows'])),16); preview.setHorizontalHeaderLabels(HEADERS); preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i,row in enumerate(batch['rows'][:100]):
            for j,text in enumerate(row['values']):preview.setItem(i,j,QTableWidgetItem(text))
        layout.addWidget(preview); notes=QPlainTextEdit(); notes.setReadOnly(True); notes.setPlainText('\n'.join(batch['errors']+batch['warnings']) or '欄位與編碼檢查通過；數值為來源快取，不自動執行公式。'); layout.addWidget(notes)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not batch['errors'] and bool(batch['rows']))
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);dialog.resize(1120,700)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            existing=self.session.pages['details'][key]
            if any(b['sha256']==batch['sha256'] and b['sheet']==batch['sheet'] for b in existing):
                QMessageBox.warning(self,'相同來源已匯入','此表已有相同檔案與工作表，未重複新增。');return
            batch['name']=datetime.now().strftime('%Y-%m-%d %H:%M')+' '+batch['filename']
            value=deepcopy(self.session.pages['details']);value[key].append(batch);self.commit_extra('details',value)

    def populate_detail(self,key):
        if self.extra_loading:return
        ui=self.detail_ui[key];tree=ui['tree'];tree.blockSignals(True);tree.clear()
        batches=self.session.pages['details'][key] if self.session else []
        if not batches:ui['info'].setText('尚無資料；匯入後保留來源公式、快取與額外欄位。');tree.blockSignals(False);return
        index=max(0,min(ui['versions'].currentIndex(),len(batches)-1));batch=batches[index]; nodes={}; mode=ui['levels'].currentIndex()
        allowed={r['id'] for r in batch['rows'] if mode==0 or (mode==1 and r['analysis']) or (mode>=2 and (r['length']<=mode-1 or (r['leaf'] and r['length']<batch['max_length'])))}
        for row in batch['rows']:
            if row['id'] not in allowed:continue
            values=list(row['values'])
            for col in (10,11):
                try:values[col]=format_decimal(values[col])
                except (ValueError,ArithmeticError):pass
            item=QTreeWidgetItem(values);item.setData(0,Qt.ItemDataRole.UserRole,row['id'])
            for col in (9,10,11,12):item.setTextAlignment(col,Qt.AlignmentFlag.AlignRight)
            item.setToolTip(3,'來源第 '+str(row['source_row'])+' 列；'+('單價分析層' if row['analysis'] else '一般項目'))
            parent=nodes.get(row['parent_id'])
            if parent:parent.addChild(item)
            else:tree.addTopLevelItem(item)
            nodes[row['id']]=item
        saved=self.settings.value('details/'+key+'/expanded',None)
        if saved is None:tree.expandToDepth(1)
        else:
            import json
            try:
                for rid in json.loads(saved):
                    if rid in nodes:nodes[rid].setExpanded(True)
            except (ValueError,TypeError):pass
        ui['info'].setText(f"{len(batch['rows'])} 筆／顯示 {len(nodes)} 筆／最長 {batch['max_length']} 碼；單價分析不重複計入工程總額。\n"+'；'.join(batch['warnings']))
        tree.blockSignals(False)

    def remember_detail_expansion(self,key):
        import json
        tree=self.detail_ui[key]['tree']; expanded=[]
        def visit(item):
            if item.isExpanded():expanded.append(item.data(0,Qt.ItemDataRole.UserRole))
            for i in range(item.childCount()):visit(item.child(i))
        for i in range(tree.topLevelItemCount()):visit(tree.topLevelItem(i))
        self.settings.setValue('details/'+key+'/expanded',json.dumps(expanded))

    def choose_detail_columns(self,key):
        from PySide6.QtWidgets import QCheckBox
        dialog=QDialog(self);dialog.setWindowTitle('顯示欄位');layout=QVBoxLayout(dialog);checks=[];tree=self.detail_ui[key]['tree']
        for i,label in enumerate(HEADERS):
            check=QCheckBox(label);check.setChecked(not tree.isColumnHidden(i));checks.append(check);layout.addWidget(check)
        restore=QPushButton('全部顯示');restore.clicked.connect(lambda:[c.setChecked(True) for c in checks]);layout.addWidget(restore)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            for i,check in enumerate(checks):tree.setColumnHidden(i,not check.isChecked());self.settings.setValue(f'details/{key}/hidden/{i}',not check.isChecked())

    def build_diary(self):
        outer,body=self.edit_page('diary');self.tabs.addTab(outer,'大事記');layout=QVBoxLayout(body);tools=self.toolstrip(layout)
        self.extra_button('diary',tools,'新增大事記',self.add_diary);self.extra_button('diary',tools,'移除',self.remove_diary);tools.addStretch()
        self.diary_table=ProjectTable(0,4);self.diary_table.setHorizontalHeaderLabels(['項次','日期','說明','備註']);self.diary_table.setWordWrap(True)
        self.diary_table.setColumnWidth(0,80);self.diary_table.setColumnWidth(1,155)
        for col in (2,3):self.diary_table.setColumnWidth(col,self.fontMetrics().horizontalAdvance('中')*50);self.diary_table.setItemDelegateForColumn(col,DiaryDelegate(self.diary_table))
        self.diary_table.itemChanged.connect(self.capture_diary);self.diary_table.horizontalHeader().sectionResized.connect(lambda *_:self.resize_diary());layout.addWidget(self.diary_table)

    def add_diary(self):
        if not self.session or 'diary' not in self.session.unlocked:return
        dialog=QDialog(self);dialog.setWindowTitle('新增大事記');layout=QVBoxLayout(dialog)
        number=QSpinBox();number.setRange(1,999999);number.setValue(max((r['number'] for r in self.session.pages['diary']),default=0)+1);layout.addWidget(QLabel('項次'));layout.addWidget(number)
        calendar=QCalendarWidget();calendar.setSelectedDate(QDate.currentDate());layout.addWidget(calendar)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            rows=deepcopy(self.session.pages['diary']);row=dict(id=uuid.uuid4().hex,number=number.value(),date=calendar.selectedDate().toString('yyyy-MM-dd'),description='',note='');rows.append(row)
            try:self.commit_extra('diary',rows)
            except ValueError as exc:QMessageBox.warning(self,'無法新增',str(exc));return
            for i,r in enumerate(sorted(rows,key=lambda r:r['number'])):
                if r['id']==row['id']:self.diary_table.setCurrentCell(i,2);self.diary_table.editItem(self.diary_table.item(i,2));break

    def capture_diary(self,item):
        if self.extra_loading or not self.session or 'diary' not in self.session.unlocked:return
        rid=item.data(Qt.ItemDataRole.UserRole);rows=deepcopy(self.session.pages['diary'])
        for row in rows:
            if row['id']==rid:row[['number','date','description','note'][item.column()]]=item.text()
        try:
            for row in rows:row['number']=int(row['number'])
            self.commit_extra('diary',rows,False);self.resize_diary()
        except ValueError as exc:QMessageBox.warning(self,'大事記欄位錯誤',str(exc));self.populate_advanced('diary')

    def resize_diary(self):
        self.diary_table.resizeRowsToContents()
        for row in range(self.diary_table.rowCount()):self.diary_table.setRowHeight(row,max(42,self.diary_table.rowHeight(row)))

    def remove_diary(self):
        item=self.diary_table.currentItem()
        if not item:return
        if QMessageBox.question(self,'移除大事記','移除選取紀錄？可使用回復動作復原。')==QMessageBox.StandardButton.Yes:self.commit_extra('diary',[r for r in self.session.pages['diary'] if r['id']!=item.data(Qt.ItemDataRole.UserRole)])

    def build_assets(self,key,title):
        outer,body=self.edit_page(key);self.tabs.addTab(outer,title);layout=QVBoxLayout(body);tools=self.toolstrip(layout)
        for text,fn in [('加入檔案',lambda:self.choose_assets(key)),('新增分類',lambda:self.add_category(key)),('編輯分類',lambda:self.edit_category(key)),('編輯／重新連結',lambda:self.edit_asset(key)),('移除清單',lambda:self.remove_asset(key))]:self.extra_button(key,tools,text,fn)
        self.extra_button(key,tools,'更新庫存',lambda:self.update_inventory(key))
        sort=QComboBox();sort.addItems(['手動順序','名稱排序','拍攝日期排序']);sort.setCurrentIndex(int(self.settings.value('assets/'+key+'/sort',0)));tools.addWidget(sort)
        self.extra_button(key,tools,'上移',lambda:self.move_asset(key,-1));self.extra_button(key,tools,'下移',lambda:self.move_asset(key,1))
        for text,fn in [('開啟',lambda:self.open_asset(key)),('完整備份',self.backup_library),('還原備份',self.restore_library)]:
            button=QPushButton(text);button.clicked.connect(fn);tools.addWidget(button)
        splitter=QSplitter();layout.addWidget(splitter);categories=QTreeWidget();categories.setHeaderLabel('分類');splitter.addWidget(categories)
        table=FileTable(0,5);table.setHorizontalHeaderLabels(['文件名稱' if key=='documents' else '照片名稱','庫存檔','分類','狀態','備註']);table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);splitter.addWidget(table)
        for col,width in enumerate([260,90,140,180,250]):table.setColumnWidth(col,width)
        preview=QStackedWidget();splitter.addWidget(preview);info=QPlainTextEdit();info.setReadOnly(True);preview.addWidget(info);photo=QLabel('選擇檔案以預覽');photo.setAlignment(Qt.AlignmentFlag.AlignCenter);photo.setWordWrap(True);preview.addWidget(photo);pdf=PdfReader();preview.addWidget(pdf);splitter.setSizes([170,500,400])
        self.asset_ui[key]=dict(categories=categories,table=table,preview=preview,info=info,photo=photo,pdf=pdf,selected=None,filter='',sort=sort,reading=False)
        sort.currentIndexChanged.connect(lambda index,k=key:(self.settings.setValue('assets/'+k+'/sort',index),self.populate_asset_rows(k)))
        photo.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        splitter.setChildrenCollapsible(False)
        table.filesDropped.connect(lambda paths,k=key:self.add_assets(k,paths));table.itemSelectionChanged.connect(lambda k=key:self.preview_asset(k));table.itemChanged.connect(lambda item,k=key:self.stock_changed(k,item))
        categories.currentItemChanged.connect(lambda item,old,k=key:self.filter_assets(k,item));pdf.annotated.connect(lambda notes,k=key:self.asset_annotations(k,notes));pdf.positionChanged.connect(lambda page,zoom,k=key:self.reader_position(k,page,zoom))

    def selected_asset(self,key):
        item=self.asset_ui[key]['table'].currentItem()
        return next((r for r in self.session.pages[key]['rows'] if item and r['id']==item.data(Qt.ItemDataRole.UserRole)),None) if self.session else None

    def choose_assets(self,key):
        paths,_=QFileDialog.getOpenFileNames(self,'加入'+('文件' if key=='documents' else '照片'))
        if paths:self.add_assets(key,paths)

    def add_assets(self,key,paths):
        if not self.session or key not in self.session.unlocked:QMessageBox.information(self,'頁面已鎖定','請先解鎖此頁再拖入檔案。');return
        category=self.asset_ui[key]['filter'];pid=self.store.project_id
        def finished(rows):
            if self.store.project_id!=pid:return
            value=deepcopy(self.session.pages[key]);digests={r['sha256'] for r in value['rows']}
            if any(r['sha256'] in digests for r in rows) and QMessageBox.question(self,'相同內容','清單已有相同內容，仍新增連結？')!=QMessageBox.StandardButton.Yes:return
            value['rows'].extend(rows);self.commit_extra(key,value)
        self.io(lambda:[new_asset(p,category) for p in paths],finished)

    def filter_assets(self,key,item):
        if self.extra_loading:return
        self.asset_ui[key]['filter']=item.data(0,Qt.ItemDataRole.UserRole) if item else '';self.populate_asset_rows(key)

    def add_category(self,key):
        name,ok=QInputDialog.getText(self,'新增分類','分類名稱（建立於選取分類下）')
        if ok and name.strip():
            value=deepcopy(self.session.pages[key]);value['categories'].append(dict(id=uuid.uuid4().hex,name=name.strip(),parent=self.asset_ui[key]['filter']));self.commit_extra(key,value)

    def edit_category(self,key):
        category=self.asset_ui[key]['filter'];value=deepcopy(self.session.pages[key]);item=next((c for c in value['categories'] if c['id']==category),None)
        if not item:return
        name,ok=QInputDialog.getText(self,'編輯分類','分類名稱',text=item['name'])
        if not ok or not name.strip():return
        choices=[('', '最上層')]+[(c['id'],c['name']) for c in value['categories'] if c['id']!=category]
        parent,ok=QInputDialog.getItem(self,'移動分類','上層分類',[c[1] for c in choices],0,False)
        if not ok:return
        item.update(name=name.strip(),parent=choices[[c[1] for c in choices].index(parent)][0])
        try:self.commit_extra(key,value)
        except ValueError as exc:QMessageBox.warning(self,'無法移動分類',str(exc))

    def stock_changed(self,key,item):
        if self.extra_loading or item.column()!=1 or not self.session or key not in self.session.unlocked:return
        rid=item.data(Qt.ItemDataRole.UserRole);row=next(r for r in self.session.pages[key]['rows'] if r['id']==rid)
        wanted=item.checkState()==Qt.CheckState.Checked
        if wanted==row['stock']:return
        if not wanted:
            value=deepcopy(self.session.pages[key]);next(r for r in value['rows'] if r['id']==rid)['stock']=False;self.commit_extra(key,value);return
        self.inventory_asset(key,row)
        # The checkbox is not successful until the worker verifies the copy.
        self.populate_asset_rows(key)

    def replace_asset(self,key,row):
        value=deepcopy(self.session.pages[key]);value['rows']=[row if r['id']==row['id'] else r for r in value['rows']];self.commit_extra(key,value)

    def inventory_asset(self,key,row):
        if self.future is not None:return
        pid=self.store.project_id;database=self.store.path;cancel=Event()
        progress=QProgressDialog('正在比對既存內容並驗證庫存檔…','取消',0,0,self)
        progress.setWindowTitle('庫存內容查重');progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModality.WindowModal);progress.canceled.connect(cancel.set)
        self._asset_progress=progress
        def complete(result):
            if self.store.project_id!=pid:return
            self.replace_asset(key,result)
            self.message.setText('已存在，未重複複製（重用 1 筆）' if result.get('inventory_reused') else '庫存檔複製與校驗完成（新增 1 筆）')
        self.io(lambda:inventory(database,pid,key,deepcopy(row),cancel),complete)
        progress.show()

    def update_inventory(self,key):
        row=self.selected_asset(key)
        if not row:return
        if QMessageBox.question(self,'更新庫存','建立新庫存版本，保留既有備份，不修改來源檔？')!=QMessageBox.StandardButton.Yes:return
        self.inventory_asset(key,row)

    def move_asset(self,key,step):
        ui=self.asset_ui[key];row=self.selected_asset(key)
        if not row:return
        if ui['sort'].currentIndex()!=0:
            QMessageBox.information(self,'手動順序','請先切換為手動順序。');return
        target=ui['table'].currentRow()+step
        if target<0 or target>=ui['table'].rowCount():return
        other=ui['table'].item(target,0).data(Qt.ItemDataRole.UserRole);value=deepcopy(self.session.pages[key]);indices={r['id']:i for i,r in enumerate(value['rows'])}
        a,b=indices[row['id']],indices[other];value['rows'][a],value['rows'][b]=value['rows'][b],value['rows'][a];self.commit_extra(key,value)

    def edit_asset(self,key):
        row=self.selected_asset(key)
        if not row:return
        dialog=QDialog(self);dialog.setWindowTitle('文件資料與重新連結');layout=QVBoxLayout(dialog);name=QLineEdit(row['name']);name.setObjectName('asset-name');layout.addWidget(QLabel('顯示名稱'));layout.addWidget(name)
        category=QComboBox();category.addItem('未分類','')
        for c in self.session.pages[key]['categories']:category.addItem(c['name'],c['id'])
        category.setCurrentIndex(max(0,category.findData(row['category'])));layout.addWidget(category)
        source=QLineEdit(row['source']);source.setObjectName('asset-source');layout.addWidget(QLabel('來源路徑（改為新檔案即重新連結）'));layout.addWidget(source)
        note=QPlainTextEdit(row['note']);note.setObjectName('asset-note');layout.addWidget(QLabel('摘要／備註'));layout.addWidget(note)
        rotate=QComboBox();rotate.addItems(['0°','90°','180°','270°']);rotate.setCurrentIndex(row.get('rotation',0)//90)
        if key=='photos':layout.addWidget(QLabel('顯示旋轉（不改原檔）'));layout.addWidget(rotate)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.resize(650,450)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            result=deepcopy(row);result.update(name=name.text().strip() or row['name'],category=category.currentData(),source=source.text().strip(),note=note.toPlainText(),rotation=rotate.currentIndex()*90)
            if result['source']!=row['source'] and not Path(result['source']).is_file():QMessageBox.warning(self,'重新連結失敗','來源檔不存在，原連結未改動。');return
            self.replace_asset(key,result)

    def remove_asset(self,key):
        row=self.selected_asset(key)
        if row and QMessageBox.question(self,'移除清單','只移除清單項目；不刪除原檔或既有庫存。可使用回復動作復原。')==QMessageBox.StandardButton.Yes:
            value=deepcopy(self.session.pages[key]);value['rows']=[r for r in value['rows'] if r['id']!=row['id']];self.commit_extra(key,value)

    def open_asset(self,key):
        row=self.selected_asset(key)
        if row:
            try:QDesktopServices.openUrl(QUrl.fromLocalFile(str(available_path(self.store.path,row))))
            except ValueError as exc:QMessageBox.warning(self,'無法開啟',str(exc))

    def preview_asset(self,key):
        if self.extra_loading:return
        ui=self.asset_ui[key];row=self.selected_asset(key);ui['reading']=True;ui['pdf'].clear();ui['selected']=row['id'] if row else None
        if not row:ui['info'].clear();ui['preview'].setCurrentWidget(ui['info']);ui['reading']=False;return
        try:
            path=available_path(self.store.path,row)
            ui['info'].setPlainText(f"{row['name']}\n來源：{row['source']}\n庫存：{row.get('managed','')}\n拍攝日期：{row.get('capture_date') or '未提供'}\n{row['note']}")
            if path.suffix.lower()=='.pdf' or Path(row['name']).suffix.lower()=='.pdf':
                page=int(self.settings.value('reader/'+row['id']+'/page',0));zoom=float(self.settings.value('reader/'+row['id']+'/zoom',1))
                ui['pdf'].load(path,deepcopy(row.get('annotations')),page,zoom);ui['pdf'].set_editable(key in self.session.unlocked);ui['preview'].setCurrentWidget(ui['pdf'])
            elif key=='photos':
                ui['photo'].setText('載入縮圖／預覽中…');ui['preview'].setCurrentWidget(ui['photo']);pid=self.store.project_id
                self.thumbnail_jobs.append((key,row['id'],pid,self.thumbnail_pool.submit(self.read_photo,path)))
            else:ui['preview'].setCurrentWidget(ui['info'])
        except (ValueError,RuntimeError) as exc:ui['info'].setPlainText(str(exc));ui['preview'].setCurrentWidget(ui['info'])
        ui['reading']=False

    @staticmethod
    def read_photo(path):
        reader=QImageReader(str(path));reader.setAutoTransform(True);size=reader.size();size.scale(900,700,Qt.AspectRatioMode.KeepAspectRatio);reader.setScaledSize(size)
        image=reader.read();capture=''
        try:
            from PIL import Image
            with Image.open(path) as photo:
                exif=photo.getexif();capture=str(exif.get(36867) or exif.get_ifd(34665).get(36867) or '')
        except (ImportError,OSError,ValueError):pass
        return image,capture,reader.errorString()

    def poll_thumbnails(self):
        remaining=[]
        for key,rid,pid,future in self.thumbnail_jobs:
            if not future.done():remaining.append((key,rid,pid,future));continue
            if not self.session or self.store.project_id!=pid:continue
            try:
                image,capture,error=future.result();ui=self.asset_ui[key]
                row=next((r for r in self.session.pages[key]['rows'] if r['id']==rid),None)
                if not row:continue
                pixmap=QPixmap.fromImage(image).transformed(QTransform().rotate(row.get('rotation',0)))
                for i in range(ui['table'].rowCount()):
                    if ui['table'].item(i,0).data(Qt.ItemDataRole.UserRole)==rid:ui['table'].item(i,0).setIcon(QIcon(pixmap.scaled(100,75,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)))
                if ui['selected']==rid:
                    if image.isNull():ui['photo'].setText('此格式無法預覽：'+error+'\n原檔仍可連結、庫存及使用系統程式開啟。')
                    else:ui['photo'].setPixmap(pixmap.scaled(520,500,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
                    ui['info'].setPlainText(ui['info'].toPlainText()+'\nEXIF 拍攝日期：'+(capture or '未提供'))
            except Exception as exc:self.message.setText('縮圖無法載入：'+str(exc))
        self.thumbnail_jobs=remaining

    def asset_annotations(self,key,notes):
        row=self.selected_asset(key)
        if row and key in self.session.unlocked:
            value=deepcopy(self.session.pages[key]);next(r for r in value['rows'] if r['id']==row['id'])['annotations']=deepcopy(notes);self.commit_extra(key,value,False)

    def reader_position(self,key,page,zoom):
        if self.asset_ui[key]['reading']:return
        rid=self.asset_ui[key]['selected']
        if rid:self.settings.setValue('reader/'+rid+'/page',page);self.settings.setValue('reader/'+rid+'/zoom',zoom)

    def backup_library(self):
        if not self.session or self.future:return
        path,_=QFileDialog.getSaveFileName(self,'完整備份資料庫與 Docstore','','可攜備份 (*.zip)')
        if path:self.save(after=lambda:self.io(lambda:portable_backup(self.store,path),lambda result:QMessageBox.information(self,'備份完成',f"已驗證 {result['files']} 個檔案；{result['external']} 個連結型來源未包含於備份。")))

    def restore_library(self):
        path,_=QFileDialog.getOpenFileName(self,'還原可攜備份','','可攜備份 (*.zip)')
        if not path:return
        parent=QFileDialog.getExistingDirectory(self,'選擇還原位置（另建全新資料夾）')
        if not parent:return
        target=Path(parent)/('TRAADuoDuo_restore_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
        self.io(lambda:restore_backup(path,target),lambda database:QMessageBox.information(self,'還原完成','已驗證並還原至：'+database+'\n可由資料庫工具列開啟；未覆蓋目前資料。'))

    def populate_asset_rows(self,key):
        before=self.extra_loading;self.extra_loading=True;ui=self.asset_ui[key];table=ui['table'];selected=ui['selected'];table.setRowCount(0)
        if self.session:
            categories={c['id']:c['name'] for c in self.session.pages[key]['categories']}
            visible={ui['filter']} if ui['filter'] else set(categories)|{''}
            while True:
                expanded=visible|{c['id'] for c in self.session.pages[key]['categories'] if c['parent'] in visible}
                if expanded==visible:break
                visible=expanded
            rows=list(self.session.pages[key]['rows'])
            if ui['sort'].currentIndex()==1:rows.sort(key=lambda r:r['name'].casefold())
            if ui['sort'].currentIndex()==2:rows.sort(key=lambda r:(not bool(r.get('capture_date')),r.get('capture_date',''),r['name'].casefold()))
            for row in rows:
                if row['category'] not in visible:continue
                i=table.rowCount();table.insertRow(i)
                try:available_path(self.store.path,row);status='已庫存' if row['stock'] else '連結可用'
                except ValueError:status='離線／遺失'
                source=Path(row['source'])
                if source.is_file() and 'source_mtime_ns' in row:
                    stat=source.stat()
                    if stat.st_mtime_ns!=row['source_mtime_ns'] or stat.st_size!=row['source_size']:status+='／來源已更新'
                for j,text in enumerate([row['name'],'',categories.get(row['category'],'未分類'),status,row['note']]):
                    item=QTableWidgetItem(text);item.setData(Qt.ItemDataRole.UserRole,row['id'])
                    if j==1:item.setCheckState(Qt.CheckState.Checked if row['stock'] else Qt.CheckState.Unchecked)
                    table.setItem(i,j,item)
                if selected==row['id']:table.setCurrentCell(i,0)
                if key=='photos':
                    table.setRowHeight(i,90);table.setIconSize(QSize(100,75))
                    try:self.thumbnail_jobs.append((key,row['id'],self.store.project_id,self.thumbnail_pool.submit(self.read_photo,available_path(self.store.path,row))))
                    except ValueError:pass
        self.extra_loading=before

    def populate_advanced(self,key=None):
        self.extra_loading=True
        if key in (None,'details'):
            for kind,ui in self.detail_ui.items():
                selected=ui['versions'].currentData();ui['versions'].clear()
                batches=self.session.pages['details'][kind] if self.session else []
                for batch in batches:ui['versions'].addItem(batch.get('name',batch['filename']),batch['id'])
                ui['versions'].setCurrentIndex(max(0,ui['versions'].findData(selected)) if selected else max(0,len(batches)-1))
        if key in (None,'diary'):
            rows=sorted(self.session.pages['diary'],key=lambda r:r['number']) if self.session else [];self.diary_table.setRowCount(len(rows))
            for i,row in enumerate(rows):
                for j,name in enumerate(['number','date','description','note']):
                    item=QTableWidgetItem(str(row[name]));item.setData(Qt.ItemDataRole.UserRole,row['id']);self.diary_table.setItem(i,j,item)
            self.resize_diary()
        for name,ui in self.asset_ui.items():
            if key not in (None,name):continue
            tree=ui['categories'];tree.clear();nodes={};top=QTreeWidgetItem(['全部文件' if name=='documents' else '全部照片']);top.setData(0,Qt.ItemDataRole.UserRole,'');tree.addTopLevelItem(top)
            categories=self.session.pages[name]['categories'] if self.session else []
            pending=list(categories)
            while pending:
                ready=[c for c in pending if not c['parent'] or c['parent'] in nodes]
                if not ready:break
                for c in ready:
                    node=QTreeWidgetItem([c['name']]);node.setData(0,Qt.ItemDataRole.UserRole,c['id']);(nodes.get(c['parent']) or top).addChild(node);nodes[c['id']]=node;pending.remove(c)
            tree.expandAll();tree.setCurrentItem(nodes.get(ui['filter'],top));ui['filter']=tree.currentItem().data(0,Qt.ItemDataRole.UserRole);self.populate_asset_rows(name)
        self.extra_loading=False
        if key in (None,'details'):
            for kind in self.detail_ui:self.populate_detail(kind)
        for name in self.asset_ui:
            if key in (None,name):self.preview_asset(name)

    def apply_advanced_locks(self,ready):
        for key,buttons in self.extra_buttons.items():
            editable=bool(ready and key in self.session.unlocked)
            for button in buttons:button.setEnabled(editable)
            if key in self.asset_ui:
                ui=self.asset_ui[key];ui['pdf'].set_editable(editable)
                for row in range(ui['table'].rowCount()):
                    item=ui['table'].item(row,1)
                    flags=item.flags()
                    item.setFlags(flags|Qt.ItemFlag.ItemIsUserCheckable if editable else flags&~Qt.ItemFlag.ItemIsUserCheckable)
        self.diary_table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers if ready and 'diary' in self.session.unlocked else QAbstractItemView.EditTrigger.NoEditTriggers)
