# 踢厄工程管理坊 TRAADuoDuo V0.0.1

第一版可執行原始碼專案。使用 Python＋PySide6，正式圖示採使用者提供原稿。

專案資料夾為 `TRAADuoDuo/`，版本資料夾為 `V0.0.1/`。同時提供 `TRAADuoDuo_V0.0.1.py` 與 `.pyw` 啟動入口；兩者使用同一套程式模組。請保留完整版本資料夾，啟動檔需搭配 `traaduoduo/` 與 `assets/` 使用。

## 啟動

需要 Python 3.11 或更新版本，安裝依賴後執行：

```sh
python3 -m pip install -r requirements.txt
python3 TRAADuoDuo_V0.0.1.pyw
```

也可使用一般 Python 啟動檔：

```sh
python3 TRAADuoDuo_V0.0.1.py
```

Windows 可在本資料夾執行 `py -3 -m pip install -r requirements.txt`，再雙擊 `start_windows.bat`。macOS 安裝依賴後可執行 `start_macos.command`。本次實測為 macOS、Python 3.14.5、PySide6 6.11.1；其他 Python 版本尚未逐一驗證。

這是原始碼交付，未附 Windows EXE。Windows 實機與打包驗證尚未執行。

## 第一次使用

1. 按「新增工程案」，選擇新的 `.db` 路徑。每個工程使用獨立資料庫；不覆寫既有檔案。
2. 在「基本資料」按「解鎖編輯」，填寫工程名稱及相關欄位。
3. 停止輸入約 1.2 秒後自動儲存，也可按「儲存」。無效日期或數值會阻止儲存，原資料保留。
4. 到施工日曆各表解鎖後新增日期。日期格式 `YYYY-MM-DD`。每個表可獨立回復最近 10 次編輯。
5. 「施工日曆」可用上一月/下一月、滾輪、上下鍵切換月份。選取日期顯示計算原因。
6. 「資料庫」可選擇其他工程、新增資料庫或備份。開啟/切換前會嘗試儲存目前修改；失敗時留在目前案件。

初次啟動不自動在任意目錄建立工程；由使用者選擇位置。上次工程位置存入系統應用設定。若原路徑不存在，會提示重新選擇。工作記錄存於 Qt AppLocalDataLocation 下 `app.log`，最多保留三份、每份約 1 MB。

建立可修改的範例工程：

```sh
python3 tools/create_demo.py demo.db
python3 TRAADuoDuo_V0.0.1.pyw --project demo.db
```

## 已完成與範圍

- WinXP 風格主視窗、六大分頁、基本資料四個子頁、施工日曆五個子頁。
- 基本資料完整編輯流程、SQLite 儲存、背景 I/O、自動儲存、案件切換、備份。
- 每頁鎖定、最多 10 次 Undo；重新鎖定前先儲存；切工程會清除上一工程的鎖定與 Undo 狀態。
- 假期、補班、輸運停工、晴雨表可編輯；工作日/日曆天、每日原因、月統計與推算竣工。
- 預算核心有階層、Decimal、父項政策、四捨五入及 trace；本版沒有預算編輯 UI。
- 正式圖示已套用主視窗、標題區及關於視窗。

保證金、工程費用、變更契約、詳細表、大事記、文件庫與照片庫目前是明確標示的預留頁面。列印停用；協力圈顯示尚未設定，本版沒有產生或匯入期限交換檔。

## 工曆及預算政策

工曆沿用參考程式的判斷：輸運停工 → 備註 `-1` → 工作日/日曆天基礎 → 補班 → 假期歸零 → 晴雨扣除。上午正值扣 1 日；下午正值扣 0.5 日；上午至少 1 時合計扣 1 日；每日結果最少為 0。這是舊程式相容規則，不是新訂工程規則。開工日包含於計數；預定竣工欄位不由推算結果自動覆寫。

預算 `rollup` 節點只加總直接子項，`analysis` 節點再乘父項數量。因原始文件對父項金額定義不同，本版保留兩種明確政策與測試，尚不自動推斷真實預算資料的種類。費率和階梯管理費完整政策、Excel 匯入留後續版本。

本版將所有列入假期/鐵路輸運表的日期視為不計工期；「記錄日期但仍計工期」的逐列選項尚未提供。

## 檢查

```sh
python3 -m unittest discover -s tests -v
python3 tools/render_preview.py
```

測試不接觸正式工程，使用暫存資料庫。UI 測試預設採 Qt offscreen。畫面預覽在 `docs/screenshots/`。

## 專案結構

- `traaduoduo/domain.py`：純工曆與預算計算。
- `traaduoduo/session.py`：驗證、每頁鎖定、Undo、dirty state。
- `traaduoduo/store.py`、`migrations.py`：SQLite、初始遷移、revision 衝突檢查及備份。
- `traaduoduo/ui.py`：畫面及 UI adapter；資料 I/O 透過單一背景 worker。
- `tests/`：資料、計算及 Qt 互動測試。
- `docs/`：測試報告、變更及交接。

SQLite schema 1 以 pages JSON 保存首版表單/工曆資料。未提供舊 TR_FxWork DB 自動轉換；非本程式 DB、未來 schema、壞檔會拒絕開啟。
