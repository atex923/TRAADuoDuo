# TRAADuoDuo V0.0.1 交接

使用者於 2026-09-23 授權實作第一版。這份專案是產品初版，和 V0.2 交接 ZIP 版本不同。

目前完成範圍及啟動方法見 README。Domain、session、repository 不依賴 GUI；UI 的 DB I/O 在 worker 執行，回到主執行緒才改畫面。每次操作使用獨立 SQLite connection 並確實關閉。

關鍵決策：每工程一個 DB；「新增資料庫」和「新增工程案」共用安全新建流程。schema 1 使用 pages JSON 作首版持久化；後續正規化 tables 需要遷移，不可直接覆寫。初始 migration 有失敗回滾測試；此版沒有可升級的歷史產品 schema。

工曆政策依 TR_FxWork_V0_3_4_3.py 的 daily_work_increment；預算 summary/detail/analysis legacy 檢視長度與最長前綴分開處理。預算父項 `rollup` 和 `analysis` 政策明確區分，等待真實資料再建立匯入判別與完整計算政策。

後續優先：Windows 實機/DPI 驗證；基本資料其餘三頁；工曆逐列是否計工期選項；完整預算欄位、匯入、diagnostics、費率與管理費政策；最後再按原 M4～M9 功能規劃推進。

DesktopWoof 原始碼仍未提供；本版僅顯示協力圈預留狀態，未建 producer、consumer、outbox 或通知。不要以預留列宣稱已串接。

UI 截圖為 Qt offscreen 的本程式畫面，不是 Windows 執行證據。Windows EXE、macOS App bundle、雲端同步、Git 發布皆未執行。
