# 離線 HTML 報告：閱讀、製作與維護

這份文件說明如何閱讀與維護 `PET_軟體驗證完整說明報告_2026-10-24.html`。PET 實驗證據來自 **2026-10-19**；教學報告於 **2026-10-24** 整理。重新繪圖與打包不代表重新執行 PET 實驗。

## 直接閱讀

交付檔案放在雲端硬碟根目錄：

```text
C:\Users\zenbook\我的雲端硬碟\PET_軟體驗證完整說明報告_2026-10-24.html
```

將這個 HTML 檔複製到其他電腦，再以 Edge 或 Chrome 開啟即可閱讀。閱讀端不需要安裝 Codex、Data 插件、Python、Conda 或 Node.js。圖表、教學互動與已封裝的資料可離線使用；開啟外部論文或官方文件連結時才需要網路。

報告採淺色版面，包含 24 章正文、20 幅圖及 1 個 TOF 時間差互動教具。這一版正文計數為 **33,307 個字元**，計算方式是各章 `body` 的 `len()` 加總，包含 Markdown 標記、標點、空白與換行，不能稱為 33,307 個純中文字。

可以先看「先看重點」，再從目錄跳到結果、操作方法或限制。TOF 教具固定兩端位置，讓讀者調整時間差，觀察公式算出的位置；它沒有執行新的 Geant4 或 PET 事件模擬。圖表旁的來源功能可檢視已封裝資料與來源索引。

## HTML 內含哪些證據

| 封裝內容 | 範圍 |
|---|---|
| 正文與圖片 | 24 章文字、20 幅 PNG 圖、TOF 公式互動 |
| Synthetic Singles | 15,871 筆完整 CSV 衍生 reviewed rows |
| GATE Singles | 11,563 筆完整 CSV 衍生 reviewed rows |
| Synthetic pairs | 7,262 筆完整 coincidence/ROR reviewed rows，含假配對及非物理 TOF |
| GATE pairs | 1,921 筆完整 coincidence/ROR reviewed rows |
| 三維體素 | Synthetic 的 1,355 個非零體素、64³ 形狀、各軸 edges 與總計 7,198 點 |
| 其他證據 | 參數、指標、時間誤差掃描、圖說來源索引與完整事實盤點 |

這些 reviewed rows 是由本機 CSV 轉為 JSON 的來源檢視資料，缺值以 `null` 表示。它們不是 CSV 原始檔的逐位元組備份。亂序示意圖仍使用明確標示的前 40 筆 Singles，其他全資料圖則對應完整查詢。圖說來源索引的一列代表一幅圖，不代表一筆偵測事件。

**完整 ROOT 檔未嵌入 HTML。** 原始 ROOT、完整 CSV 與 NPZ 仍保存在本機專案的 `data/`、`outputs/`。報告中的來源路徑用於追溯；它不會讓其他電腦自動取得這些本機原檔。

兩組資料都來自模擬。GATE 同 EventID／RunID 的比例不等於完成散射分類的 true-coincidence precision；平均重建位置偏差也不等於單事件空間解析度。報告引用的 **61 項測試通過**是 2026-10-19 保存的歷史紀錄，這次製作 HTML 沒有重新執行完整測試。

## 製作檔案放在哪裡

專案程式與證據位於：

```text
C:\Users\zenbook\我的雲端硬碟\碩士班研究資料\06_PET
```

可編輯的共享報告框架位於：

```text
C:\Users\zenbook\我的雲端硬碟\PET_HTML報告原始檔_2026-10-24
```

| 專案檔案 | 維護用途 |
|---|---|
| `scripts/pet_explainer_content.py` | 24 章正文、章節來源查詢與圖表安排 |
| `scripts/create_explainer_figures.py` | 讀既有實驗輸出，重繪淺色 SVG／PNG；不重跑模擬 |
| `reports/explainer_assets/manifest.json` | 20 幅圖的圖說、來源、參數及輸入／輸出雜湊 |
| `scripts/prepare_explainer_snapshot.py` | 將現有 CSV、JSON、NPZ 整理為可封裝查詢 |
| `docs/pet_explainer_snapshot.json` | 16 個查詢的資料快照，含完整逐筆 reviewed rows；Git 忽略，可重新整理產生 |
| `docs/html_report_evidence.json` | 事實盤點、限制、確切參數與來源路徑 |
| `scripts/build_explainer_report.py` | 將正文、圖與資料／主題寫入既有共享框架 |

共享框架中的 `src/content/report/` 保存正文元件、書籍資料與報告樣式；`src/data.json` 保存資料與框架識別碼；`src/theme.css` 保存淺色主題。製作腳本沿用既有 `id`、`legacyPresentationTitle`、`authoredRevision`，不建立另一套替代框架。

## 更新文字、圖片與資料

以下是製作者的操作流程。閱讀已交付的 HTML 不需要做這些步驟。

先在同一個 PowerShell 工作階段進入專案並啟用環境：

```powershell
Set-Location -LiteralPath 'C:\Users\zenbook\我的雲端硬碟\碩士班研究資料\06_PET'
. .\scripts\activate.ps1
$petReportApp = 'C:\Users\zenbook\我的雲端硬碟\PET_HTML報告原始檔_2026-10-24'
```

修改 `scripts/pet_explainer_content.py` 的正文。若要重繪圖，執行：

```powershell
python scripts/create_explainer_figures.py
if ($LASTEXITCODE -ne 0) { throw '圖表重繪失敗。' }
```

這個步驟讀取已保存的實驗資料，產生 SVG、150 dpi PNG、圖表 manifest 與版面檢查縮圖。它不呼叫 `demo` 或 `generate_gate_singles.py`，不生成新的 PET 事件。

接著更新資料快照與報告內容：

```powershell
python scripts/prepare_explainer_snapshot.py
if ($LASTEXITCODE -ne 0) { throw '資料快照整理失敗。' }
python scripts/build_explainer_report.py --app-dir $petReportApp --complete
if ($LASTEXITCODE -ne 0) { throw '報告內容寫入失敗。' }
```

`build_explainer_report.py --complete` 只寫入允許的正文內容、資料快照及主題，並將資料中的 `buildStatus` 設為 `complete`。**這個旗標不會編譯、打包或匯出 HTML，也不能取代閱讀檢查。**

若替換了 PET 實驗輸出，應先更新對應的 metrics、config、manifest、驗證報告與事實盤點，再執行上面的圖表及資料整理。`prepare_explainer_snapshot.py` 只讀取現有證據，不會自動重做實驗或重新審查盤點文件。實驗重現指令另見專案 [README](../README.md)。

## 重新打包與匯出離線 HTML

重新打包需要可執行 `node` 的製作環境、**已安裝且相容的 Data 插件工具**，以及原有共享報告框架。只有 `npm install` 不會建立插件工具與完整共享框架，不能當成可用的重建流程。

本次工具實際位置如下。若插件版本或電腦不同，請改成該環境已安裝的 `data-app.mjs` 路徑，不要直接假設這個版本目錄仍存在。

```powershell
$petDataApp = 'C:\Users\zenbook\.codex\plugins\cache\openai-curated-remote\data-analytics\1.0.11\scripts\data-app.mjs'
if (-not (Test-Path -LiteralPath $petDataApp)) {
    throw '找不到 Data 插件的 data-app.mjs；請先確認插件與實際安裝路徑。'
}
node $petDataApp build --project-dir $petReportApp --separate-data
if ($LASTEXITCODE -ne 0) { throw '共享報告框架打包失敗。' }
```

然後透過同一個工具匯出：

```powershell
$petExportDir = Join-Path $petReportApp '.data-app-offline\exports'
New-Item -ItemType Directory -Force -Path $petExportDir | Out-Null
$petExport = Join-Path $petExportDir 'PET_軟體驗證完整說明報告_2026-10-24.html'
node $petDataApp export-offline --project-dir $petReportApp --output $petExport
if ($LASTEXITCODE -ne 0) { throw '離線 HTML 匯出失敗。' }
$petCloudHtml = 'C:\Users\zenbook\我的雲端硬碟\PET_軟體驗證完整說明報告_2026-10-24.html'
Copy-Item -LiteralPath $petExport -Destination $petCloudHtml -Force
```

`build --separate-data` 與 `export-offline` 是兩個分開的步驟。不要把中間建置目錄或只複製 `index.html` 當作最後的單檔離線報告。最後交付的是 `export-offline` 產生並複製到雲端硬碟根目錄的 HTML。

## 交付前檢查

開啟**最後匯出的單檔 HTML**，確認目錄、24 章文字、20 幅圖、來源檢視與 TOF 滑桿可以使用。另檢查窄視窗下的表格與圖片、教具的線段外狀態，以及日期和原始結果是否正確。可暫時離線確認內嵌圖表與資料仍能使用；外部參考連結不列入離線功能。

文字／圖表製作檢查與 PET 演算法測試是不同的紀錄。若日後重新執行測試或實驗，應保存新的日期、參數、版本及輸出雜湊，不能只將原有 61 項通過紀錄改成新日期。
