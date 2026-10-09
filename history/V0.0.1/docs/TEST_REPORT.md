# V0.0.1 驗證紀錄

日期：2026-09-23。環境：macOS、Python 3.14.5、PySide6 6.11.1。

## 已執行

- `python3 -W error::ResourceWarning -m unittest discover -s tests -v`：21 項通過。
- `python3 tools/smoke_launch.py`：實際 app.main 入口以隔離設定/日誌啟動、事件迴圈運作、定時關閉，exit 0。使用 Qt offscreen。
- `python3 tools/render_preview.py`：成功產生 main.png、calendar.png，已人工視覺檢查內容、文字、圖示及主要控制項。
- `python3 -m compileall -q`：首輪語法編譯通過；後續修改的模組亦由上述測試匯入執行。
- 額外 characterization：由所附 TR_FxWork_V0_3_4_3.py 抽出 daily_work_increment 的 AST，在不啟動舊 GUI 下執行。兩種工期模式 × 7 個星期日別 × 假期/輸運/補班旗標 × 上午/下午 0、0.5、1 × 強制 -1，共 2,016 組，與新服務結果全部一致。

## 測試涵蓋

資料：建立/重開、備份回讀、禁止覆寫、revision 衝突、交易失敗回滾、拒收非本程式 DB 與未來 schema、工程隔離、初始 migration 回滾。

編輯：頁面鎖定、Undo 上限 10、saved/dirty 狀態、日期重複與非有限數字拒收。

工曆：規則優先序、晴雨舊行為、閏年、包含開工日的累計與竣工推算。

預算：父項 rollup/analysis 政策、非列序階層、重複/缺父項/循環拒收、Decimal HALF_UP、費率及 legacy 檢視。

Qt：六大分頁、4/5 子頁、列印停用、圖示、鎖定、儲存/Undo、實際輸入後計時自動儲存、內部日曆視圖上下鍵切月、工曆表編輯、切案件前儲存與鎖定重置、模擬 disk full 保留草稿及 revision。

## 限制

- UI 與入口驗證使用 macOS 的 Qt offscreen；尚未完成 Windows 實機、125%/150% Windows DPI、檔案對話框人工操作或 EXE 打包。
- 未驗證每個宣告支援的 Python 版本；本次實測只有 3.14.5。
- 初始 schema 0→1 有交易回滾驗證；未提供舊工程 DB 匯入/遷移。
- 預算只完成首版模型與基礎計算，非完整費率/管理費/Excel 計算驗收。
- 協力圈、DesktopWoof 系統通知、正式列印、雲端往返都不在本版完成範圍。
- Qt 顯示一次 Sans Serif 字型 fallback 提示，不影響測試；Windows 字型仍需實機檢查。
