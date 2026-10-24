"""HTML 教學報告正文。採短句、固定名詞與分步說明，不宣稱中文 STE 認證。"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def chapters():
    syn = json.loads((ROOT / "reports/synthetic_metrics.json").read_text(encoding="utf-8-sig"))
    gate = json.loads((ROOT / "reports/gate_metrics.json").read_text(encoding="utf-8-sig"))
    pairs = pd.read_csv(ROOT / "outputs/synthetic/coincidences_ror.csv")
    row = pairs.loc[pairs.same_truth_event].iloc[0]
    p1 = np.array([row.x1_mm, row.y1_mm, row.z1_mm])
    p2 = np.array([row.x2_mm, row.y2_mm, row.z2_mm])
    length = np.linalg.norm(p2 - p1)
    unit = (p2 - p1) / length
    mid = (p1 + p2) / 2
    point = [row.ror_x_mm, row.ror_y_mm, row.ror_z_mm]

    def vector(x):
        return "(" + ", ".join(f"{v:.6f}" for v in x) + ")"

    sections = []

    def add(id_, title, body, query="parameters", figs=None):
        sections.append(
            {"id": id_, "title": title, "body": body.strip(), "query": query, "figures": figs or []}
        )

    add(
        "summary",
        "先看重點：我們已完成兩種模擬與同一條重建流程",
        r"""
## 先看重點

本專案已建立 Python 參考程式。程式先讀取尚未配對的偵測事件。程式再找出時間接近、能量合格、位置合格的事件對。最後，程式使用兩端的時間差，估計每個事件對的三維位置，並將位置累積成影像。

我們使用兩種資料。第一種資料由簡化的幾何模型產生。第二種資料由 OpenGATE 與 Geant4 產生。兩種資料都來自本機模擬，沒有使用病患、動物或商用掃描器的量測資料。

| 已完成項目 | 實際結果 |
|---|---|
| 理想幾何模型 | 15,871 筆 Singles，找到 7,262 組事件對，其中 7,194 組是真配對。 |
| OpenGATE 物理模型 | 29,935 個來源事件產生 107,916 筆 Hits，再形成 11,563 筆 Singles。Python 找到 1,921 組同源事件對。 |
| 程式測試 | 2026-10-19 的紀錄顯示 61 項測試通過。獨立暴力搜尋與主要配對程式得到相同結果。 |
| 可重現資料 | 已保存設定、固定亂數種子、套件版本、CSV、ROOT、三維體素及檔案雜湊。 |
| 尚未完成項目 | 線上串流、FPGA、實際 White Rabbit 同步、有限寬度 ROR 核、MLEM、OSEM 與臨床校正。 |

**你現在已經有可檢查的軟體基準。下一步最有價值的工作，是先確認相同配對政策下的結果，再把離線排序改成可驗證的多路串流處理。**

### 這份報告怎麼讀

第一次接觸 PET：依照目錄順序閱讀。先理解 Hits、Singles 與 Coincidence 的差別。再看兩種模擬。最後閱讀結果及下一步。

只想重現結果：閱讀「操作步驟」與「檔案與模組」。所有必要指令都放在本報告中。

想設計 FPGA：先閱讀時間差、配對政策、時間同步與限制。再閱讀下一步的驗收條件。

### 日期與文字規則

實驗執行日期是 **2026-10-19**。本說明報告整理日期是 **2026-10-24，Asia/Taipei**。本次重新盤點既有檔案及雜湊，並重繪說明圖；沒有重新執行完整 Geant4 實驗。不能把報告日期當成新一輪實驗日期。

你提到的 ADS-STE100，正式名稱是 **ASD-STE100**。本報告參考其清楚技術寫作原則：使用短句、每段說明一個主題、先定義再解釋、保持名詞一致。ASD-STE100 規範英文。這份繁體中文報告不宣稱通過正式 STE 認證。[官方說明](https://www.asd-ste100.org/STE_faq.html)
""",
        "summary",
        ["01_pipeline", "20_stage_counts"],
    )

    add(
        "purpose",
        "01｜這次工作的目標與邊界",
        r"""
## 01｜這次工作的目標與邊界

### 我們要回答的問題

1. 一串尚未配對的偵測事件，能否經由程式形成合格的事件對？
2. 事件的抵達順序被打亂後，離線程式能否仍找回相同的事件對？
3. 兩端時間差的單位與正負號，能否得到合理的三維位置？
4. 時間抖動與固定時鐘偏移，會如何影響估計位置？
5. 未來硬體演算法應該拿什麼結果當比較基準？

### 我實際建立了什麼

我建立 `pet-simulation` Conda 環境。我把資料產生、資料匯入、配對、重建、統計、繪圖與驗證拆成獨立模組。我另外建立真正的 OpenGATE 生成腳本。程式的註解與操作文件使用繁體中文。

我使用 Git 保存程式版本。我將程式、測試、文件與精簡成果推送到 [PET_simulation 儲存庫](https://github.com/t5512355123/PET_simulation)。完整事件資料保存在本機。環境、下載快取及完整 ROOT 沒有提交到 Git。

### 這條流程的輸入與輸出

輸入是一筆一筆的 **Singles**。每筆至少需要偵測時間、偵測器識別碼、能量與互動位置。

輸出有兩層。第一層是事件對及每對的估計座標。第二層是把估計座標放入三維格子後的計數影像。

本次程式從 Singles 開始。程式沒有解析原始電壓波形、ADC 取樣或 TDC 碼。這個邊界很重要，因為「raw list-mode」在不同系統可能代表不同資料層級。

### 這是後續研究的參考模型

參考模型常稱為 **golden model**。你可以先信任其已驗證的輸入與輸出規則。之後改成串流或 FPGA 時，新的程式必須與此基準比較。

此處的「信任」有明確範圍：已測試的配對政策、單位、公式、資料與參數。它不代表所有掃描器、所有事件率或所有物理效應都已驗證。
""",
        "summary",
    )

    add(
        "pet",
        "02｜PET 如何由兩個光子推估一個位置",
        r"""
## 02｜PET 如何由兩個光子推估一個位置

### PET 的基本概念

**PET** 是 Positron Emission Tomography，中文通常稱為正子斷層造影。在實際 PET 系統中，放射性示蹤劑會產生正子。正子與電子湮滅後，通常形成兩個接近相反方向的 511 keV 光子。環狀偵測器量測光子到達的位置與時間。

偵測到一個光子，只能知道某個偵測器收到訊號。找到同一次湮滅的兩個光子後，就可以連接兩個偵測位置。這條線稱為 **LOR**。

若兩端能量與時間差符合條件，程式會保留這個事件對。這個選取動作稱為 **coincidence selection**。時間接近只是候選條件，並不保證兩筆資料真的來自同一次湮滅。

### 為什麼需要 TOF

**TOF** 是 Time of Flight，這裡使用兩個光子的到達時間差。若來源較靠近其中一端，光子通常會較早到達該端。時間差因此能提供沿 LOR 的位置資訊。

沒有 TOF 時，一個事件對主要提供一條線上的可能位置。有 TOF 時，可以把可能位置限制到線上的一個區域。這個區域稱為 **ROR：Region of Response**。

### 本專案的來源比較簡單

本專案直接產生背對背的 511 keV 光子對。程式沒有模擬放射性核種衰變、正子移動距離或正子的停止位置。理想模型也沒有散射與非共線性。OpenGATE 模型另外包含光子在材料中的電磁交互作用。

因此，這裡的「來源事件」是模型中的一個光子對生成事件。不要把它解讀成完整放射性示蹤劑的生物分布模型。

### 從原始訊號到影像有多個資料層級

| 資料層級 | 一筆資料代表什麼 | 本次是否處理 |
|---|---|---|
| ADC/TDC 或波形 | 電壓取樣、時間計數器或電子學原始碼 | 尚未處理。 |
| Hit | Geant4 記錄的一次能量沉積或相關步進紀錄 | OpenGATE 有產生並保存。 |
| Single | 經 digitizer 整理的一次偵測事件 | 是主要配對輸入。 |
| Coincidence pair | 通過規則的兩筆 Singles | 由 Python 搜尋。 |
| LOR / ROR center | 兩端幾何與時間差形成的線及位置估計 | 由 Python 計算。 |
| Voxel image | 每個三維格子內累積的位置數 | 本版的影像輸出。 |

一個光子可能留下多個 Hits。同一個來源事件也可能留下多個 Singles。因此，這些層級的數量不能直接視為同一種事件數。
""",
        "gate_metadata",
        ["04_tof_geometry"],
    )

    add(
        "software",
        "03｜每個軟體工具負責什麼",
        r"""
## 03｜每個軟體工具負責什麼

工具各自負責不同工作。Python 是控制與分析程式。OpenGATE 負責建立物理模型。Geant4 負責粒子傳輸。Git 負責版本記錄。這些工具不能互相替代。

| 工具 | 簡單說明 | 本專案的工作 |
|---|---|---|
| Conda | 建立獨立的軟體環境 | 建立 `pet-simulation`，避免與其他研究套件混用。 |
| Python 3.11.17 | 執行程式的語言與直譯器 | 執行資料生成、配對、重建與報告程式。 |
| pip | Python 套件安裝工具 | 在 Conda 環境內安裝本專案與相依套件。 |
| NumPy 2.4.6 | 處理陣列與數值計算 | 產生亂數、計算座標、計算距離及三維直方圖。 |
| pandas 2.3.3 | 處理有欄位名稱的表格 | 讀寫 CSV、排序時間戳與保存事件欄位。 |
| Matplotlib 3.11.2 | 產生圖形 | 畫位置分布、能量分布、時間差與誤差圖。 |
| uproot 5.7.7 | 以 Python 讀取 ROOT 檔案 | 檢查資料樹與分支，匯入 Singles；不需要先安裝桌面 ROOT 程式。 |
| OpenGATE 10.1.1 | 以 Python 建立醫學影像粒子模擬 | 定義 BGO 晶體、光源、物理設定與 digitizer。 |
| opengate-core 10.1.1 | OpenGATE 的原生核心套件 | 提供與 Geant4 連接的編譯程式。 |
| Geant4 | 粒子與材料交互作用引擎 | 計算光子傳輸、能量沉積及晶體內散射。核心版本字串未單獨保存，不能只由資料集參照網址推論版本。 |
| pytest 9.1.1 | 自動測試工具 | 比較輸出、檢查邊界、檢查公式及錯誤輸入。 |
| Ruff 0.17.1 | Python 靜態檢查工具 | 檢查未使用變數、匯入順序及部分容易出錯的寫法。通過 Ruff 不等於物理模型正確。 |
| Git | 本機版本控制工具 | 記錄程式與文件的每次提交。 |
| GitHub | 遠端儲存庫與協作平台 | 保存可取得的程式與精簡成果。 |
| GitHub Actions / CI | 在遠端自動執行檢查 | 推送後執行 Ruff、pytest 及解析驗證。CI 表示持續整合。 |

### 報告工具與 PET 工具分開

這份報告使用 HTML 表達結構、CSS 設定淺色外觀、JavaScript 提供互動。報告封裝流程使用 Node.js 與共享的 React 顯示元件。這些工具只負責呈現報告，沒有參與 PET 粒子傳輸。

你只要使用一般桌面瀏覽器，就能閱讀匯出的單一 HTML。開啟報告不會重新執行 OpenGATE，也不會重新計算一整批事件。

### 三個設定檔有不同用途

`environment.yml` 說明如何建立環境。`pyproject.toml` 說明 Python 套件名稱、入口指令與相依套件範圍。`requirements-lock.txt` 保存本次環境的實際套件版本。

固定亂數種子仍需要固定程式與套件版本。若你改變生成程式或亂數呼叫順序，結果可能改變。這也是為什麼我們另外保存 Git 版本與原始碼雜湊。
""",
        "validation",
    )

    add(
        "sources",
        "04｜資料從哪裡來：兩種本機模擬",
        r"""
## 04｜資料從哪裡來：兩種本機模擬

### 資料 A：理想幾何模型

`src/pet_sim/simulation.py` 使用數學公式與亂數產生資料。它知道光源在哪裡，也知道哪兩筆 Singles 來自同一個來源事件。這些已知答案稱為 **ground truth，簡稱 truth**。

這種資料適合檢查時間單位、配對規則與 TOF 正負號。因為模型簡單，我們可以預先推導某些誤差的上限及期望值。

### 資料 B：OpenGATE 物理模型

`scripts/generate_gate_singles.py` 在本機建立 OpenGATE 模擬。Geant4 計算光子與材料的交互作用。digitizer 再將 Hits 整理成尚未配對的 Singles。資料寫入 `data/raw/gate_demo/singles.root`。

這是實際執行物理模擬後產生的 ROOT。它不是從數學模型換副檔名得到的檔案。它也不是臨床掃描器量測檔。

### 公開取得的部分是工具與物理資料

本次使用公開的 OpenGATE 軟體、官方範例 API 與 Geant4 物理資料。初次安裝時，程式從 CERN 取得 OpenGATE 所需的 12 份資料集。這些資料集提供物理交互作用所需的資料；它們不是預先掃描好的 PET 病患事件。

本次沒有下載先前討論的 17.9 GB 公開 GATE ROOT、OMEGA 量測資料或 Siemens Inveon 動物掃描資料。這些仍可作為後續資料來源。不能把它們算進本次已完成的驗證。

### 為什麼先用這兩種資料

先用簡單模型，可以找到數值與程式錯誤。再用 Geant4 資料，可以檢查真實 ROOT 欄位、單位與較複雜的互動紀錄。兩個階段的證據互補。

兩個模型的幾何與時間響應不同。因此，不能直接用兩組 RMSE 的大小，判定哪個重建方法較好。本次兩組資料都使用同一個 Python 配對及 ROR 中心點演算法。
""",
        "gate_metadata",
    )

    add(
        "synthetic",
        "05｜理想幾何模型：程式如何產生 Singles",
        r"""
## 05｜理想幾何模型：程式如何產生 Singles

### 先設定掃描器與光源

| 設定 | 預設值 | 意義 |
|---|---:|---|
| 光源位置 | (20, −12, 12) mm | 固定偏心點光源，便於檢查正負號。 |
| 圓筒半徑 | 400 mm | 偵測位置落在圓筒表面。 |
| 環層數 × 每層識別數 | 7 × 48 = 336 | 用於建立 detector ID。 |
| 每層軸向間距 | 30 mm | 有效軸向總長為 210 mm。 |
| 幾何接受事件數 | 8,000 | 兩光子均能到達有效軸向範圍的事件。 |
| 每光子偵測效率 | 95% | 各光子獨立決定是否留下 Single。 |
| 每端時間誤差 σ | 80 ps | 獨立、零均值的高斯時間誤差。 |
| 每端能量誤差 σ | 25 keV | 以 511 keV 為平均，負值設為零。 |
| 背景 Singles | 700 | 不屬於任何正確光子對的獨立事件。 |
| 傳輸 lane 數 | 14 | 模擬多路資料抵達順序。 |
| seed | 20261019 | 固定的亂數起始設定。 |

### 步驟 1：產生一條隨機方向

程式對三個座標抽取常態亂數，再將向量長度正規化為 1。這會產生各向同性的方向。兩個光子沿相反方向移動。

程式接著計算直線與圓筒表面的兩個交點。若任一交點的 z 座標落在有效軸向範圍外，程式就重新取樣方向。

這個重新取樣會持續到取得 8,000 個合格方向。因此，`n_events` 不是全部各向同性湮滅事件的數量。它是通過幾何條件後、尚未套用偵測效率的數量。

### 圓筒交點公式

令光源為 `s`，單位方向為 `d`，光子路徑為 `p = s + λd`。程式要求 `pₓ² + pᵧ² = R²`。定義 `a = dₓ²+dᵧ²`、`b = sₓdₓ+sᵧdᵧ` 後，兩個解為：

```text
λ± = [−b ± sqrt(b² + a(R² − sₓ² − sᵧ²))] / a
p₁ = s + λ+ d
p₂ = s + λ− d
```

光子飛行距離分別為 `λ+` 與 `−λ−`。程式保留這兩個連續交點，沒有把它們移到晶體中心。

### 步驟 2：建立 detector ID

程式依 z 座標決定環層，依 XY 平面上的角度決定環向編號。全域編號為 `ring × 48 + sector`。

**只有識別碼被量化。位置仍是連續圓筒交點。** 因此，這個模型尚未包含有限晶體尺寸造成的位置讀出誤差。

### 步驟 3：建立事件時間

程式以指數分布產生相鄰事件的等待時間，再累加成生成時間。指數等待時間對應 Poisson 事件流。預設條件接受事件率為每秒 2,000,000 個事件。

```text
等待時間平均值 = 10¹² / activity_bq  （ps）
生成時間 Tₙ = 前 n 個等待時間的總和
量測時間 t = Tₙ + 飛行距離/c + 時間誤差 + 半環偏移
```

這裡的 `activity_bq` 是已通過幾何條件之事件流的參數。它不能直接拿來計算完整掃描器的絕對靈敏度。

### 步驟 4：加入能量與漏偵測

每個光子的量測能量為 `511 + 高斯誤差` keV。若結果小於零，程式設為零。每個光子再以 95% 機率留下資料。

因此，一個來源事件可能留下兩筆、一筆或零筆 Singles。兩端都被偵測到的理論平均比例約為 `0.95² = 90.25%`，但每次有限樣本仍有隨機變動。

### 步驟 5：加入背景與傳輸延遲

背景事件的能量均勻分布於 100–800 keV。背景位置隨機分布在有效圓筒表面。背景時間獨立取樣。背景 truth ID 設為 −1。

每筆資料的 lane 由 `detector_id % 14` 決定。各 lane 使用固定的隨機延遲，範圍為 0–8000 ps。每筆資料另加 0–1000 ps 的非負抵達抖動。程式最後依抵達時間排序並輸出。

這個模型沒有模擬材料交互作用、衰減、散射、非共線性、正子射程與電子學死時間。它的用途是驗證資料處理規則。
""",
        "parameters",
        ["02_synthetic_geometry", "06_lane_delays"],
    )

    add(
        "gate",
        "06｜OpenGATE 模型：由材料交互作用形成 Singles",
        r"""
## 06｜OpenGATE 模型：由材料交互作用形成 Singles

### 幾何與物理設定

本例在半徑 200 mm 的圓周上放置 96 個 BGO 晶體。每個晶體的徑向、切向、軸向尺寸為 20 × 10 × 100 mm。光源位置為 (30, −15, 10) mm。

**BGO** 是 Bi₄Ge₃O₁₂。它是一種閃爍晶體。本例以 7.13 g/cm³ 定義密度。程式使用 Geant4 的電磁模型 `G4EmStandardPhysics_option4`，並設定 0.1 mm 的產生截斷參數。這個截斷參數用於處理次級粒子產生；它不是影像體素大小，也不是保證的追蹤步長。

世界體積為 600 × 600 × 300 mm，材料為空氣。沒有放置病患或組織假體。`sim.visu=False` 表示不開啟 Geant4 的視覺視窗，並不表示省略粒子物理計算。

### 光源與時間設定

來源直接產生各向同性、背對背的 511 keV 光子。活度參數為 200,000 Bq，模擬時間為 0.15 s。期望事件數因此為 `200,000 × 0.15 = 30,000`。

實際事件數為 29,935。這與期望值不同，是 Poisson 事件流的正常變動。程式沒有用 truth ID 預先挑選正確的事件對。

程式使用活度與時長，讓事件分布在時間軸上。固定事件數模式在此 API 的時間處理方式不同，可能讓生成時間集中；這不適合直接作為本例的連續 coincidence 輸入。

### Digitizer 的三個步驟

1. **Hits actor** 保存晶體中的能量沉積與相關欄位。正式案例共有 107,916 筆 Hits。
2. **Adder actor** 依來源事件與晶體彙整資料。能量使用加總，位置使用能量加權互動座標。它形成 11,563 筆 `SinglesIdeal`。
3. **Blurring actor** 對偵測時間加入獨立高斯誤差，輸出 11,563 筆 `Singles`。加入的時間誤差對應 CTR FWHM 200 ps，因此每端 FWHM 為 `200/sqrt(2) ≈ 141.421 ps`。這是模型設定，不是另行量測的整體系統 CTR。

Adder 使用事件資訊，是 digitizer 在模擬內整理能量沉積的行為。之後的 Python coincidence finder 不讀 truth 來決定配對。這兩個階段的工作不能混在一起解讀。

### 同一來源可以留下多筆 Singles

正式資料中，有 7,451 個來源事件至少留下 1 筆 Single。這些事件留下的 Singles 數分布為：1 筆有 4,012 個事件；2 筆有 2,802 個；3 筆有 602 個；4 筆有 34 個；5 筆有 1 個。

同一個光子可能在不同晶體互動。同一來源事件因此不一定只有兩筆 Singles。`Hits → Singles` 的筆數下降，也不能直接視為偵測效率。

### 已包含與未包含的物理效應

本例包含光子在晶體及世界材料中的電磁傳輸，並保留晶體互動與散射的結果。它沒有模擬完整的光學閃爍光子、光感測器、電子學讀出、死時間或能量解析度模型。

本例也沒有受測物、完整衰減／散射／隨機符合修正，以及實機校準。因此，這份資料可以驗證程式介面與較複雜的模擬流程，尚不足以代表完整臨床掃描器。
""",
        "gate_metadata",
        ["03_gate_geometry"],
    )

    add(
        "formats",
        "07｜檔案、欄位與單位：程式實際讀到什麼",
        r"""
## 07｜檔案、欄位與單位：程式實際讀到什麼

### ROOT、TTree 與 Branch

**ROOT** 是科學資料檔案格式與工具生態系。本例的 ROOT 檔內有 `Hits`、`SinglesIdeal`、`Singles` 三棵資料樹。**TTree** 可先理解成資料表。**Branch** 可先理解成其中一個欄位。匯入器也支援 uproot 能讀取的 RNTuple 容器。

程式先用 `inspect-root` 列出結構，再用 mapping 明確指定欄位。程式不會因為副檔名是 `.root`，就假定內容一定是可用的 Singles。

### 本例的單位轉換

| GATE 10 ROOT 欄位 | 原單位 | 統一欄位 | 轉換 |
|---|---|---|---|
| `GlobalTime` | ns | `timestamp_ps` | 乘 1000，再依明確規則取整數。 |
| `TotalEnergyDeposit` | MeV | `energy_kev` | 乘 1000，成為 keV。 |
| `PostPosition_X/Y/Z` | mm | `x_mm/y_mm/z_mm` | 保持 mm。 |
| `PreStepUniqueVolumeID` | 複合字串 | `detector_id` | 明確選用 categorical 編碼並保存對照表。 |
| `EventID`、`RunID` | 識別碼 | `truth_event_id`、`truth_run_id` | 保留整數，僅供事後評估。 |

舊版 GATE 的 `time` 可能以秒儲存。不要把本例的 ns 倍率套用到所有版本。若時間單位錯 1000 倍，配對與位置都可能失去意義。

### 統一 Singles 格式

| 欄位 | 意義 | 是否用於配對 |
|---|---|---|
| `single_id` | 本次載入中唯一的列識別碼 | 用來追蹤與穩定排序。 |
| `timestamp_ps` | 偵測器的量測時間，int64 ps | 是。 |
| `detector_id` | 全域偵測位置識別碼 | 是，用來排除同一偵測器。 |
| `x_mm/y_mm/z_mm` | 偵測互動位置 | 是，用來檢查角度及建立 LOR。 |
| `energy_kev` | 偵測能量 | 是。 |
| `arrival_time_ps` | 模擬抵達時間；GATE 匯入時為佔位值 | 不用於 coincidence 判斷。 |
| `lane_id` | 理想模型的輸入通道群；GATE 匯入時為 0 | 不用於 coincidence 判斷。 |
| `truth_event_id` | 模擬來源事件識別碼 | 否，只用於評估。 |
| `truth_run_id` | 模擬執行識別碼 | 否，只用於區分不同 run。 |
| `truth_source_x_mm/y_mm/z_mm` | 模擬來源位置 | 否，只用於評估。 |

GATE 匯入器將 `arrival_time_ps` 設為量測時間的複本，並把 `lane_id` 設為 0。這些不是量測到的網路資訊。因此，GATE 匯入後的「逆序次數 0」不能證明真實傳輸沒有亂序。

### 全域 ID 與跨檔案問題

某些資料的 `crystalID` 只在 module 或 block 內唯一。匯入前必須確認它能否表示全域偵測器。本例使用複合 volume ID，避免只保留局部晶體編號。

字串編碼表以本次載入範圍建立。不同檔案或不同 `entry-stop` 範圍，可能得到不同編碼。合併前必須重新對應。EventID 也可能在不同 run 重設；跨 run 應同時使用 RunID，跨檔案還需要來源檔識別。

### 為什麼時間使用 int64

int64 是 64 位元整數。它可以保存大的絕對計數，也能保留相差 1 ps 的整數值。程式先以整數相減，再轉為浮點做位置計算，並檢查溢位。

浮點數無法對任意大的絕對時間都保留 1 ps 差異。若來源已使用浮點並丟失精度，之後轉成整數無法恢復。必要時，先用 mapping 的 `time_origin` 明訂共同時間原點。

**ps 是檔案單位。它不代表偵測器具有 1 ps 的時間解析度。**
""",
        "parameters",
        ["19_units_precision"],
    )

    add(
        "arrival",
        "08｜量測時間與抵達時間：為什麼需要排序",
        r"""
## 08｜量測時間與抵達時間：為什麼需要排序

### 先分清兩個時間

**量測時間 timestamp** 描述偵測器量到事件的時間。**抵達時間 arrival time** 描述資料送到接收端的順序。資料的傳輸延遲不同，就可能造成後發生的事件先抵達。

這種順序稱為 **OOO：Out-of-Order，亂序**。本例用 14 個 lane 的固定延遲及每筆抵達抖動，建立可觀察的亂序輸入。

```text
lane = detector_id % 14
arrival_time_ps = timestamp_ps + lane_delay[lane] + arrival_jitter
```

此式只用來產生教學用的抵達順序。接收端沒有獨立的硬體時鐘模型。未來研究 clock drift、串流延遲界限或 watermark 時，應把物理偵測時間、本地量測時鐘與接收端時鐘分開建模。

### 程式目前怎麼處理

程式讀入完整資料後，依 `timestamp_ps` 排序。時間相同時，程式依 `single_id` 排序。配對演算法接著處理排序後的事件。

這是離線方法。它可以等待整個檔案到齊。它尚未解決線上系統何時能確定「更早的資料不會再來」。

### 本次亂序結果如何

依抵達時間排列的 15,871 筆理想模型資料中，有 **3,495 次相鄰時間戳逆序**。這表示某筆抵達資料的 timestamp 小於前一筆的 timestamp。

3,495 是相鄰逆序的次數。它不是所有兩兩逆序對的總數，也不是封包遺失數。圖中只取前 40 筆實際資料來方便閱讀；完整統計使用整個檔案。

獨立驗證另外打亂同一批資料的輸入順序。主要配對程式仍得到相同的 pair ID 集合。這證明已測試資料的離線配對不依賴輸入抵達順序。
""",
        "synthetic_events",
        ["05_arrival_order"],
    )

    add(
        "coincidence",
        "09｜Coincidence finder 如何決定兩筆資料能配對",
        r"""
## 09｜Coincidence finder 如何決定兩筆資料能配對

### 四個篩選條件

1. 每端能量都符合 `350 ≤ E ≤ 650 keV`。
2. 兩筆資料符合 `|t₂ − t₁| ≤ 4000 ps`。
3. 兩端 detector ID 不同。
4. 兩個位置在 XY 平面繞原點的角差至少為 120°。

所有邊界都包含端點。這裡的 4000 ps 表示最大絕對時間差，也就是 4 ns。不要再把這個值當成全寬而除以二。

### 主要演算法：排序後的滑動視窗

程式先移除能量不合格的 Singles，再依 timestamp 排序。對每筆事件 A，程式向後檢查事件 B。若時間差超過 4000 ps，因為後面的時間只會更晚，程式就停止這一輪搜尋。

時間合格時，程式檢查 detector ID 與橫向角差。通過後就輸出事件對。程式不會以「最接近的時間差」強迫只挑一筆。

```text
先檢查欄位、型態、缺值與唯一single_id
保留能量合格資料
依(timestamp_ps, single_id)排序
對每個A：
    從A後一筆開始檢查B
    若時間差大於門檻：停止往後搜尋
    若偵測器不同且角度合格：輸出(A,B)
```

### 全配對政策是什麼

本版使用 **all-pairs，全配對政策**。同一筆 Single 可以出現在多個事件對。每個無序事件對只輸出一次。

例如，A、B、C 若彼此都符合條件，程式可輸出 AB、AC、BC。它不會先用掉 A，之後禁止 A 再配對。這與 greedy 一對一配對或 RemoveMultiples 政策不同。

所以，兩個程式的 pair 數不同，不一定表示其中一個錯誤。先確認開窗方式、幾何條件與多重事件政策是否一致，再比較結果。

### Truth 沒有參與搜尋

程式在輸出 pair 後，才比較兩端的 truth ID。這個比較只建立評估標籤。你移除或改變 truth 欄位，不應改變配對 ID 集合；測試也檢查此行為。

### 複雜度與可用範圍

排序約需要 `O(N log N)`。之後檢查 `K` 個窗內候選，約需要 `O(K)`。若大量事件擠在同一時間窗，`K` 最壞仍可達 `O(N²)`。

目前程式整份載入記憶體。它是參考基準，尚未宣稱即時吞吐率或大型資料的固定記憶體上限。
""",
        "parameters",
        ["07_energy_windows", "08_time_differences", "10_pair_matrix"],
    )

    add(
        "truth",
        "10｜配對完成後，如何知道結果是否正確",
        r"""
## 10｜配對完成後，如何知道結果是否正確

### 理想模型可以使用明確真值

理想模型每個來源事件最多產生兩筆可偵測 Singles。兩端 truth ID 相同且非負時，就是真配對。其他通過選取的組合是假配對。背景 truth ID 為 −1。

本次 7,262 組 pair 中，7,194 組是真配對，68 組是假配對。真配對比例為 `7194/7262 ≈ 99.064%`。

已偵測到兩端的理想事件共有 7,194 個。這些事件在本次預設篩選下都找回了。因此，相對此分母的 recall 為 100%。這不表示 8,000 個幾何接受事件都被偵測，更不表示完整掃描器偵測效率為 100%。

### GATE 只先檢查同源事件

GATE 的 EventID 與 RunID 一致，表示兩筆資料屬於同一個來源事件。它不能證明兩端沒有發生晶體散射。若要完整分類 true、scatter、random，需要更多粒子軌跡與交互作用資訊。

正式 GATE 的 1,921 組 pair 都屬於同源事件。這是本次資料及篩選條件下的觀察，不能稱為對所有資料都達到 100% precision。

### 幾何上的 TOF 有效也不等於配對正確

程式會檢查估計位置是否在線段內。即使位置在線段內，來自不同來源的兩筆資料仍可能偶然通過。

理想模型正好提供例子：68 組假配對中，49 組的 TOF 中心仍在線段內，另外 19 組在線段外。單靠物理線段條件，無法排除所有隨機符合。

### 不要把「真值」帶入正式重建

真實掃描器通常不知道每個事件的真實來源座標與 EventID。我們使用這些欄位檢查模擬結果，沒有使用它們來挑選配對或計算 ROR 位置。
""",
        "summary",
        ["09_pair_composition"],
    )

    add(
        "tof",
        "11｜TOF-ROR 公式：時間差如何變成三維位置",
        r"""
## 11｜TOF-ROR 公式：時間差如何變成三維位置

### 先固定正負號

令兩個偵測位置為 `p₁` 與 `p₂`，時間為 `t₁` 與 `t₂`。本專案使用下列定義：

```text
L = ||p₂ − p₁||                 兩端距離，mm
u = (p₂ − p₁) / L               從p₁指向p₂的單位方向
m = (p₁ + p₂) / 2               兩端中點，mm
Δt = t₂ − t₁                    時間差，ps
c = 0.299792458                  光速，mm/ps
r = m − (c × Δt / 2) × u        ROR中心估計，mm
```

若來源較靠近 p₂，t₂ 通常較早，Δt 為負，估計點便沿 u 朝 p₂ 移動。若來源較靠近 p₁，情況相反。

實際 CSV 依量測時間排列端點，所以通常 `t₂ ≥ t₁`。若為了教學把左端固定為 p₁，Δt 就可以正也可以負。只要端點與時間標號一起交換，估計座標應保持不變。

### 為什麼要除以二

令來源距離中點的帶符號位移為 `s`。兩個飛行距離分別是 `L/2+s` 與 `L/2−s`。相減後得到 `Δt = −2s/c`。因此 `s = −cΔt/2`。

這不是只用一個光子的 `距離 = 速度×時間`。兩個相反方向光子的路徑一增一減，所以有因子 2。

### 用一維例子檢查

左端位於 −400 mm，右端位於 +400 mm，來源位於 +30 mm。兩個路徑長度為 430 mm 與 370 mm。若左端標為 p₁，則 `Δt = (370−430)/c ≈ −200.138 ps`。代入公式後，位置回到 +30 mm。

下方互動圖固定左端與右端。拖動時間差，觀察位置方向。這只是公式教學，不是重新執行 Geant4 或新的實驗資料。

### 超出兩端線段時怎麼處理

程式檢查 `|cΔt| ≤ L`。不符合時，程式把 `physical_tof_valid` 設為 false。事件對仍保留在 CSV，但不放入預設體素影像。

程式不會把線段外的位置強行裁到端點。這可以保留錯誤配對或極端時間差的線索。線段內的估計也只代表符合幾何必要條件，並非完整物理驗證。
""",
        "pair_example",
        ["04_tof_geometry"],
    )

    add(
        "worked",
        "12｜拿一組實際 CSV 資料，逐步算出位置",
        f"""
## 12｜拿一組實際 CSV 資料，逐步算出位置

以下選取理想模型 CSV 中第一組標記為真配對的資料。它是單一計算範例，不用來代表整批誤差分布。表中的座標為顯示而四捨五入；原始 CSV 保留更多位數。

| 項目 | 第一端 | 第二端 |
|---|---|---|
| single ID | {int(row.single_id_1)} | {int(row.single_id_2)} |
| detector ID | {int(row.detector_id_1)} | {int(row.detector_id_2)} |
| timestamp，ps | {int(row.t1_ps)} | {int(row.t2_ps)} |
| energy，keV | {row.energy1_kev:.6f} | {row.energy2_kev:.6f} |
| 偵測位置，mm | {vector(p1)} | {vector(p2)} |

1. 計算時間差：`Δt = {int(row.t2_ps)} − {int(row.t1_ps)} = {int(row.dt_ps)} ps`。
2. 計算 LOR 長度：`L = {length:.6f} mm`。
3. 計算中點：`m = {vector(mid)} mm`。
4. 計算方向：`u = {vector(unit)}`。單位方向沒有長度單位。
5. 計算沿線位移：`−cΔt/2 = {row.tof_displacement_mm:.6f} mm`。
6. 將位移乘上方向，再加回中點，得到 `r = {vector(point)} mm`。

真正來源是 (20, −12, 12) mm。這個事件的三維位置誤差約為 **{np.linalg.norm(np.asarray(point) - np.array([20, -12, 12])):.6f} mm**。

即使這組 pair 的來源配對正確，時間抖動仍會讓估計位置偏離來源。配對是否正確，與每一個位置是否精準，是不同問題。

### 程式摘要

```python
vector = p2 - p1
length = norm(vector)
dt_ps = int(t2_ps) - int(t1_ps)
displacement_mm = -0.299792458 * dt_ps / 2
ror_mm = (p1 + p2) / 2 + displacement_mm * vector / length
```

這段是教學用摘要。正式函式另外檢查必要欄位、有限數值、零長度 LOR 與整數差值溢位。
""",
        "pair_example",
    )

    add(
        "image",
        "13｜從一個位置，到三維體素與投影圖",
        r"""
## 13｜從一個位置，到三維體素與投影圖

### Voxel 是三維格子

二維影像使用 pixel。三維影像使用 **voxel，體素**。本例將 x、y、z 各軸的 −100 到 +100 mm 分成 64 格。

每格邊長為 `200/64 = 3.125 mm`。總格數為 `64³ = 262,144`。一個有效 ROR 中心落入哪個格子，該格的計數就加 1。

### 本版累積的是中心點

一個 pair 在本版只增加一個位置的計數。程式沒有把該 pair 的完整高斯不確定區域攤開到多個格子。有限寬度 ROR kernel 是後續工作。

目前影像是事件計數分布。程式沒有完整的靈敏度、衰減、散射、隨機符合或正規化校正。計數不能直接解讀成 Bq/mL 或 SUV。

### 為什麼影像計數小於 pair 數

理想模型找到 7,262 組 pair。19 組的估計中心在線段外，因此不進入預設影像。其餘 7,243 組有效 pair 中，有 45 組位置落在三維立方體外。

所以，體素總計數為 `7262 − 19 − 45 = 7198`。這不是程式無聲遺失事件；排除數量已記錄在 metrics。

GATE 的 1,921 組 pair 都在線段內，也都位於本例的影像立方體內，因此 NPZ 的總計數為 1,921。

### 投影與切片有不同含義

XY 投影將不同 z 的位置或體素計數放到同一個 XY 平面。XZ 投影則沿 y 方向合併。切片只顯示某個 z 範圍或其中一層。

原先的 PNG 使用 80×80 的二維顯示格，顯示格邊長為 2.5 mm。NPZ 則保存 64³、邊長 3.125 mm 的三維體素。兩者的格數不同，不能逐格相減。

原先的二維直方圖只限制圖上的兩個軸；三維 NPZ 同時限制三個軸。不同範圍定義也可能使投影總數不同。本報告的圖注會說明使用原始位置還是已保存體素。

### 影像解析度尚未正式量測

體素大小是取樣設定，不等於系統解析度。若要報告影像解析度，應另設點源或假體，使用明確的重建與校正流程，再量測各軸 FWHM 等指標。
""",
        "summary",
        ["11_synthetic_ror", "12_gate_ror", "17_voxel_slices"],
    )

    add(
        "centroid",
        "14｜怎麼讀誤差：平均位置、單事件 RMSE 與 CTR",
        r"""
## 14｜怎麼讀誤差：平均位置、單事件 RMSE 與 CTR

### 平均位置偏差

先把所有選定 pair 的 XYZ 估計座標取平均，得到平均位置。再計算平均位置與已知光源之間的三維距離。

這個指標回答：「整批估計的中心偏離光源多少？」它不表示每個 pair 都在這個距離內。

### 單事件三維 RMSE

先計算每個 pair 的三維誤差平方，再取平均與平方根：

```text
RMSE = sqrt(mean((x−x₀)² + (y−y₀)² + (z−z₀)²))
```

它回答：「單次位置估計的誤差規模有多大？」RMSE 會受較大的誤差影響。報告另外保留中位數，幫助觀察典型誤差。

### 為什麼中心很準，單事件仍有明顯誤差

零均值的隨機誤差可以在平均時部分抵銷。許多位置分布在光源兩側，平均值仍可能靠近光源。固定的時鐘偏移則可能讓整批中心一起移動。

本次理想模型的平均位置偏差約 0.063 mm，單事件 RMSE 約 16.917 mm。這兩個數字並不矛盾。也不能將 0.063 mm 當成影像解析度。

### σ 與 FWHM

**σ** 是標準差，用來描述分布寬度。**FWHM** 是半高全寬，表示高斯曲線在一半峰值高度的寬度。對高斯分布，`FWHM ≈ 2.35482σ`。

**CTR** 是 Coincidence Timing Resolution。本例以兩端時間差誤差的 FWHM 表示 CTR。若每端誤差獨立、標準差相同，則時間差標準差是單端的 `sqrt(2)` 倍。

```text
σ(時間差) = sqrt(2) × σ(單端)
σ(沿LOR位置) = c × σ(單端) / sqrt(2)
沿LOR位置FWHM = c × CTR / 2
```

理想模型每端 σ=80 ps，所以位置誤差理論規模約為 16.959 mm。GATE 設 CTR=200 ps，所以沿 LOR 的時間定位 FWHM 約為 29.979 mm，對應高斯 σ 約為 12.731 mm。

這些值描述時間誤差造成的定位寬度。它們仍不是包含所有幾何、材料、重建與校正效應的臨床影像解析度。
""",
        "summary",
        ["13_error_distributions", "14_centroid_vs_spread", "18_tof_uncertainty"],
    )

    add(
        "results",
        "15｜兩組實驗的完整結果與可支持的結論",
        f"""
## 15｜兩組實驗的完整結果與可支持的結論

| 指標 | 理想幾何模型 | OpenGATE 物理模型 |
|---|---:|---:|
| 光源位置，mm | (20, −12, 12) | (30, −15, 10) |
| 主要幾何 | 半徑400mm，7×48個ID | 半徑200mm，96個BGO晶體 |
| 原始Singles | {syn["singles"]:,} | {gate["singles"]:,} |
| 能量篩選後Singles | 15,460 | 8,383 |
| 所有合格pairs | {syn["coincidence_pairs"]:,} | {gate["coincidence_pairs"]:,} |
| 真配對／同源pairs | 7,194真配對 | 1,921同源pairs |
| TOF線段內pairs | 7,243 | 1,921 |
| 三維體素總計數 | 7,198 | 1,921 |
| 平均位置，mm | {vector(syn["truth_valid_centroid_mm"])} | {vector(gate["same_event_valid_centroid_mm"])} |
| 平均位置偏差，mm | {syn["truth_centroid_error_mm"]:.6f} | {gate["same_event_centroid_error_mm"]:.6f} |
| 單事件三維RMSE，mm | {syn["truth_event_rmse_mm"]:.6f} | {gate["same_event_event_rmse_mm"]:.6f} |
| 單事件三維誤差中位數，mm | {syn["truth_event_median_error_mm"]:.6f} | {gate["same_event_event_median_error_mm"]:.6f} |

表中的理想模型位置誤差使用有效真配對。GATE 位置誤差使用有效同源配對。這兩個群體的真值定義不同，不能把兩欄當成完全等價的分類 benchmark。

### 結果支持什麼

第一，程式能從尚未配對的 Singles 完成完整流程。第二，OpenGATE 的 ROOT 能正確經由明確單位映射送入同一套 Python 演算法。第三，兩組位置分布的中心都靠近各自設定的偏心光源。

偏心點源有助於發現 TOF 正負號錯誤。若來源只在正中心，正負號錯誤可能較不明顯。

### 結果尚不能支持什麼

本次沒有臨床影像品質、絕對靈敏度、受測物內散射分類、硬體吞吐率或實測 White Rabbit 誤差。單一 seed 與少量固定設定，也不能代表所有情況都穩定。

GATE 的來源數、Hits 數、Singles 數與 pairs 數屬於不同資料層級。不要把 `1921/29935` 直接當成經完整定義的掃描器絕對靈敏度。
""",
        "summary",
    )

    add(
        "validation",
        "16｜我們如何驗證程式，而非只看圖像是否漂亮",
        r"""
## 16｜我們如何驗證程式，而非只看圖像是否漂亮

### 自動測試的範圍

2026-10-19 的 `reports/pytest.txt` 記錄 61 項測試通過。測試涵蓋模擬的可重現性、欄位驗證、時間與能量端點、全配對、多重事件、空資料、整數溢位、ROOT 映射、TOF 正負號與端點交換。

本次說明報告引用這份既有紀錄。2026-10-24 的整理工作主要重新核對檔案、程式雜湊、數量與圖表，沒有把舊測試紀錄改成今天的新測試結果。

### 獨立 oracle

Oracle 是已知答案或獨立參考。這裡另外寫一個逐對檢查的 O(N²) 版本。它不使用主要滑動視窗的排序與幾何判斷函式。

測試取 600 筆 Singles。兩個版本都得到相同的 218 組 pair ID。測試另外打亂輸入順序，結果仍相同。這比只比較 pair 總數更強，因為相同總數仍可能包含不同事件對。

### 零時間雜訊的解析檢查

程式產生 1,000 個完整雙端事件，移除時間及能量雜訊、背景與漏偵測。程式仍把 timestamp 四捨五入成整數 ps。

每端最多產生 0.5 ps 的量化差。兩端時間差最多因此改變 1 ps。沿 LOR 的位置誤差上限約為 `c/2 = 0.149896229 mm`。

實測最大誤差為 **0.144409 mm**，低於此上限。此檢查依賴理想連續幾何，不能轉成真實晶體的解析度保證。

### 雜訊理論值的檢查

另一組驗證使用 12,000 個事件、每端 σ=80 ps。測得位置 RMSE 為 **16.957194 mm**。理論值為 **16.958822 mm**。相對差約 **0.0096%**。

這表示此簡化條件下的時間誤差傳播符合預期。它不代表所有物理與校正模型都已正確。

### 檔案與版本檢查

本次盤點重新比對兩組執行紀錄中各 11 個 Python 模組的 SHA-256、各 6 個輸出檔雜湊、正式 ROOT、生成腳本與匯入 CSV。它們都與保存的紀錄一致。

Synthetic manifest 指向 `c5d3298`，當時工作目錄乾淨。GATE manifest 指向 `c9caa55`，並保存 `git_dirty=true`。工作目錄有變更時，不能只用 commit 推定全部內容；應同時檢查保存的原始碼雜湊及生成器雜湊。

SHA-256 或 MD5 可以檢查檔案是否與指定內容相同。它們不能證明物理模型或科學結論正確。NDL 的 MD5 是用來核對官方下載 archive。
""",
        "validation",
    )

    add(
        "sync",
        "17｜時間同步實驗：為什麼找到 pair 仍可能重建錯位置",
        r"""
## 17｜時間同步實驗：為什麼找到 pair 仍可能重建錯位置

### 隨機抖動與固定偏移不同

時間抖動是每筆資料不同的隨機誤差。固定偏移是某一群偵測器共同偏早或偏晚。前者主要擴大位置分布，後者可能讓整批分布中心移動。

掃描實驗使用 4,000 個幾何接受事件、100% 偵測效率、無背景及每秒 10,000 個條件接受事件。這些設定用來減少其他干擾。

程式測試單端 σ 為 0、40、80、160 ps。程式另對 x≥0 半環加入 0、100、300 ps 固定偏移。總共有 12 組設定。這個半環分組是教學模型，不是已接線的兩張 FPGA 板。

### 觀察到的結果

在 σ=80 ps 時，沒有固定偏移的中心誤差約為 0.124 mm。加入 100 ps 半環偏移後，中心誤差約為 9.525 mm。加入 300 ps 後，中心誤差約為 28.395 mm。

這三組都找回 4,000 個真配對。因此，配對數沒有下降，不代表重建位置沒有受損。

沿單一 LOR 而言，100 ps 的時間差偏移對應約 `c×100/2 = 14.990 mm` 的位置變動。整批中心偏差還取決於各 LOR 方向與哪些端點被偏移，所以不必等於 14.990 mm。

### 與 White Rabbit 的關係

White Rabbit 是高精度時間與頻率同步技術。未來若事件來源跨多張板，兩端時間戳必須使用一致的時間基準。資料抵達後排序，只能處理順序；排序無法消除 timestamp 本身的固定偏移。

本次沒有接上 White Rabbit、QSFP 或 FPGA。這份結果只是用軟體注入已知偏移，量化其影響。它可以協助建立同步誤差預算，尚不能作為任何硬體同步精度的實測宣稱。
""",
        "sweep",
        ["15_timing_rmse", "16_timing_bias"],
    )

    add(
        "modules",
        "18｜程式模組與輸出檔案，逐一說明",
        r"""
## 18｜程式模組與輸出檔案，逐一說明

專案根目錄是 `C:\Users\zenbook\我的雲端硬碟\碩士班研究資料\06_PET`。以下路徑都相對於此目錄。

| 模組／腳本 | 主要函式或入口 | 輸入與工作 | 主要輸出 |
|---|---|---|---|
| `src/pet_sim/config.py` | `SimulationConfig`、`CoincidenceConfig` | 集中管理參數與光速，檢查值域。 | 參數物件。 |
| `simulation.py` | `simulate_singles` | 理想幾何、亂數、效率、背景與抵達延遲。 | Singles DataFrame。 |
| `coincidence.py` | `validate_singles`、`find_coincidences` | 驗證資料並搜尋全配對。 | 事件對表格。 |
| `coincidence.py` | `brute_force_pair_ids` | 獨立逐對檢查。 | 參考 pair ID 集合。 |
| `reconstruction.py` | `reconstruct_ror` | 使用兩端位置與時間差。 | ROR中心、LOR長度、位移及有效標記。 |
| `reconstruction.py` | `histogram_ror` | 將所選位置放入三維格子。 | 體素陣列與邊界。 |
| `root_io.py` | `inspect_root`、`load_gate_singles` | 檢查結構、映射欄位、換算單位、編碼ID。 | 統一Singles與來源資訊。 |
| `metrics.py` | `summarize` | 讀取已完成配對及座標。 | 計數、同源關係、中心偏差與RMSE。 |
| `plotting.py` | `save_ror_plot` | 讀取有效位置。 | 原始XY/XZ與誤差PNG。 |
| `pipeline.py` | `run_pipeline` | 串接模組並保存紀錄。 | CSV、NPZ、PNG、JSON。 |
| `validation.py` | `validate_software`、`run_sweep` | 解析驗證及12組時間參數掃描。 | 驗證JSON與掃描CSV。 |
| `cli.py` | `main` | 解析使用者命令列參數。 | 呼叫以上功能。 |
| `scripts/generate_gate_singles.py` | `main` | 建立及執行真正OpenGATE模型。 | ROOT、mapping與metadata。 |
| `scripts/activate.ps1` | PowerShell腳本 | 載入Conda hook並啟用環境。 | 目前終端機的啟用環境。 |
| `scripts/reproduce.ps1` | PowerShell腳本 | 依序執行測試、解析驗證、demo、sweep與Markdown報告。 | 一組可重現成果。 |
| `scripts/build_report.py` | `main` | 彙整既有輸出。 | 簡明Markdown驗證報告。 |

### 每次完整流程保存的檔案

| 檔案 | 你可以看到什麼 |
|---|---|
| `singles_arrival_order.csv` | 原始單事件欄位；模擬資料依抵達順序排列，匯入資料保留原輸入順序。 |
| `coincidences_ror.csv` | 每個pair的兩端ID、時間、能量、座標、ROR結果、線段有效性與可用truth標籤。 |
| `ror_volume.npz` | `counts[x,y,z]` 與三個軸的mm邊界。NPZ是壓縮的NumPy陣列容器。 |
| `ror_projections.png` | 原始簡明投影圖與分布圖。本HTML另外重繪淺色說明圖。 |
| `metrics.json` | 本次統計值。JSON是有欄位名稱的文字資料格式。 |
| `config.json` | 本次使用的模擬、篩選與匯入設定。 |
| `manifest.json` | Python與套件版本、Git狀態、程式及輸出雜湊。 |
| `gate_singles.provenance.json` | CSV匯入的ROOT來源、分支、單位、時間原點及ID編碼表。 |

### 本機與 GitHub 各保存什麼

完整生成資料在 `data/` 與 `outputs/`。精簡結果在 `reports/`。Git 的 `.gitignore` 排除原始 ROOT、完整輸出、環境與快取。

因此，GitHub 上的程式與精簡成果可以取得。你仍應保留本機原始 ROOT；不要以為推送 Git 就已備份所有原始資料。
""",
        "parameters",
    )

    add(
        "reproduce",
        "19｜你可以直接照做的操作步驟",
        r"""
## 19｜你可以直接照做的操作步驟

### 路線 A：只閱讀現有成果

1. 使用瀏覽器開啟本 HTML。
2. 先讀結果與圖注。
3. 若需要原始表格，查看專案的 `outputs/synthetic/` 與 `outputs/gate/`。

這條路線不需要啟動 Python。把本 HTML 複製到其他電腦後，主要文字、圖片與互動公式仍可離線閱讀。外部參考網址需要網路。原始資料檔並沒有全部放進 HTML。

### 路線 B：重跑簡化模型

先開啟 PowerShell，再依序執行：

```powershell
cd 'C:\Users\zenbook\我的雲端硬碟\碩士班研究資料\06_PET'
. .\scripts\activate.ps1
python -c "import sys; print(sys.executable)"
python -m pet_sim.cli demo --out outputs/my_first_run
```

Python 路徑應指向 `anaconda3\envs\pet-simulation\python.exe`。`activate.ps1` 只啟用目前的 PowerShell，不修改全域設定。新開終端機後，請再次啟用。

確認 `outputs/my_first_run/metrics.json` 及 `ror_projections.png` 已產生。若程式、套件與預設參數不變，固定seed應重現本報告的事件統計。圖檔雜湊也可能受顯示工具版本影響，所以同時比較設定與數值。

### 路線 C：重用已存在的 GATE ROOT

本機已保存正式 ROOT。你可以先重跑匯入與重建，不必重做粒子模擬。

```powershell
python -m pet_sim.cli inspect-root data/raw/gate_demo/singles.root
python -m pet_sim.cli import-root data/raw/gate_demo/singles.root --tree Singles --mapping data/raw/gate_demo/mapping.json --out data/processed/my_gate_singles.csv
python -m pet_sim.cli run data/processed/my_gate_singles.csv --source-mm 30 -15 10 --out outputs/my_gate_run
```

`--source-mm` 只提供誤差評估參考，不參與配對與 ROR 公式。請確認它與你的光源設定一致。

### 路線 D：重新產生 GATE 事件

```powershell
python scripts/generate_gate_singles.py --dry-run
python scripts/generate_gate_singles.py --output data/raw/gate_new_run --expected-events 30000 --activity-bq 200000 --source-mm 30 -15 10 --ctr-ps 200 --seed 20261019
```

`--dry-run` 只列出設定，不執行粒子模擬。正式命令使用新的輸出資料夾，避免與既有 ROOT 混淆。若 `singles.root` 已存在，生成器會停止並保留原檔。

重新生成後，請將路線 C 的 ROOT 與 mapping 路徑改成 `gate_new_run`。第一次安裝與資料下載可能花較長時間。已下載的物理資料可重用。

### 路線 E：驗證與同步誤差掃描

```powershell
python -m pytest -q
python -m pet_sim.cli validate --out outputs/my_validation.json
python -m pet_sim.cli sweep --out outputs/my_timing_sweep.csv
```

這些命令會真的執行程式。請把新結果與原始紀錄分開保存。如果你只是閱讀本報告，不需要再次執行。

### 在另一台電腦建立環境

```powershell
git clone https://github.com/t5512355123/PET_simulation.git
cd PET_simulation
conda env create -f environment.yml
conda activate pet-simulation
python -m pip install -e '.[dev]'
python -m pet_sim.cli demo --out outputs/first_demo
```

`environment.yml` 也包含 OpenGATE 安裝需求。鎖定版本清單記錄的是本次 Windows 環境，不應假設所有作業系統都能原樣使用。若只做簡化模型，獨立Python環境加上 `pip install -e '.[dev]'` 就能安裝核心依賴。

### 常見問題

| 現象 | 先檢查什麼 |
|---|---|
| 找不到conda或Python指到錯誤位置 | 回到專案目錄，載入activate.ps1，再印出sys.executable。 |
| 找不到pet_sim | 確認位於正確環境，並執行 `python -m pip install -e '.[dev]'`。 |
| ROOT缺少必要欄位 | 先inspect，再改mapping；不要猜它一定是Singles。 |
| pair數為零或極多 | 檢查時間／能量單位、生成時間、篩選值與幾何條件。 |
| 重建往反方向偏 | 檢查端點標號、Δt定義、位置與時間是否一起交換。 |
| 同seed結果不同 | 比較程式雜湊、完整參數與套件版本，不只比較seed。 |
| GATE拒絕覆寫 | 換新 --output，或直接重用現有ROOT做匯入。 |
""",
        "parameters",
    )

    add(
        "limitations",
        "20｜目前限制：哪些事情還沒有證據",
        r"""
## 20｜目前限制：哪些事情還沒有證據

### 演算法邊界

本版使用整份資料離線排序。沒有有限記憶體的線上保證，也沒有 late-event 處理、watermark、封包遺失或時鐘漂移模型。合格pair可以重複使用同一個Single；此政策不是所有掃描器的預設政策。

### 物理與影像邊界

理想模型沒有材料物理。GATE 有電磁傳輸，但只有簡化空氣世界與 BGO 晶體環。兩個模型都直接產生背對背光子，沒有完整核種衰變與正子傳輸。

目前位置讀出沒有模擬真實晶體中心量化與完整 DOI 誤差。影像沒有完整校正，也沒有有限寬度 ROR 核。沒有量測經校正影像的解析度、對比或定量準確度。

### 統計邊界

本次主要使用固定seed、固定點源及固定幾何。沒有大量獨立重複實驗、不同seed的信賴區間、動態移動源或大型假體比較。

同源事件標籤不足以完整分類散射。線段內標記不足以證明配對正確。平均位置偏差不足以代表單事件誤差或影像解析度。

### 硬體邊界

本次沒有使用 DE5a、DE10 Pro、QSFP、TDC 或 White Rabbit 實測。沒有 FPGA 資源表、時脈收斂、端到端延遲、最大吞吐量或 buffer 溢位結果。

本例 14 lane 是軟體事件標籤。它沒有包含實際 QSFP 封包格式或接收器。後續硬體研究需要另外實作這些介面。
""",
        "parameters",
    )

    add(
        "next",
        "21｜下一步：依序把軟體基準變成可比較的研究",
        r"""
## 21｜下一步：依序把軟體基準變成可比較的研究

### 第一步：你先親自追蹤一個事件對

已知：一個pair能由兩筆Singles與TOF公式得到座標。待完成：你能在CSV中找回相同兩筆資料，並手算方向及位移。

產物：一頁筆記，記錄single ID、時間差、兩端位置、計算座標及誤差。驗收：你的結果與CSV只差顯示四捨五入，不使用truth幫忙配對。

### 第二步：與 GATE sorter 使用相同政策比較

已知：Python滑動視窗通過獨立暴力oracle。待確認：在同一批ROOT Singles、同一單位與同一多重事件政策下，GATE sorter與本專案是否得到相同pair集合。

先明訂時間窗、all-pairs或multiples政策及幾何條件。若兩者原生幾何篩選不同，先匯出候選pairs，再套用共同的後處理條件。不要直接比較兩個預設pair數。

產物：差異pairs CSV，包含只在A出現、只在B出現與原因分類。驗收：同政策可比較的pair ID集合一致，或每個差異都有可重現解釋。

### 第三步：建立分離時鐘的時間誤差模型

已知：100ps固定半環偏移會移動重建中心。待完成：區分真實偵測時間、各板本地timestamp、網路傳輸與主板接收時間。

模型可逐步加入固定偏移、頻率誤差、隨機抖動與時間校正。先使用已知注入值，再測校正前後的中心偏差、RMSE與pair遺失。這些是提議的軟體實驗，尚未完成。

產物：校正參數、誤差掃描圖與可重現設定。驗收：在明訂範圍內，校正結果符合事先寫下的誤差預算；預算應由研究需求決定。

### 第四步：實作14路串流reorder buffer與watermark

已知：完整離線排序可當參考。待完成：資料陸續抵達時，在有限buffer中處理亂序。

**Reorder buffer** 暫存尚未確定順序的事件。**Watermark** 表示系統可安全處理到哪個時間之前。Watermark需要明確的延遲上界、通道進度或heartbeat；不能只因為目前沒收到較早資料，就假設它永遠不會來。

先測：通道延遲不同、某通道暫停、burst、跨區塊時間窗、相同timestamp、結尾flush、過晚資料、封包遺失及buffer滿。對每組輸入，與離線基準逐一比較pair ID，並檢查是否重複輸出。

平均佔用可先用 `事件率×等待時間` 估計。但這不是buffer大小的保證。Burst與最壞延遲仍需要單獨測試。

產物：串流模組、事件trace、buffer最大佔用與漏配對紀錄。驗收：在已宣告的輸入與延遲條件內，pair集合與離線基準一致。

### 第五步：做固定點與 FPGA golden vectors

已知：Python使用整數ps與浮點位置。待完成：定義硬體字寬、固定點格式、縮放係數、捨入及溢位規則。

先輸出測試向量：原始事件、配對ID、Δt、兩端位置、預期座標及容許誤差。再讓硬體測試平台讀入相同向量。不要把演算法誤差、固定點誤差與時鐘誤差混成一個無法追蹤的數字。

產物：固定點Python模型、CSV或binary向量、硬體testbench。驗收：配對一致，座標誤差位於明確容許值內。吞吐率、延遲、DSP/BRAM與時脈結果另行量測。

### 第六步：擴充 ROR 與影像品質比較

已知：目前只累積ROR中心。待完成：依CTR建立沿LOR的有限寬度kernel，並用多點源或假體比較中心點累積與kernel累積。

之後才評估MLEM/OSEM。MLEM以整批量測反覆更新影像。OSEM把資料分成子集合，依序做近似更新。它們需要一致的幾何、量測模型與校正，不能只拿一張好看的圖比較。

產物：相同資料條件下的影像、每軸FWHM、對比、雜訊與運算成本。驗收：比較條件、指標與實驗重複方式事先明確定義。

### 與你原先三板構想的對應

未來可以讓兩張來源板模擬事件並加上時間戳，再經QSFP送到主板。White Rabbit提供共同時間基準。主板處理reorder、coincidence與ROR。這是概念分工，還沒有實際部署。

目前最建議先完成第二步與第四步。它們能先回答配對語意與串流正確性，再讓FPGA工作有穩定、可量測的比較基準。
""",
        "validation",
    )

    add("glossary", "附錄 A｜名詞速查表", glossary(), "parameters")
    add("references", "附錄 B｜來源、版本與查核方式", references(), "validation")
    return sections


def glossary():
    rows = [
        ("PET", "正子斷層造影。利用湮滅光子對估計來源分布。"),
        ("Annihilation／湮滅", "正子與電子轉換成光子的物理過程。本例直接產生光子對。"),
        ("Gamma photon／伽瑪光子", "高能電磁輻射的一個量子。模型中每個來源對含兩個511keV光子。"),
        ("BGO", "Bi₄Ge₃O₁₂閃爍晶體。本例使用的偵測材料。"),
        ("Detector／Crystal", "偵測器／晶體。負責接收光子；detector ID是其識別資訊。"),
        ("Geometry／幾何", "偵測器尺寸、位置、排列與來源位置的定義。"),
        ("FOV", "Field of View，視野。模型接受或影像顯示的空間範圍，兩者需分別定義。"),
        ("Raw list-mode", "逐事件列表。本專案特指未配對Singles，不是原始波形。"),
        ("Hit", "一次能量沉積或相關Geant4步進紀錄；一個光子可產生多筆。"),
        ("Single", "經digitizer整理的一次偵測事件，尚未與另一端配對。"),
        ("Digitizer", "將物理互動紀錄轉成偵測資料的處理鏈。本例不是完整電子學。"),
        ("Actor", "OpenGATE中的記錄或處理元件，例如Hits、Adder與Blurring。"),
        ("Adder", "把同一事件及晶體內的能量沉積彙整成Single的元件。"),
        ("Energy-weighted centroid", "以各次沉積能量為權重計算平均互動位置。"),
        ("Blurring", "依指定分布加入量測誤差。本例對時間加入高斯誤差。"),
        ("Coincidence", "符合選取規則的兩筆Singles組合；不保證真的是同一次湮滅。"),
        ("Coincidence window", "允許的時間差範圍。本例使用最大絕對差4000ps。"),
        ("All-pairs", "列出每個合格無序pair；同一Single可以出現在多個pair。"),
        ("Multiples", "同一窗內有多筆事件，可能形成多個pairs的情況。"),
        ("Greedy matching", "依某種順序先挑一組，再限制重用的配對方法；本版未採用。"),
        ("True pair", "在理想模型中，兩端來自同一個非背景來源事件的pair。"),
        ("Random coincidence", "不同來源或背景事件偶然通過時間與幾何條件。"),
        ("Scatter", "光子方向或能量因交互作用改變；需更多truth才能完整分類。"),
        (
            "Prompt／Delayed",
            "常見PET符合分類或隨機估計相關資料。原則與政策依系統定義，本版未實作延遲窗估計。",
        ),
        ("Ground truth", "模擬已知的來源ID與位置，僅作結果評估。"),
        ("EventID／RunID", "來源事件與執行批次識別碼；識別範圍不能任意跨檔案假設唯一。"),
        ("Single ID", "本次載入中追蹤一筆Single的唯一列編號。"),
        ("LOR", "Line of Response，兩個偵測位置連成的線。"),
        ("TOF", "Time of Flight；本例使用兩端到達時間差來定位。"),
        ("ROR", "Region of Response，TOF限制的LOR區域。本版只計算區域中心。"),
        ("Kernel", "把一個事件的影響分配到一段或一區位置的權重函數；本版尚未累積有限核。"),
        ("CTR", "兩端時間差誤差的時間解析度；本例以FWHM表示。"),
        ("σ／Standard deviation", "標準差。描述隨機分布的寬度。"),
        ("FWHM", "半高全寬。對高斯分布約為2.35482σ。"),
        ("Gaussian／高斯", "常態分布。本例用於時間及部分能量誤差。"),
        ("Poisson process", "以隨機等待時間形成事件流的模型；一定時長內事件數會波動。"),
        ("Exponential distribution", "指數分布。本例用來取樣相鄰來源事件的等待時間。"),
        ("Monte Carlo", "使用亂數取樣估計或模擬系統的方式；Geant4粒子傳輸屬此類。"),
        ("Seed／RNG", "亂數種子／亂數產生器。種子控制可重現的取樣序列。"),
        ("Efficiency", "偵測效率。理想模型對每個光子使用95%保留機率。"),
        (
            "Activity／Bq",
            "活度／每秒一次衰變的單位。本例直接光子源使用事件生成率；理想模型另有幾何接受條件。",
        ),
        ("ps／ns／s", "皮秒／奈秒／秒。1ns=1000ps；1s=10¹²ps。"),
        ("eV／keV／MeV", "能量單位。1MeV=1000keV；1keV=1000eV。"),
        ("mm／g·cm⁻³", "毫米／每立方公分克數。分別表示長度與材料密度。"),
        ("Timestamp", "事件量測時間戳。與資料抵達時間分開。"),
        ("Arrival time", "接收端抵達時間或模型中的抵達排序時間。"),
        (
            "Jitter／Offset／Drift",
            "每筆隨機抖動／固定偏移／隨時間累積的時鐘變化。本次只做前兩者的簡化模型。",
        ),
        ("Int64／Float64", "64位元整數／雙精度浮點數。兩者的範圍與精度規則不同。"),
        ("Overflow／Quantization", "溢位／量化。分別是超出可表示範圍，以及轉為離散刻度的誤差。"),
        ("Time origin", "共同時間原點。明確減去原點可降低大絕對時間的表示問題。"),
        ("Voxel／Pixel", "三維體素／二維像素。是取樣格子，不等於物理解析度。"),
        ("Histogram／Bin", "直方圖／統計格。累積各區間或空間格內的事件數。"),
        ("Projection／Slice", "投影／切片。分別合併一個方向，或只顯示一層。"),
        ("Centroid error", "先平均位置，再與已知光源計算距離的中心偏差。"),
        ("RMSE／Median", "均方根誤差／中位數。分別表達平方誤差規模與排序後的中央值。"),
        ("Precision／Recall", "配對精確率／找回率。使用前必須先說清楚正確標籤與分母。"),
        ("Physical TOF valid", "估計中心位於兩偵測端點之間的標記，不是正確配對證明。"),
        (
            "Attenuation／Normalization",
            "衰減校正補償光子在物體內被吸收或移出有效路徑的損失。正規化校正補償偵測效率或通道響應差異，並非把影像縮放至0–1。本版未完成。",
        ),
        ("DOI／Dead time", "互動深度／死時間。實機位置讀出與無法接收新事件的時間相關效應。"),
        ("SUV", "Standardized Uptake Value，標準化攝取值。需要定量影像與額外資料，本版未計算。"),
        ("MLEM", "Maximum-Likelihood Expectation-Maximization，以量測模型反覆更新影像的方法。"),
        ("OSEM", "Ordered-Subsets EM，將資料分為子集合並依序更新的迭代重建方法。"),
        ("Phantom", "假體。用已知幾何或活性分布測試影像系統。"),
        ("ROOT／TTree／Branch／RNTuple", "科學檔案格式，以及其中的資料表與欄位容器。"),
        ("CSV／JSON／NPZ／PNG／SVG", "表格文字／結構化文字／壓縮陣列／點陣圖片／向量圖片格式。"),
        ("DataFrame／Array", "具欄位的表格物件／數值陣列。"),
        ("Mapping／Provenance", "欄位及單位映射／來源與處理紀錄。"),
        ("CLI／API", "命令列介面／程式呼叫介面。"),
        ("Conda／pip", "環境管理工具／Python套件安裝工具。"),
        ("Python／NumPy／pandas", "程式語言／數值陣列套件／表格處理套件。"),
        ("Matplotlib／uproot", "繪圖套件／Python ROOT讀取套件。"),
        ("OpenGATE／Geant4", "模擬配置與digitizer工具／粒子交互作用引擎。"),
        ("pytest／Ruff", "執行自動測試／靜態檢查Python程式。"),
        ("Git／Commit／GitHub", "本機版本控制／一次版本提交／遠端儲存與協作平台。"),
        ("CI／GitHub Actions", "持續整合／在遠端自動執行檢查的工作流程。"),
        ("Manifest／SHA-256／MD5", "執行清單／檔案內容指紋算法。雜湊相符不等於科學模型正確。"),
        ("Unit test／Oracle", "針對特定行為的自動測試／用來比對的獨立參考答案。"),
        ("Golden model／Golden vectors", "可比較的參考程式／明確輸入與預期輸出的測試資料。"),
        ("O(N log N)／O(N²)", "輸入變大時運算量如何成長的記號；不是已量測的執行秒數。"),
        ("Lane／OOO", "輸入資料通道群／資料抵達順序與事件時間順序不同。"),
        ("FIFO／Reorder buffer", "先進先出佇列／等待並重排事件的暫存區。"),
        (
            "Watermark／Heartbeat／Flush",
            "可安全處理的時間界線／通道仍在運作的進度訊息／結尾排空暫存事件。",
        ),
        (
            "Burst／Backpressure／Late event",
            "短時間大量資料／要求上游減慢傳送／超過已宣告時間界線才抵達的事件。",
        ),
        ("FPGA／DE5a／DE10 Pro", "可重新配置的硬體邏輯裝置／原先研究構想中的兩種開發板。"),
        ("White Rabbit／QSFP", "高精度時間頻率同步技術／高速光電介面模組形式。本次沒有實測。"),
        ("TDC／ADC", "時間數位轉換器／類比數位轉換器。本專案尚未處理其原始碼。"),
        ("Throughput／Latency", "每秒處理資料量／單筆資料到結果的延遲。兩者應分開量測。"),
        ("Fixed point／DSP／BRAM", "固定點數值表示／硬體數值運算資源／晶片內區塊記憶體。"),
        ("HTML／CSS／JavaScript／React", "網頁結構／外觀／互動語言／本報告共享顯示元件的技術。"),
        ("Node.js／Offline", "報告打包所用的JavaScript執行環境／不連網也能閱讀已封裝內容。"),
    ]
    return (
        "## 附錄 A｜名詞速查表\n\n這份表提供回查用的簡短定義。主要章節已逐步解釋重要名詞。你也可以用瀏覽器 Ctrl+F 搜尋中英文名稱。\n\n| 名詞 | 簡單說明 |\n|---|---|\n"
        + "\n".join(f"| {a} | {b} |" for a, b in rows)
    )


def references():
    return r"""
## 附錄 B｜來源、版本與查核方式

### 本專案的第一手證據

本次數值來自既有 `reports/synthetic_metrics.json`、`reports/gate_metrics.json`、`reports/timing_sweep.csv`、兩組原始 CSV 與 NPZ。模型設定來自 `config.py`、`simulation.py`、`generate_gate_singles.py` 與保存的 config／metadata。

測試證據是 `reports/pytest.txt` 與 `reports/software_validation.json`。來源及生成檔的查核使用兩組 manifest、正式 ROOT SHA-256、生成腳本 SHA-256 與 CSV provenance。

本報告新增 `docs/html_report_evidence.json`，保存盤點結果與來源路徑。圖表 manifest 記錄每張圖使用的來源及圖注。所有教學示意與公式互動都標成示意，沒有混入實測統計。

### 主要外部參考

| 來源 | 本報告參考用途 |
|---|---|
| [ASD-STE100 官方FAQ](https://www.asd-ste100.org/STE_faq.html) | 清楚技術文字與適用範圍。 |
| [ASD-STE100 Issue9 官方下載頁](https://www.asd-ste100.org/STE_downloads.html) | 官方名稱及版本。 |
| [ASD-STE100 Issue9 原文](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf) | 短句、逐步說明、一段一主題與操作句原則。英文word限制沒有直接換成中文字數。 |
| [Korcyl等人的J-PET FPGA論文](https://arxiv.org/pdf/1807.10754) | LOR、TOF定位、ROR及事件位置累積概念。未重製其完整TDC或FPGA系統。 |
| [OpenGATE官方安裝文件](https://opengate-python.readthedocs.io/en/master/user_guide/user_guide_installation.html) | Python環境與物理資料安裝。 |
| [OpenGATE官方Hits／Singles範例](https://github.com/OpenGATE/opengate/blob/master/opengate/tests/src/actors/test037_pet_hits_singles_helpers.py) | Hits到Singles、欄位與GATE10時間單位。 |
| [OpenGATE官方PET coincidence範例](https://github.com/OpenGATE/opengate/blob/master/opengate/tests/src/actors/test072_coinc_sorter_step1.py) | 光源、晶體與digitizer API。 |
| [OpenGATE Coincidence Sorter文件](https://opengate-python.readthedocs.io/en/master/user_guide/user_guide_reference_actors.html#coincidence-sorter) | 時間窗與多重事件政策。 |
| [Geant4單位系統](https://geant4.web.cern.ch/documentation/pipelines/master/bfad_html/ForApplicationDevelopers/Fundamentals/unitSystem.html) | mm、ns、MeV的基礎單位。 |
| [Geant4資料集定義參照](https://github.com/Geant4/geant4/blob/v11.4.0/cmake/Modules/G4DatasetDefinitions.cmake) | NDL4.7.1官方MD5校驗碼。此連結不單獨證明本機引擎版本。 |
| [TOF PET影像資訊量研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC2828326/) | 高斯TOF不確定寬度與c×CTR/2關係。 |

外部網址用來補充來源。理解本報告的主要流程與結果，不需要先讀這些外部頁面。GitHub的master文件可能隨時間更新；本次實際套件版本與生成器雜湊另有保存。

### 報告中的資料分類

「理想模型實驗」指本機數學模擬。「OpenGATE實驗」指本機執行的粒子物理模擬。「示意圖」用來說明概念。「下一步」是尚未完成的提議。這四類不能互換。

### 你讀完後應能回答的八個問題

1. 本專案的raw list-mode為何是Singles，而不是TDC碼？
2. 一個光子為何可能產生多個Hits？
3. Timestamp和arrival time有何不同？
4. 為什麼4000ps門檻、200ps CTR與1ps儲存單位不是同一件事？
5. 為什麼同EventID不等於無散射？
6. 為什麼TOF公式有負號與除以二？
7. 為什麼0.063mm平均位置偏差不代表每個事件或影像解析度？
8. 你要如何用離線pair ID集合驗證新的串流或FPGA版本？

若你能用自己的話回答這些問題，你已掌握本次工作的範圍，也知道下一步研究要檢查什麼。
"""
