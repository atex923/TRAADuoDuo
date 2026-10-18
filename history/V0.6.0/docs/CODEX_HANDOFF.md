# V0.6.0 交接

2026-10-17。正式入口 <workspace>；V0.6.0 為獨立交付，保留 V0.5.0。不推送、不雲端同步，不改寫使用者原始庫。

schema 8 新增 details／diary／documents／photos 四個 JSON 頁。advanced_data 提供預設值及驗證，仍使用原有 EditSession、project_id、revision 及 SQLite 交易。舊庫只能唯讀預覽後匯入新庫；不可降低 user_version 給舊程式開啟。

aa_import 只讀 .xlsx，以 openpyxl 展開共享公式、原始 XML 保留精確快取／額外欄，不執行公式或外部連結。asset_store 管理 Docstore、SHA-256、版本及可攜備份；取消庫存或刪清單不刪原檔。layout_settings 保存本機 UI 偏好，不寫入業務頁；施工曆私有表格的星期列另由 MonthCalendar 管理。

advanced_forms 接四表、大事記與兩種資產庫；pdf_reader 在 PDF 外保存書籤與矩形標記，連續閱讀僅渲染附近頁。tools/render_v060.py 使用獨立 QA 身分及示範畫面，不能把歷史 screenshots 當新版本驗收。

151 項測試及兩種 Qt 啟動通過。詳細界線見 V0.6.0_validation.md。原管理費 total 改整元，raw_total 保留精確值，default 仍從精確值截千元。

## 以下為 V0.5.0 歷史交接，非目前版本說明

2026-10-17。來源為保留的V0.4.1，正式入口改為<workspace>。
本次不推送、不雲端同步；沒有改寫使用者資料庫。

schema 7使用原有關聯表結構，但weather頁JSON增加第5格獨立不計工期；第4格仍為備註。UI順序為日期／上午／下午／不計工期／備註，populate/capture需交換最後兩格。舊4格只補第5格，-1備註補1，原值不丟失。禁止將schema7降標為6讓舊版開啟。

scheduling.py提供純函式deadlines、working_calendar、weather_text。日曆日期用date，不用含時區datetime；workdayA為順延衍生。Session.reconcile接通finance.synchronize，日期、保證金、費用與招標一同產生。實際日期不覆寫。施工曆統計固定使用工作日context，與所選竣工模式獨立。

cost_totals使用Decimal，計算其他費用、包工費以外、未完工程及總工程費。關鍵來源空白保留空白。新輸入總額唯讀，歷史total/unfinished保存在historical_totals、基本資料舊預定日期在historical_deadlines；raw匯入快照仍保留。既有明確保證金基數不自動覆蓋；自辦工費▶依本次確認固定複製預算自辦工費，舊來源留在source_settings_legacy。

擴充項目仍為共用id/label/budget/contract；兩個區域各有自己的表格，名稱編輯同步，金額各自保存。extensions_visible只改顯示，不能作為公式排除條件。

allocation_allowed讀取session.saved與目前前階段比對，要求三費別與生效期完整且成功保存。submit_allocation會觸發save；失敗只留草稿，不開放下一階段。原有舊越序資料可載入、保留與警告，store不以新UI順序拒絕舊快照。

macOS單一實例沿用MacInstance，正式應用識別與資料路徑未更換。QA使用隔離設定／目錄／實例，所有測試暫存與畫面在外接專案work或outputs。Qt離屏不代表Windows／DPI／打包或使用者正式庫操作驗收。

執行：TMPDIR指定到專案work/qa_v050/tmp，PYTHONDONTWRITEBYTECODE=1，python3 -m unittest discover -s tests -v。
畫面：python3 tools/render_revision.py，輸出docs/screenshots/v050。tools/render_preview.py為舊版通用示範工具，畫面來源以render_revision為本版交付證據。
