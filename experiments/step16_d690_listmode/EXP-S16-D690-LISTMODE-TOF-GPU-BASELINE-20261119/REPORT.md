# EXP-S16-D690-LISTMODE-TOF-GPU-BASELINE-20261119 — PETRIC2 GE D690 NEMA IQ：TOF sinogram 轉 list-mode、模型驗證、GPU 基準、硬體架構模型

## Verdict

`PASS`（資料與基準）：
- GE_D690_NEMA_IQ2 的 TOF sinogram 已轉成 list-mode：3,070,938 個事件，重新直方圖化和 prompts 完全相同。
- 模型和 PETRIC 一致：在參考影像上的 KKT 殘差 4.8×10⁻⁵（OSEM 0.10）。
- GPU 的 TOF list-mode psv 到 PETRIC 門檻：**2.39 s**（RTX 3070 Ti Laptop，81 W），第 40 次更新，7.6 個投影 epoch。
- 目標「快 5 倍」= FPGA ≤ 0.478 s。架構模型顯示需要「兩個主軸副本常駐片上 + 每條 lane 4 條步進 pipeline + 200 MHz」（R2）。

## 1. list-mode 資料怎麼做（參考 Zenodo 8404015）

Zenodo 8404015（G. Schramm，GE Discovery MI NEMA IQ）是**實機**的 list-mode：每個事件有晶體對、TOF bin，
以及每個事件的校正值（sens、atten、contam = randoms + scatter），檔案 `LIST0000.BLF` + `corrections.h5`。
PETRIC2 只給 sinogram，所以照同樣的「每事件：LOR + TOF bin + 乘法 / 加法校正」格式產生事件（`source/sino2lm_tof.py`）：

- 每個 sinogram bin 有 y 個 count 就產生 y 個事件（re-histogram 必須完全等於 prompts）。
- 時間戳：在 frame 內均勻亂數再排序（sinogram 沒有時間資訊；靜態掃描下就是 homogeneous Poisson process）。
- 每個事件存：`t`、`lor`（LOR 編號 → `lors_all.npy` 的端點，由 STIR `get_LOR` 算出）、`tof`（STIR TOF 位置）、
  `m`（乘法因子，和 TOF bin 無關，已檢查）、`a`（該 TOF bin 的加法項）。
- D690：11 個 TOF bin（mashing 5 × 89 ps = 66.7 mm）、550 ps FWHM（σ 35.0 mm）、23 segment、288 view、381 tangential、
  60,679,584 條 LOR；影像 201×201×47，voxel 2.13×2.13×3.27 mm。
- 輸出在 `D:\PET_DATA\listmode\GE_D690_NEMA_IQ2`（資料太大不進 repo；`raw/meta_d690.json` 有來源 SHA-256）。

## 2. 模型驗證（`source/tofcore.py`、`tof_sign.py`、`kkt_tof.py`）

- 投影器：parallelproj TOF Joseph（list-mode）；模型 ŷ = m (c A_tof x + a)，c = 1/橫向 voxel 大小；RDP 同 EXP-S9。
- TOF 方向：STIR 位置 k → parallelproj bin 5 − k（log-likelihood 在 OSEM 和參考影像上都比 5 + k 大）。
- TOF 核截斷：3σ 時 KKT 殘差 2.5×10⁻³；**5σ 時 4.8×10⁻⁵**（和 Esser2 的 3.6×10⁻⁵ 同級）→ 用 5σ。
- sensitivity：m 和 TOF 無關，TOF 核在各 bin 加總為 1 → 非 TOF 反投影 m（6,068 萬條 LOR）。

## 3. GPU 基準（`source/run_tof.py`，M = 8，時間子集，同 EXP-S9 的 list-mode psv）

| 項目 | 結果 |
|---|---|
| 到門檻 | 第 40 次更新、epoch 5.0、投影 7.625 epoch |
| 演算法時間（4 次） | 2.403、2.404、2.375、2.387 s → **2.39 s** |
| GPU 功率 | 81 W（nvidia-smi，GPU 使用率 ≥ 50% 的平均）→ 約 195 J |
| 每子集（383,867 事件）| 前投影 9.8 ms、反投影 35.1 ms（atomic）、RDP 0.6 ms、更新 0.4 ms、預條件 1.5 ms |

GPU 的時間幾乎都在 TOF 反投影；投影 = 1.07 億樣本 / 44.9 ms = 2.4 G 樣本/s。

## 4. 硬體需要什麼才能快 5 倍（`source/*_model.py`，用 D690 的真實事件）

每個事件 5σ TOF 窗口內 139 步（整條 LOR 175 步）；每子集 5,347 萬步（前投影）。5 倍預算 478 ms；61 次子集投影 + 40 次 voxel 更新。

| 架構（32 lanes） | 每子集前+反投影 | 對 GPU |
|---|---|---|
| EXP-S13/S15 的做法（每軸分兩半、連續 slab），150 MHz | 36.0 ms（效率 0.62，中央 lane 太忙） | 1.25× |
| 平面交錯分配（plane p → lane p mod 32），150 MHz | 28.1 ms（效率 0.79） | 1.6× |
| 交錯 + 每 lane W = 4 條 pipeline（bank 依本地平面 mod 4 分組），200 MHz | 7.0 ms | 6.4× |
| 常駐單一 x 排列（y 主軸射線集中在少數 lane） | 9.5 ms | 4.7× |
| **R2：兩個主軸副本常駐（IMG fp16、ACC fp32、只存 FOV）、交錯、W = 4、200 MHz** | **6.2 ms** | **7.25×** |

- R2：61 次子集投影 378 ms，剩 2.5 ms/次給 voxel 更新；不需要每次更新重新載入影像（EXP-S13/S15 的瓶頸）。
- 記憶體：FOV 內 1,475,659 voxel × 2 副本：ACC fp32 5,764 + IMG fp16 2,882 = 8,646 個 M20K（74%）。
- 不可行的方案：跳過 x = 0 的 voxel（只有 2%）；用累積負載切 slab（邊緣 lane 平面太多，RAM 不夠）。

## 附錄：GE_DMI4_NEMA_IQ2（使用者先打成 DMI4，後來改成 D690）

同樣流程已做完：1,285,067 事件（re-histogram 完全相同）；KKT 5σ 5.4×10⁻⁵；GPU 到門檻 0.92–1.03 s（第 30 次更新）；
3σ 時球體 AEM 卡在 1.0%（不過門檻），5σ 才通過。結果檔在 `raw/dmi4/`。

## Next action

EXP-S17：R2 的 lane（TOF 核、交錯平面、W = 4、兩副本、轉送器）先寫軟體模型，對 GPU parallelproj 比對；再 HLS、上板。
