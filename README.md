# 踢厄工程管理坊 TRAADuoDuo

Python／PySide6 桌面工程管理程式，整合多工程、契約執行、工程費用、施工日曆、計價與文件管理。最新版 **V0.8.1(20261023)**，GPL v3；macOS 已驗證，Windows 專屬視窗功能仍待實機驗收。

## 最新版

- [完整來源 ZIP](deliverables/TRAADuoDuo_V0.8.1.zip) · [ZIP SHA-256](deliverables/SHA256.txt)
- [Python 入口](TRAADuoDuo_V0.8.1.py) · [無主控台入口](TRAADuoDuo_V0.8.1.pyw)
- [macOS 啟動器](start_macos.command) · [Windows 啟動器](start_windows.bat)
- [更新紀錄](CHANGELOG.md) · [V0.8.1 驗證報告](docs/V0.8.1_validation.md)

請解壓完整 ZIP 或取得整個儲存庫。入口依賴同目錄的 traaduoduo 與 assets，不是單檔程式。ZIP 沿用已驗證的完整本機來源包；儲存庫首頁與歷史文件另整理為公開閱讀版，業務程式碼一致。

## 程式特色

- 多工程統一 SQLite 資料庫、頁面鎖定、復原與唯讀舊庫匯入，保留來源與歷史資料。
- 契約、保證金、招標與工程費用；Decimal 計算、千分位兩位小數，顯示格式不截斷原值。預算與契約的未完工程扣除指定進項稅額並標示未稅。
- 輸入停止60秒才背景儲存；手動儲存立即提交，有序銜接既有寫入，不等待閒置計時。
- 施工曆整合假期、補班、鐵路疏運及晴雨；工作日累計達工期後截止。
- 發包工程、發包以外與管理費計價，數字期數排序、截至選期累計、階段提撥分攤；金額靠右，日期、期數與文字置中。
- 詳細表支援 A3118／AB3155 Excel 預覽匯入、來源快取保存、階層檢視、預算修訂版刪除及回復。
- 大事記搜尋與手動／日期排序、期限追蹤警示；文件／照片庫分類、連結或 Docstore 庫存及內容去重。
- 可搜尋中文 PDF 與 typed Excel 報表；文件照片來源不嵌入報表。
- Windows 標題列 _ 專供系統匣，位於一般最小化左側；一般最小化保留工具列，關閉仍先確認未儲存變更。

## 安裝與執行

需 Python 3 與 requirements.txt 依賴。於完整來源資料夾執行：

```sh
python3 -m pip install -r requirements.txt
python3 TRAADuoDuo_V0.8.1.py
```

Windows 可用 `py -3 TRAADuoDuo_V0.8.1.pyw`；亦可使用對應啟動器。升級前保留資料庫備份。舊來源先唯讀預覽再匯入，不用舊版直接改寫新版資料；文件庫存請使用完整備份，不只複製單一 db。

## 檔案與版本歷史

根目錄保留最新版程式、資源、測試與文件；[history 索引](history/README.md)保留舊公開版及後續獨立版本，舊驗證報告與截圖隨版本歸檔。累積變更見 [CHANGELOG](CHANGELOG.md)。

## 驗證與限制

沿用與來源指紋相符的235項回歸測試、200%縮放14項測試與 macOS Cocoa 啟閉證據；本次發布只整理交付與文件，未重新建置或重跑全套測試。

Windows 標題列、系統匣、縮放與邊緣調整尚未完成 Windows 實機驗收；跨平台元件預覽不能替代實機。未提供 EXE、簽署安裝包或另建 GitHub Release／tag。Excel 原生應用程式與正式工程資料未代為驗收。
