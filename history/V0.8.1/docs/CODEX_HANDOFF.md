# V0.8.1 交接

目前版本 V0.8.1(20261023)，schema 10，費用 calculation_revision 3。以本版 README 與 V0.8.1_validation.md 為準。本次只本機實作／驗證／封裝，沒有同步或發布授權。V0.8.0 保留不變。

未完工程＝原含稅合計－未完工程進項稅額；總額再加回該稅額。歷史費用以 historical_v080 留存。MoneyField 必須傳原始值；擴充欄保留原值與顯示值，不能用兩位顯示反向截斷未編輯資料。

詳細表支援 A3118 16 欄與 AB3155 9 欄，表頭自動辨識前 100 列，支援指定工作表、格式與表頭列。AB3155 映射至共用 16 欄，未提供欄位留空，來源額外資訊另存；不執行公式／外部連結。預算「刪除」刪除選取修訂版，需解鎖確認，可回復，不刪來源 Excel。

Windows 自訂標題列提供 _／─／□／×，_ 專用系統匣；─ 保留一般最小化，支援拖曳、邊緣縮放及尺寸握把。僅元件與條件分支測試，仍待 Windows 實機驗收。

## V0.8.0 歷史交接

目前版本為V0.8.0(20261022)，schema 10。請以本版README、V0.8.0_validation.md及原始碼為準。新增idle_save、report_export、export_forms、desktop_features模組；來源庫唯讀匯入，不修改正式工程。Windows實機仍待驗收；同步不等同GitHub發布。

以下為V0.6.1歷史交接，僅供追溯，不代表目前費用基數、管理費欄位或入口。

## V0.6.1歷史紀錄

正式新入口 `<project-root>/outputs/TRAADuoDuo/V0.6.1`，保留 V0.6.0 與其 manifest 全部 99 檔不變。Python／PySide6 原始碼交付，啟動檔 TRAADuoDuo_V0.6.1.py／.pyw。

- 施工工作日帳依工作日完成日截止顯示，事件照常保留；不改基本資料竣工模式及日期規則。三表以資料鍵及焦點判斷作用頁，禁止回復舊的副分頁索引對應。
- presentation.MoneyField 將原始精度與顯示文字分開，金額格式不能透過 capture 反向截斷資料；管理費兩位、保證金整數。原管理費整元合計及 default 截千計算不變。
- billing.contract_progress 使用同範圍 amount＋tax 除以 costs.contract.award_total，不估固定稅率、不使用 estimated 或 paid。
- asset_store.inventory 與 content_store 在同 library_id 的 Docstore 內查重，使用大小＋SHA-256，候選完整重新校驗、OS 鎖和背景取消。同內容不增加相同歷史版本，內容真的改變保留舊版本；不刪任何既有完整庫存。
- .content-index.json 為可重建快取，.inventory.lock 存在不代表有活程序；均不是業務資料或備份必要檔。備份透過清單／版本引用包含共用物件一次，還原後可重建索引。舊庫存路徑繼續可讀，不作資料庫 schema 遷移（仍為 8）。
- 單一實例保護不變。正常使用中的 V0.6.0 未關閉；原生 cocoa／offscreen 啟動測試、畫面、測試庫均用獨立 QA 身分。沙盒阻擋 Unix 通道的失敗不視為 App 缺陷，最終測試使用取得權限的隔離 QA 環境。

最終完整回歸 177 項全數通過（無跳過），47 個 Python／pyw 語法檢查通過；詳細證據見 V0.6.1_validation.md。tools/render_v061.py 產生本版示範畫面；舊畫面不當本版證據。本次不含 PsTOAA 技能包、正式資料整理、Drive 同步或 GitHub 發布。

## 以下為 V0.6.0 歷史交接

2026-10-17。正式入口 <project-root>；V0.6.0 為獨立交付，保留 V0.5.0。不推送、不雲端同步，不改寫使用者原始庫。

schema 8 新增 details／diary／documents／photos 四個 JSON 頁。advanced_data 提供預設值及驗證，仍使用原有 EditSession、project_id、revision 及 SQLite 交易。舊庫只能唯讀預覽後匯入新庫；不可降低 user_version 給舊程式開啟。

aa_import 只讀 .xlsx，以 openpyxl 展開共享公式、原始 XML 保留精確快取／額外欄，不執行公式或外部連結。asset_store 管理 Docstore、SHA-256、版本及可攜備份；取消庫存或刪清單不刪原檔。layout_settings 保存本機 UI 偏好，不寫入業務頁；施工曆私有表格的星期列另由 MonthCalendar 管理。

advanced_forms 接四表、大事記與兩種資產庫；pdf_reader 在 PDF 外保存書籤與矩形標記，連續閱讀僅渲染附近頁。tools/render_v060.py 使用獨立 QA 身分及示範畫面，不能把歷史 screenshots 當新版本驗收。

151 項測試及兩種 Qt 啟動通過。詳細界線見 V0.6.0_validation.md。原管理費 total 改整元，raw_total 保留精確值，default 仍從精確值截千元。

## 以下為 V0.5.0 歷史交接，非目前版本說明

2026-10-17。來源為保留的V0.4.1，正式入口改為<project-root>。
本次不推送、不雲端同步；沒有改寫使用者資料庫。

schema 7使用原有關聯表結構，但weather頁JSON增加第5格獨立不計工期；第4格仍為備註。UI順序為日期／上午／下午／不計工期／備註，populate/capture需交換最後兩格。舊4格只補第5格，-1備註補1，原值不丟失。禁止將schema7降標為6讓舊版開啟。

scheduling.py提供純函式deadlines、working_calendar、weather_text。日曆日期用date，不用含時區datetime；workdayA為順延衍生。Session.reconcile接通finance.synchronize，日期、保證金、費用與招標一同產生。實際日期不覆寫。施工曆統計固定使用工作日context，與所選竣工模式獨立。

cost_totals使用Decimal，計算其他費用、包工費以外、未完工程及總工程費。關鍵來源空白保留空白。新輸入總額唯讀，歷史total/unfinished保存在historical_totals、基本資料舊預定日期在historical_deadlines；raw匯入快照仍保留。既有明確保證金基數不自動覆蓋；自辦工費▶依本次確認固定複製預算自辦工費，舊來源留在source_settings_legacy。

擴充項目仍為共用id/label/budget/contract；兩個區域各有自己的表格，名稱編輯同步，金額各自保存。extensions_visible只改顯示，不能作為公式排除條件。

allocation_allowed讀取session.saved與目前前階段比對，要求三費別與生效期完整且成功保存。submit_allocation會觸發save；失敗只留草稿，不開放下一階段。原有舊越序資料可載入、保留與警告，store不以新UI順序拒絕舊快照。

macOS單一實例沿用MacInstance，正式應用識別與資料路徑未更換。QA使用隔離設定／目錄／實例，所有測試暫存與畫面在外接專案work或outputs。Qt離屏不代表Windows／DPI／打包或使用者正式庫操作驗收。

執行：TMPDIR指定到專案work/qa_v050/tmp，PYTHONDONTWRITEBYTECODE=1，python3 -m unittest discover -s tests -v。
畫面：python3 tools/render_revision.py，輸出docs/screenshots/v050。tools/render_preview.py為舊版通用示範工具，畫面來源以render_revision為本版交付證據。
