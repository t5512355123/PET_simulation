# EXP-S6-SINOGRAM-TO-LISTMODE-PETRIC2-20261116 — PETRIC2 sinogram 轉 list-mode

## Verdict

`PASS`（三組 non-TOF 測試資料）

## Objective

PETRIC 與 PETRIC2 只提供 sinogram（prompts、mult_factors、additive_term）。
要做 list-mode 串流重建並和比賽比較，需要和比賽資料完全等價的 list-mode 事件。

## Method（`source/sino2lm.py`、`source/lm_check.py`）

- 資料：PETRIC2 官方 File Browser 下載到 `D:\PET_DATA\petric2\`（.26 當時無法連線）。下載紀錄 `raw/observe/download.log`。
- 每個計數為 y 的 bin 產生 y 個事件。每個事件記錄：
  `t`（frame 內時間）、`bin`（`ProjData.to_array()` 的扁平索引）、`m`、`a`（該 LOR 的乘法因子與加法項）。
- 時間戳記是合成的：sinogram 沒有時間順序，所以在 [0, 1) 均勻抽樣後排序（靜態掃描下的 Poisson 過程），seed 20261116。
- LOR 端點：STIR 6.5 `get_LOR`（和 PETRIC 的 parallelproj 投影器相同幾何）。
- 沒有存晶體編號：STIR Python 介面沒有公開 BlocksOnCylindrical 的 bin → 晶體對；
  mMR 是 span 11，一個 bin 本來就對應多對晶體。重建只需要 bin 的 LOR。
- FPGA 事件檔 `fpga_events.bin`：每個事件 8 個 float32（z1 y1 x1 z2 y2 x2 m a），依時間排序。
- sensitivity 影像 s = c·Aᵀm 用全部 bin 算一次（list-mode 重建的固定輸入）。

## Checks

1. 事件重新直方圖化 = prompts（逐 bin、整數完全相同）。
2. 在 OSEM 影像上，用同一個 parallelproj Joseph 投影器（GPU）比較：
   - sinogram 梯度：c·Aᵀ(m·y/ŷ) − c·Aᵀm（所有 bin）
   - list-mode 梯度：c·Σₑ Aₑᵀ(mₑ/ŷₑ) − s（每個事件一次）
   - ŷ = m·(c·Ax + a)，c = 1/橫向 voxel 大小。

## Results（`raw/observe/<dataset>/meta.json`、`check.json`）

| 資料 | 影像 | sinogram bins | 非零 bins | 事件數 | 事件 / 非零 bin | 重新直方圖化 | 梯度 max 差 / max | 相對 L2 |
|---|---|---|---|---|---|---|---|---|
| NeuroLF_Esser2 | 95×163×163 | 53,084,160 | 2,503,978 | 2,601,282 | 1.039 | 相同 ✔ | 4.7×10⁻⁶ | 3.9×10⁻⁶ |
| NeuroLF_Hoffman2 | 95×163×163 | 53,084,160 | 6,024,882 | 6,882,698 | 1.142 | 相同 ✔ | 5.5×10⁻⁶ | 6.8×10⁻⁶ |
| Siemens_mMR_ACR2 | 127×285×285 | 72,557,856 | 1,964,805 | 2,026,156 | 1.031 | 相同 ✔ | 2.2×10⁻⁶ | 1.2×10⁻⁶ |

梯度差在 float32 加總順序的誤差範圍內，所以 list-mode 和 sinogram 的模型等價。

資料量：

| 資料 | 三份 dense sinogram（fp32） | FPGA 事件檔 | 比例 |
|---|---|---|---|
| Esser2 | 637 MB | 83 MB | 13% |
| Hoffman2 | 637 MB | 220 MB | 35% |
| ACR2 | 871 MB | 65 MB | 7.4% |

同一支腳本（含 host↔GPU 複製，未調校）算一次梯度：Esser2 dense 11.1 s → list-mode 1.2 s；
Hoffman2 6.8 s → 3.7 s；ACR2 11.9 s → 1.7 s。這只是參考，不是 benchmark。

## Limits

- 時間順序是合成的；真實掃描的時間順序對靜態影像重建沒有影響，但對動態分析或 online 演算法的收斂順序有影響。
- 只處理 non-TOF。TOF 資料（DMI3_Torso2、D690_NEMA_IQ2、DMI4_NEMA_IQ2）正在下載，需要再加 TOF bin。
- 輸出檔在 `D:\PET_DATA\listmode\<dataset>\`（太大，不進 git），SHA-256 在 `raw/observe/output_files_SHA256.txt`。

## Next action

1. TOF 版轉換。
2. 用 list-mode 事件跑 psv（子集改成時間分段），確認仍能達到 PETRIC2 門檻。
3. Esser2 事件檔送進 FPGA（Step 5 slab 架構）。
