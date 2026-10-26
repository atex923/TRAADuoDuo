# V0.6.0 驗證入口

目前版本的驗收紀錄為 [V0.6.0_validation.md](V0.6.0_validation.md)：151 項測試、實際 AA 原檔、macOS cocoa／offscreen 啟動、欄寬持久化、Docstore 備份還原及 PDF 非破壞註記均有獨立紀錄。

## 以下為 V0.5.0 歷史驗證報告

日期：2026-10-17。環境：macOS、Python 3.14.5、PySide6 6.11.1。
來源：獨立複製V0.4.1，在新入口<project-root>內開發。
測試資料與暫存放work/qa_v050；沒有寫入使用者正式工程或覆蓋舊版。

## 驗證結果

| 關卡 | 結果與範圍 |
|---|---|
| 全套單元／整合／Qt離屏 | 125項通過，原有100項依新版介面行為調整並保留涵蓋，新增25項驗收 |
| macOS原生Qt Cocoa操作 | 14項通過，含欄位、日期、格式、分頁位置、鍵盤輸入、自動儲存、分攤保存與失敗保護 |
| 真實app.main入口 | offscreen及cocoa皆成功啟動、定時正常關閉；設定／日誌／單一實例為隔離QA目錄 |
| Python語法 | 33個.py檔在記憶體編譯成功，不向主機寫pyc |
| 單一實例 | 同身分第二實例拒絕、關閉後核心鎖釋放；正式身分與既有資料路徑不變 |
| 實際舊資料庫 | 指定TRFxWork_db共4工程，全部唯讀預覽及隔離匯入成功，來源SHA-256不變 |
| 實際舊計價 | 發包工程10筆、發包以外2筆、管理費支用2筆；逐筆轉入回讀一致，未分類階段不猜填 |
| 原始資料保存 | 招標日期括號註記與原始快照回讀一致；V0.4.1來源測試庫的舊合計／預定日期／晴雨值保留且來源雜湊不變 |
| TR_FxWork原始建表 | 原始init_schema建表，施工日曆、三類計價及分攤匯入／回讀通過，來源位元組不變 |
| 實際Qt畫面 | 14張Cocoa原生Qt視窗擷取，含1440×1000及860×650；不是HTML概念預覽 |
| 雲端／GitHub | 未執行同步、推送、發布或CodeLazy登錄 |

## 關鍵覆蓋

- 主分頁位置不因副分頁有無變動；Cocoa的副標籤預設置中另以內容寬度限制修正，1440px下驗證緊接主標籤。
- 日期提示#8E8E8E、識別312px／一般156px；i重複標題不出現、說明39px。
- 日曆天含首日；工作天遇假期、輸運、一般週末排除，補班例外；上午1全日、下午0.5半日、不計工期獨立保存。同日不重複扣除。
- 半日不足跨週末／假期順延、閏日、跨年、空白、0、非法日期與分數工期；實際日期不覆寫、錯誤草稿不寫入且不顯示舊衍生日期。
- 初驗由所選模式竣工起算，驗收由初驗起算；施工曆工作日數與模式獨立，達契約工期後仍累計。
- 預算／契約唯讀公式、Decimal精度、必要來源未填保留空白、其他費用擴充與隱藏合計不變；項目名稱同步、ID及顯示狀態重啟保存。
- 不合法擴充金額保留草稿、不可寫入／複製，修正後可保存；編輯時不重建正在使用的表格委派輸入元件。
- 前階段三費別及生效期成功保存才開放下一階段；0視為已填，寫入失敗不開放。越序歷史紀錄保留並提示。
- 既有唯一決標、每階段單筆提撥、歷史期數、空值與0、稅額不猜拆、跨工程隔離、revision衝突、回滾、備份與匯出回讀沿用測試。
- 實際舊庫的元金額、百分比、ISO日期後括號備註可明確轉換並保留原字串；不認識的管理費金額列為該工程預覽錯誤，不猜0、不使整個預覽崩潰。

## 畫面

本版證據只使用screenshots/v050下的basic、no-subtabs、costs、management-fees、guarantees、holiday-makeup、date-dialog、weather-full、weather-half、calendar、admin-payments、admin-narrow、basic-narrow、costs-narrow。
同資料夾以外若有沿用的舊版示範圖，不能當本版新畫面證據。

## 證據位置與重跑

專案work/qa_v050/tests-final.log：125項離屏測試紀錄。
專案work/qa_v050/native-ui.log：14項原生操作紀錄。
專案work/qa_v050/legacy-source-report.json：無工程名稱／金額的計數、原始快照與來源SHA驗證。

```sh
TMPDIR=<project-root>/work/qa_v050/tmp PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v
TMPDIR=<project-root>/work/qa_v050/tmp PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=cocoa PYTHONPATH=.:tests python3 -m unittest test_revision.RevisionUITests test_ui.UITests.test_real_timer_autosaves_typing test_ui.UITests.test_compact_header_clicks_and_layer_visibility -v
TMPDIR=<project-root>/work/qa_v050/tmp PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=cocoa python3 tools/render_revision.py
```

## 尚未驗證／未交付

Windows實機、不同DPI／顯示縮放、Windows EXE、macOS.app封裝／簽章／安裝、使用者人工逐頁驗收未完成。
原生操作測試與Qt視窗擷取不代表上述平台或人工驗收已完成；本版交付為可執行的Python專案。
使用者正式庫未原地升級；後續開啟舊庫需核對預覽後另存新V050統一庫，不能把隔離匯入成功當成正式庫已轉換。
