# 目前狀態（2026-11-17）

**投影引擎：32-lane slab 在 Esser2 實際影像大小、真實事件上 PASS（3.69 G samples/s、4.7 nJ/樣本；筆電 GPU 2.66 G/s、36 nJ）。
整機：能量一定贏；時間要先做「每條 lane 從 DDR 平行載入 slab」才會贏筆電 GPU（EXP-S13）。**

| 到 PETRIC 門檻（Esser2） | 時間 | 能量 |
|---|---|---|
| GPU RTX 3070 Ti Laptop，list-mode psv（實測，EXP-S9） | 8.62 s | 745 J |
| FPGA slab 32 + voxel 單元，影像 / 累加器經 token 鏈串列搬移（現在的做法，零件實測、組合計算，EXP-S13） | 16.2 s | 323 J |
| FPGA slab 32 + voxel 單元，每條 lane 平行載入（模型，EXP-S13） | 6.5 s | 130 J |
| 最後事件後的延遲：GPU / FPGA 串列 / FPGA 平行（模型）（online Br 64/64，EXP-S10） | 0.70 / 1.35 / 0.57 s | 61 / 27 / 11 J |

**更正**：EXP-S11、EXP-S12 的整機比較沒有計入每次更新的影像載入和累加器讀出；
EXP-S12 的「6.4 s / 106 J 贏 GPU」只在平行載入下成立（EXP-S13）。

- 演算法：list-mode psv 收斂和原版相同（EXP-S9）；online 成長資料 psv 把最後事件後的工作量從 18.4 降到 1.5 epoch（EXP-S10）。
- 硬體：voxel 單元 1.0 cycle/voxel、165 MHz、8.6 W（EXP-S11）；slab 投影 32 lanes 1.0 cycle/iteration、150 MHz（Fmax 204）、
  17.5 W、RAM 79%（Esser2 實際大小，4 次 pass，EXP-S13）。

## 下一步

1. 每條 lane 的 slab 從 DDR 平行載入 / 讀出（或 voxel 更新直接寫回 lane），在板上量整個 psv 更新。
2. voxel 單元和投影 lanes 放進同一個 bitstream，接 DDR4。
3. 依累積負載切 slab 邊界（平衡 0.81 → 接近 1）；處理主軸是 z 的事件（0.11%）。
4. voxel 單元並行 4 份；預條件硬體化。

## 已知限制

- 整機數字是零件實測加組合計算，不是同一次執行。
- FPGA 功耗是 Quartus 估計值；GPU 功耗是 nvidia-smi 板上功耗。
- GPU 基準是筆電 GPU；A100 等級 GPU 的 list-mode 寫法會再快數倍。
