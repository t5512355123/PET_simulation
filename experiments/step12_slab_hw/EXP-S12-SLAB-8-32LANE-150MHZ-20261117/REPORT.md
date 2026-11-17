# EXP-S12-SLAB-8-32LANE-150MHZ-20261117 — slab 投影引擎 8 lanes 和 32 lanes，DE10-Pro 板上實測

## Verdict

`PASS`：32 lanes 在板上 **3.54 G samples/s**（筆電 GPU 2.66 G/s），結果正確，估計功耗 14.0 W（**4.0 nJ/樣本**，GPU 36 nJ）。
和 EXP-S11 的 voxel 單元組合後，到 PETRIC 門檻的時間和能量**都贏筆電 GPU**（6.4 s / 106 J 對 8.6 s / 745 J）。

## Objective

1. 修正 `EXP-S12-SLAB-8LANE-NOFIFO-150MHZ-20261117` 的速度問題，達到每 iteration 1 cycle。
2. 把 slab 擴充到 32 lanes，量測速度、資源、功耗，驗證 EXP-S5 的模型（32 lanes 約 3.1 G/s）。

## Design change（`source/slab.cpp`，和 NOFIFO 版只差兩行）

- 每條 lane 的 token 輸入加 256 深 FIFO（`slab_exp`）。
- 每個 `padd` 的部分和輸入加 256 深 FIFO。

架構、測試資料和 NOFIFO 版相同：影像 128×128×32（x、y 兩份主軸副本），8,000 個合成事件，HAZ = 64。
32 lanes 時每條 lane 只有 4 個平面；排程插了 3 個 NOP（130 個空 iteration）。

## Build（`raw/lanes8/build`、`raw/lanes32/build`）

| | 8 lanes | 32 lanes |
|---|---|---|
| HLS | 全部迴圈 II = 1；每種元件只編一次（約 10 分鐘，和 lane 數無關） | 同左 |
| Quartus 時間 | 29 分 | 76 分（第一次 fitter 在繞線時 segfault，`compile_try1_fitter_crash.log.gz`；原樣重跑成功） |
| Fmax（150 MHz 時序） | 219.1 MHz ✔ | 204.3 MHz ✔ |
| ALM | 68,896（7%） | 229,736（25%） |
| RAM blocks | 4,654（40%） | 5,182（44%） |
| DSP | 181（3%） | 709（12%） |
| 功耗（quartus_pow） | 10.54 W（動態 4.45、靜態 6.09） | 14.04 W（動態 7.80、靜態 6.24） |

## Runtime observations（`raw/lanes*/observe/`、`analysis/compare_board_lanes*.txt`）

| | 8 lanes | 32 lanes |
|---|---|---|
| 前投影比值 s：最大相對誤差 | 1.2×10⁻⁷ ✔ | 1.2×10⁻⁷ ✔ |
| 反投影：最大誤差 / 最大值 | 8.7×10⁻⁸ ✔ | 8.7×10⁻⁸ ✔ |
| 每次前投影 + 反投影（`probe_ev.log`，長時間量測） | 1.778 ms | 0.527 ms |
| 最忙 lane 的 iterations | 2 × 133,351 | 2 × 39,578 |
| **cycles / iteration** | **1.00** | **1.00** |
| **樣本 / 秒**（前投影 + 反投影的真實 Joseph 步） | **1.05 G** | **3.54 G** |
| 每條 lane 每 cycle 的樣本 | 0.87 | 0.74 |
| 能量 | 10.0 nJ/樣本 | **4.0 nJ/樣本** |

樣本的定義和 EXP-S4 `compare_board.py` 相同。

## Analysis

1. **每 iteration 1.00 cycle**：加 FIFO 後，時間完全由最忙 lane 的 iterations 決定（token + 本段步數 + NOP）。
2. **32 lanes 效率 0.74**（模型 `analysis/swsim_lanes32.txt` 預測 0.737，板上 0.737）。
   損失來自每個 token 在每條 lane 的 1 iteration，加上邊緣 slab 負載較少（平衡 0.94）。
   EXP-S5 用 2 cycles/段估計 0.65；實作只多 1 iteration，所以比模型好。
   用 EXP-S5 的 Esser2 事件統計（每事件 143.4 步、碰到 28.4 段、平衡 0.912）換算，效率約 0.76，和合成事件接近。
3. **比較**：

| | 樣本/秒 | nJ/樣本 | 影像存法 |
|---|---|---|---|
| v10 8 lanes（EXP-S4） | 1.11 G | 10.0 | 每條 lane 一份 64×64×32 |
| slab 8 lanes | 1.05 G | 10.0 | 共用一份 128×128×32（大 8 倍） |
| **slab 32 lanes** | **3.54 G** | **4.0** | 共用一份 128×128×32 |
| GPU RTX 3070 Ti Laptop | 2.66 G | 36 | — |

4. **FPGA vs GPU 到 PETRIC 門檻**（`analysis/fpga_vs_gpu_S12_V*.txt`；工作量同 EXP-S11：
   offline 18.375 投影 epoch + 158 次 voxel 掃描；online Br 64/64 最後事件後 1.5 epoch + 15 次掃描；
   投影和 voxel 單元都是板上實測，組合計算；同一顆晶片靜態功耗只算一次）：

| 工作 | 裝置 | 時間 | 能量 |
|---|---|---|---|
| 時間一（比賽定義） | GPU（實測） | 8.62 s | 745 J |
| | FPGA slab 32 + voxel 單元 V=1（兩者實測） | **6.39 s** | **106 J** |
| | FPGA slab 32 + voxel 單元 V=4（V=4 是模型） | 4.52 s | 75 J |
| 時間二（最後事件後延遲） | GPU（實測換算） | 0.70 s | 61 J |
| | FPGA slab 32 + voxel 單元 V=1 | **0.55 s** | **9 J** |
| | FPGA slab 32 + voxel 單元 V=4 | 0.38 s | 6 J |

## Limits

- 測試影像是 128×128×32 和合成事件，不是 Esser2（95×163×163）。Esser2 兩份主軸副本加累加器要約 323 Mb，
  超過 M20K 的 234 Mb；要改成 x、y 主軸分兩次 pass（162 Mb）或影像存 fp16。
- 投影和 voxel 單元還在不同 bitstream；比較是組合計算，不是同一次執行。
- FPGA 功耗是 Quartus 估計（toggle rate 信心「Low」）；GPU 是 nvidia-smi 板上功耗。
- GPU 基準是筆電 GPU；A100 等級 GPU 會快數倍，對資料中心 GPU 的主張仍是能量。

## Next action

1. 用 Esser2 實際事件和實際影像大小（分 x、y 兩次 pass）在板上跑 slab 32。
2. 投影 lanes 和 voxel 單元放進同一個 bitstream，接 DDR4，跑完整 psv 更新。
3. 試 200 MHz（Fmax 204 MHz，餘裕很小）。
