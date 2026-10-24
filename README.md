# PET：Raw Singles → Coincidence → TOF-ROR

以 Python 建立可重現的 PET 軟體參考模型，作為後續 White Rabbit 時間同步、多路 FPGA 串流與重建加速器的研究起點。程式、註解與文件以繁體中文撰寫。

本專案處理的 raw list-mode 是**尚未配對的 Singles**：每筆包含偵測時間、偵測器 ID、能量與互動座標。它不包含 ADC 波形、原始 TDC 解碼或 J-PET 雙端閃爍條校正。

## 已完成的工作

- 獨立 Conda 環境 `pet-simulation`，Python 3.11；本機資料夾直接使用 Git 版本控制，遠端為 [PET_simulation](https://github.com/t5512355123/PET_simulation)。
- 理想幾何 Singles 模擬：7 層、每層 48 個 detector、14 個傳輸 lane、不同傳輸延遲、時間及能量誤差、漏偵測和隨機背景。
- 獨立模組實作離線時間排序、能量篩選、時間窗搜尋、幾何篩選、全配對 coincidence、TOF-ROR 三維座標和體素累積。
- ROOT trees/branches 檢查、明確欄位與單位映射、GATE Singles CSV 匯入。
- 真正的 OpenGATE / Geant4 小型 BGO 晶體環生成腳本，保留 Hits、未配對 SinglesIdeal 和 Singles。
- 單元測試、獨立暴力搜尋比對、零時間雜訊解析驗證、時間誤差理論值比對、時間同步誤差掃描與 GitHub Actions。

實際執行結果與限制列在 [驗證報告](reports/validation_zh_TW.md)；研究依據列在 [來源說明](docs/sources.md)。

本機新環境已通過 **61 項測試**、Ruff 與套件相依檢查，並完成以下兩組實驗：

| 資料來源 | Singles | Coincidence pairs | 重建平均位置 mm | 中心偏差 |
|---|---:|---:|---|---:|
| 理想幾何模擬 | 15,871 | 7,262（7,194 真配對） | (19.970, −12.050, 12.022)，真配對 | 0.063 mm |
| OpenGATE / Geant4 | 11,563 | 1,921（全部為同源事件配對） | (29.907, −15.366, 9.947)，同源事件配對 | 0.381 mm |

GATE 正式案例的 29,935 個來源事件產生 107,916 Hits，再經 digitizer 成為未配對 Singles。兩組幾何與時間響應不同；平均位置偏差和單事件解析度各自列於報告。同源 EventID 不足以完成散射分類。

## 離線 HTML 完整說明報告

雲端硬碟根目錄的 `PET_軟體驗證完整說明報告_2026-10-24.html` 包含 24 章、20 幅圖及 1 個 TOF 互動教具，採淺色版面。可將單一 HTML 複製到其他電腦，以瀏覽器離線閱讀；閱讀端不需要插件或 Conda。完整 ROOT 未嵌入，CSV 衍生的完整 reviewed rows 已封裝供來源檢視。

實驗證據日期為 2026-10-19，報告整理日期為 2026-10-24；61 項測試通過是既有紀錄，製作 HTML 沒有重新執行完整測試。正文 33,307 字元包含 Markdown 標記，並非純中文字數。閱讀方法、原始框架位置與正確的重繪／打包步驟見 [HTML 報告維護說明](docs/html_report_zh_TW.md)。重新打包需要已安裝的 Data 框架工具，單獨執行 `npm install` 不足以重建這份報告。

## 啟用環境與快速重現

在 PowerShell 中切換到專案資料夾：

```powershell
cd 'C:\Users\zenbook\我的雲端硬碟\碩士班研究資料\06_PET'
. .\scripts\activate.ps1
python -c "import sys; print(sys.executable)"
```

`activate.ps1` 只在目前 PowerShell 載入 Conda hook，不修改全域 PowerShell 設定。環境啟用後也可直接使用 `conda activate pet-simulation`。每次開新終端機需要重新啟用。

如在另一台電腦重建環境，先安裝 Conda，再執行：

```powershell
conda env create -f environment.yml
conda activate pet-simulation
python -m pip install -e '.[dev]'
```

完整簡化模擬驗證：

```powershell
.\scripts\reproduce.ps1
```

或逐步執行：

```powershell
python -m pytest -q
python -m pet_sim.cli validate
python -m pet_sim.cli demo --out outputs/synthetic
python -m pet_sim.cli sweep --out outputs/timing_sweep.csv
```

安裝後同時提供 `pet-sim` 指令，例如 `pet-sim demo`。Conda 負責隔離 Python；Python 套件由 pip 安裝。`environment.yml` 是可攜設定，`requirements-lock.txt` 記錄這次實驗實際安裝的版本；鎖定清單含 OpenGATE 的 Windows 相依套件，不應視為所有作業系統通用的鎖檔。

## 怎麼看輸出

每次完整流程會在指定 `--out` 資料夾建立：

| 檔案 | 內容 |
|---|---|
| `singles_arrival_order.csv` | 模擬時依傳輸抵達時間排列的未配對事件；匯入時保留輸入順序 |
| `coincidences_ror.csv` | 每對事件的時間、位置、能量、ROR 座標及物理 TOF 有效標記 |
| `ror_volume.npz` | `counts[x,y,z]` 三維計數與各軸 mm 邊界；64³、每軸 −100 到 +100 mm |
| `ror_projections.png` | XY、XZ 投影，以及定位誤差或符合時間差分布 |
| `metrics.json` | Singles 數、pair 數、truth 關係、重建中心與單事件誤差 |
| `config.json` | 模擬、coincidence 參數與 ROOT 匯入來源 |
| `manifest.json` | Python/套件版本、Git 狀態、執行時間與程式／輸出 SHA-256 |

`physical_tof_valid=False` 的 pair 仍保留在 CSV，以便研究錯誤及隨機符合；它們不進入影像。影像範圍外的有效點也不計入 NPZ，數量另列於 metrics，避免把裁切誤認為事件遺失。

`truth_event_rmse_mm` 量測單一真配對的三維誤差；`truth_centroid_error_mm` 量測所有真配對的平均位置偏差。兩者具有不同意義。`recall_before_energy_time_geometry_cuts` 的分母是已偵測到兩光子的 synthetic 事件，包含之後被各篩選條件移除的事件，不是所有湮滅事件的偵測效率。

## Coincidence 的明確定義

1. 每端能量介於 350–650 keV，包含端點。
2. 依 `timestamp_ps`、`single_id` 排序；`arrival_time_ps` 只描述傳輸順序，不用來判斷 coincidence。
3. 兩端 `|t2 − t1| <= 4000 ps`，包含端點。這裡 `window_ps` 是**最大絕對時間差**，不是把全寬再除以二。
4. detector ID 不同，繞掃描軸的橫向角差至少 120°。
5. 保留所有合格的無序 pairs，每一對只輸出一次；同一 single 可以出現在多個 pair，沒有一對一消耗或多重事件剔除。

Truth ID 僅在配對完成後用來評估，完全不參與事件搜尋。這是可審查的離線基準，不是已完成的線上串流硬體演算法，也不保證等同任何 GATE 預設 sorter 的開窗及多重事件政策。

時間排序複雜度為 `O(N log N)`，視窗候選配對為 `O(K)`；密集的同時刻輸入最壞仍會產生 `O(N²)` 個候選與輸出。大型資料目前會整份載入記憶體，請先用 `--entry-stop` 選擇前段驗證，再規劃分塊與 watermark。

可更改篩選及模擬參數：

```powershell
pet-sim demo --events 20000 --seed 42 --window-ps 2000 --energy-kev 400 600
pet-sim demo --timing-sigma-ps 160 --hemisphere-offset-ps 300 --out outputs/offset300
```

`--config` 可指定完整或部分 `SimulationConfig` JSON；使用該選項時模擬參數以 JSON 為準，其餘 coincidence CLI 選項仍有效。

## TOF-ROR 公式與單位

內部時間使用 `int64` ps、座標使用 mm、能量使用 keV。光速 `c = 0.299792458 mm/ps`。

```text
u  = (p2 − p1) / ||p2 − p1||
m  = (p1 + p2) / 2
dt = t2 − t1
r  = m − (c × dt / 2) × u
```

來源較靠近 p2 時，t2 較早，因此 dt 較小，位置沿 u 朝 p2 移動。交換端點應得到相同結果。當 `|c × dt| > ||p2 − p1||`，估計點落在線段外；程式標記為非物理 TOF，不以裁切偽造有效位置。

若每一端的獨立時間誤差標準差為 σ，兩端時間差標準差為 `sqrt(2) × σ`，沿 LOR 的位置標準差為 `c × σ / sqrt(2)`。預設 σ=80 ps 時約 16.96 mm；CTR FWHM 約 266.42 ps。三維空間的誤差仍主要沿每個事件自己的 LOR，不能直接把這個值當成三個軸各自的解析度。

本版重建 **ROR 中心點** 並累積直方圖；尚未沿 LOR 展開有限寬度 Gaussian ROR 核，也未實作 MLEM/OSEM。

## 簡化資料模型的範圍

預設光源 `(20, −12, 12) mm`，掃描半徑 400 mm、有效軸向長度 210 mm。光子背對背、方向各向同性，保留兩光子均擊中有效圓筒的方向後再套用各端 95% 偵測效率。`n_events=8000` 指幾何接受後、效率篩選前的事件數。因此 `activity_bq` 控制條件接受事件的時間間隔，不能用此模型推算絕對掃描器靈敏度。

Detector ID 依環層和角度量化，**互動座標保留連續圓筒交點**，適合驗證 TOF 公式；沒有把互動點替換成晶體中心。預設每端 Gaussian 時間 σ=80 ps、能量 σ=25 keV，能量低於零時飽和為零；另外加入 700 個獨立背景 singles。不模擬散射、非共線性、正電子射程、衰減或電子學死時間。

14-lane 傳輸使用固定 lane 延遲和非負抵達抖動，會讓抵達順序不同於偵測時間。`hemisphere_offset_ps` 額外偏移 x≥0 半環的量測時間，用來研究跨板時鐘偏移；它與傳輸延遲是不同的量。`sweep` 為了隔離此影響，使用無背景、100% 效率、較低事件率的條件。

## 真正的 OpenGATE Singles

安裝及生成：

```powershell
python -m pip install opengate==10.1.1
python scripts/generate_gate_singles.py --dry-run
python scripts/generate_gate_singles.py --output data/raw/gate_demo --expected-events 30000
pet-sim inspect-root data/raw/gate_demo/singles.root
pet-sim import-root data/raw/gate_demo/singles.root --tree Singles --mapping data/raw/gate_demo/mapping.json --out data/processed/gate_singles.csv
pet-sim run data/processed/gate_singles.csv --source-mm 30 -15 10 --out outputs/gate
```

本機已生成 `data/raw/gate_demo/singles.root`，可直接從 inspect/import/run 開始。重新生成請使用另一個 `--output` 資料夾，並修改後續路徑；生成腳本會保留既有原始檔。

首次執行 OpenGATE 會下載 Geant4 資料集，耗時與磁碟使用量較大。生成腳本採活動度與時長產生有時間間隔的湮滅事件；`expected-events` 是 Poisson 流的期望事件數，實際數量以 `metadata.json` 為準。腳本避免覆寫已存在的 `singles.root`。

這個模型使用 96 個 BGO 晶體、半徑 200 mm、偏心點光源 `(30, −15, 10) mm`、兩端差值 CTR FWHM 200 ps。它直接產生背對背 511 keV 光子並做 Geant4 電磁傳輸，仍不是完整放射性衰變、受測物或臨床掃描儀模型。`Hits → SinglesIdeal` 的事件內加總屬於 digitizer；本專案的 coincidence finder 不讀 truth 作配對。

對 GATE ROOT 不可猜單位：舊版 GATE 的 `time` 常以 s 表示，這個 GATE 10 範例的 `GlobalTime` 為 ns；`TotalEnergyDeposit` 為 MeV、位置為 mm。必須先 inspect，再確認對應的 mapping。

ROOT 匯入及重建的實際指令請見 [驗證報告](reports/validation_zh_TW.md)。對自己的 ROOT 可從 [mapping 範例](configs/gate_branch_map.example.json) 修改：

```powershell
pet-sim inspect-root your_gate_output.root
pet-sim import-root your_gate_output.root --tree Singles --mapping configs/gate_branch_map.example.json --out data/processed/singles.csv
pet-sim run data/processed/singles.csv --out outputs/gate
```

`crystalID` 可能僅在 block/module 內唯一，應先建立全域 detector ID。複合字串識別碼可在 mapping 明訂 `detector_id_encoding: "categorical"`，其編碼表會寫入 provenance；不同檔案或不同 `entry-stop` 選取範圍的編碼需依表重新對應，不能直接混合。沒有 detector ID 的資料不能僅憑分支名稱假設可直接使用。

共同時間原點可在 mapping 明訂 `time_origin`（使用來源時間單位）。整數時間戳不先轉 float；若 ROOT 已用浮點儲存而喪失精度，轉換無法恢復。匯入產生的 `arrival_time_ps` 和 `lane_id` 是介面佔位，並非實測傳輸資訊，限制會寫入 `.provenance.json`。

GATE 的 event ID 代表同次衰變；晶體內散射可讓同一事件留下多筆 Singles，因此 `same_truth_event_fraction` 只是同事件比例，不能直接當作實機 true-coincidence precision。跨 run 需同時映射 run ID；跨檔案還需另外識別來源。只有已配對 Coincidences 的資料無法還原原始 Singles，不能用來完整驗證自己的 finder。

## 程式結構

```text
src/pet_sim/
  config.py          參數、光速、統一單位
  simulation.py      理想幾何 Singles、背景及傳輸亂序
  coincidence.py     資料驗證、滑動視窗、獨立暴力參考
  reconstruction.py TOF-ROR 中心與三維直方圖
  root_io.py         ROOT 結構檢查、明確分支/單位匯入
  metrics.py         事件統計與定位誤差
  plotting.py        XY/XZ 投影和誤差圖
  pipeline.py        完整流程與輸出追溯
  validation.py      解析驗證、時鐘誤差掃描
  cli.py             命令列入口
scripts/             環境啟用、重現、OpenGATE 生成
tests/               有效性、端點與回歸測試
reports/             本次可追溯的精簡結果及圖表
data/                本機原始/處理資料，Git 忽略
outputs/             本機完整輸出，Git 忽略
```

## Git 與後續研究

`data/`、`outputs/`、ROOT、大型壓縮檔與環境不提交到 GitHub；程式、測試、文件、精簡數值和示意圖會提交。完整 CSV/ROOT 保留在本機並可依固定 seed 或生成設定重新產生。

```powershell
git status
git add src tests scripts configs docs reports README.md
git commit -m "Describe the research change"
git push origin main
```

後續建議依序加入：GATE 官方 sorter 的同政策交叉比對、真實 detector 位置及時間校正、散射/隨機分類、有限寬度 ROR 核、14-lane reorder buffer/watermark、固定點量化與 FPGA golden vectors、MLEM/OSEM 對照。現在的測試是 Python 演算法與簡化物理流程驗證，尚未主張臨床定量影像品質或 FPGA 端即時吞吐量。
