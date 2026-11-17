# EXP-S13-SLAB32-ESSER2-REALSIZE-20261117 — 32-lane slab 投影，PETRIC2 Esser2 實際事件與實際影像大小，DE10-Pro 板上實測

## Verdict

`PASS`（投影引擎）：Esser2 實際影像（95×163×163，fp32）、真實 list-mode 事件，板上結果和 GPU parallelproj 一致
（s 最大相對差 3.0×10⁻⁵，反投影最大差 7.9×10⁻⁵），**3.69 G samples/s、4.7 nJ/樣本**（筆電 GPU 2.66 G/s、36 nJ）。

`FAIL`（整機時間，照現在的做法）：每次 psv 更新都要把新影像載入 lanes、把累加器讀出。
現在經由 token 鏈一個 voxel 一個 cycle，到門檻要 9.95 s，整機 16.2 s，比筆電 GPU 的 8.6 s 慢。
**更正 EXP-S11/S12 的比較**：那兩份沒有計入這項搬移；EXP-S12 的「6.4 s 贏 GPU」不成立，除非做每條 lane 平行載入（模型 0.31 s，整機 6.5 s）。

## Objective

1. 用 Esser2 實際事件和實際影像大小在板上跑 slab 32，確認正確性（對 GPU parallelproj）和速度。
2. 用實測數字重算到 PETRIC 門檻的 FPGA vs GPU。

## Inputs（`raw/testdata/`，`source/prep_esser2.py`）

- `D:\PET_DATA\listmode\NeuroLF_Esser2\fpga_events.bin`（EXP-S6，SHA-256 在 `prep.json`）前 16,000 個事件（時間順序），
  影像 = PETRIC `OSEM_image`。
- 15,977 個事件可用：18 個（0.11%）的主軸是 z（硬體只有 x、y 主軸），5 個不經過影像；這 23 個從測試和參考值都排除。
- 射線裁切：只取內插點在影像框內（體素邊界，即中心外半格）的平面，這和 parallelproj 相同。
  先試過「內插支撐和影像重疊」，0.4% 事件（軸向邊緣）差到 17%；改成體素邊界後，2,000 個事件的前投影和 parallelproj 最大差 4.3×10⁻⁵。
- 參考值：本機 RTX 3070 Ti 上 parallelproj Joseph（與 EXP-S9 相同）：
  s_ref = 1/(c·A x + a)，back_ref = c·Aᵀ s_ref（list-mode 梯度的第一項）。
  硬體 ratio 設 y = 1：s_hw = mw/(mw·F + a)，所以 s_hw/mw 對應 s_ref，硬體反投影對應 back_ref。

## Design changes from EXP-S12（`source/slab4.cpp`）

- 實際影像兩份主軸副本放不下 M20K（每條 lane 6 個平面就要 12,032 個 M20K > 11,721）。
  改成每次 pass 只放一個主軸方向、半個主軸（82 個平面）：4 次 pass（x 前半、x 後半、y 前半、y 後半），fp32 不變。
- slab 可以不等寬：lane id 負責第 ⌊id·82/32⌋ 到 ⌊(id+1)·82/32⌋ 個平面（2 或 3 個）。
- token 那一圈同時做第一個本段步：每個 token 在一條 lane 花 max(1, 本段步數) 圈（EXP-S12 是 1 + 步數）。
- 前半 pass 的前投影部分和由 sink 原樣送回主機，後半 pass 由 src 當起始值送進部分和鏈（`finit`），sink 算 ratio。
- 主機排程（反投影 RMW 間隔 HAZ = 64，引擎迴圈延遲 35）照新的 lane 時間模型；每個 pass 插 9–18 個 NOP。

## Build（`raw/build/`）

- HLS：所有迴圈 II = 1。
- Quartus 92 分：Fmax 204.4 MHz（150 MHz 時序通過）；ALM 271,098（29%）、RAM 9,277（79%）、DSP 710（12%）。
- 功耗（quartus_pow）：17.45 W（動態 11.15 W、靜態 6.30 W）。

## Runtime observations（`raw/observe/board4.log`、`analysis/compare_board.txt`、`analysis/timing4.txt`）

正確性：

| | 結果 |
|---|---|
| 每個 pass 的前投影（部分和或 s），對軟體模型 | 最大相對差 ≤ 2.9×10⁻⁷ |
| 每個 pass 的累加器，對軟體模型 | 最大差 / 最大值 ≤ 1.4×10⁻⁷ |
| 4 個 pass 合起來的 s，對 GPU parallelproj | 最大相對差 **3.0×10⁻⁵**（中位數 9.2×10⁻⁷） |
| 4 個 pass 合起來的反投影，對 GPU parallelproj | 最大差 / 最大值 **7.9×10⁻⁵** |

速度（每個 pass 跑 1 次和 2001 次，取差；150 MHz）：

| | 結果 |
|---|---|
| 每個 pass 的 cycles / 最忙 lane 的 iterations | 0.996–1.000 |
| 4 個 pass 的前投影 + 反投影，15,977 個事件（2,295,582 步） | 1.2435 ms |
| **樣本 / 秒** | **3.69 G**（效率 0.77；EXP-S12 合成事件 0.74） |
| 能量 | **4.73 nJ/樣本** |
| 一個投影 epoch（全部 2,601,282 個事件）換算 | 0.203 s（GPU list-mode psv 每 epoch 0.47 s，含 voxel 運算） |

## FPGA vs GPU 到 PETRIC 門檻（`source/timing4.py`；工作量同 EXP-S11）

影像載入和累加器讀出：每個子集（1/8 epoch）要載入 4 個半影像、讀出 4 個累加器，共 10,158,160 個 voxel。
現在經由 token 鏈每 cycle 一個：67.7 ms；每條 lane 從 DDR 平行載入自己的 slab（模型，需要 19.2 GB/s）：2.1 ms。

| 工作 | 裝置 | 時間 | 能量 |
|---|---|---|---|
| 時間一 | GPU（實測，EXP-S9） | **8.62 s** | 745 J |
| | FPGA slab 32 + voxel V=1，**現在的串列載入** | 16.17 s（投影 3.72 + voxel 2.49 + 搬移 9.95） | 323 J |
| | FPGA slab 32 + voxel V=1，每條 lane 平行載入（模型） | **6.52 s** | **130 J** |
| | FPGA slab 32 + voxel V=4，平行載入（模型） | 4.65 s | 93 J |
| 時間二（最後事件後） | GPU | **0.70 s** | 61 J |
| | FPGA slab 32 + voxel V=1，現在的串列載入 | 1.35 s | 27 J |
| | FPGA slab 32 + voxel V=1，平行載入（模型） | **0.57 s** | **11 J** |

## Analysis and conclusion

1. **投影引擎在實際問題上成立**：實際影像大小、真實事件，結果和 GPU 參考一致，速度 1 cycle/iteration，3.69 G/s，
   比筆電 GPU 快 1.39 倍、能量少 7.6 倍。
2. **能量一定贏**：即使用現在的串列載入，到門檻 323 J，GPU 745 J（2.3 倍）。
3. **時間要靠平行載入**：現在的整機瓶頸不是投影，而是每次更新的影像載入和累加器讀出（佔 62%）。
   每條 lane 從 DDR 直接載入自己的 slab 後，搬移降到 0.31 s，整機 6.5 s，贏筆電 GPU。這一步還沒做。
4. 負載平衡 0.81（slab 有 2 或 3 個平面）；照累積負載切 slab 邊界，可再提升。
5. 主軸是 z 的事件（0.11%）硬體還不能處理；可交給主機或增加一個 z 主軸 pass。

## Next action

1. 每條 lane 的 slab 從 DDR 平行載入 / 讀出（或 voxel 更新直接寫回 lane 的 IMG），在板上量整個 psv 更新。
2. 投影 lanes 和 voxel 單元放進同一個 bitstream。
3. 依累積負載切 slab 邊界；處理 z 主軸事件。
