# 目前狀態（2026-11-18）

**投影 + 影像搬移 + voxel 單元，全部用板上實測的零件組合：到 PETRIC 門檻 FPGA 7.67 s / 236 J，筆電 GPU 8.62 s / 745 J（EXP-S15）。
時間快 11%、能量少 3.2 倍。三個零件還在不同 bitstream，整機是組合計算。**

| 到 PETRIC 門檻（Esser2） | 時間 | 能量 |
|---|---|---|
| GPU RTX 3070 Ti Laptop，list-mode psv（實測，EXP-S9） | 8.62 s | 745 J |
| FPGA slab 32 + 影像經 token 鏈串列搬移 + voxel 單元（EXP-S13） | 16.2 s | 323 J |
| **FPGA slab 32 + DDR4 寬鏈搬移 + voxel 單元（EXP-S15）** | **7.67 s** | **236 J** |
| FPGA，同上，voxel 單元並行 4 份（模型） | 5.80 s | 178 J |
| 最後事件後的延遲：GPU / FPGA（EXP-S15，online Br 64/64） | 0.70 / 0.66 s | 61 / 20 J |

- 演算法：list-mode psv 收斂和原版相同（EXP-S9）；online 成長資料 psv 把最後事件後的工作量從 18.4 降到 1.5 epoch（EXP-S10）。
  **完整演算法目前只在 GPU 上跑過；FPGA 上是零件（投影、搬移、voxel 更新）分別實測。**
- 硬體：
  - slab 投影 32 lanes：Esser2 實際大小，1.0 cycle/iteration，3.69 G samples/s（EXP-S13/S15）。
  - DDR4A 啟用（EXP-S14）；寬鏈每子集搬移 9.86 ms（EXP-S15）。
  - voxel 單元：1.0 cycle/voxel（EXP-S11）。
  - 整個設計 150 MHz，ALM 56%、RAM 83%，估計 28.2 W（EXP-S15）。

## 下一步

1. voxel 單元放進同一個 bitstream（讀寫 DDR），在板上跑完整 psv 子集更新，接著跑完整的 online list-mode psv。
2. 寬鏈提高到 1 字/cycle（現在 0.52 / 0.38）；voxel 單元並行 4 份。
3. 依累積負載切 slab 邊界；處理主軸是 z 的事件（0.11%）。

## 已知限制

- 整機數字是零件實測加組合計算，不是同一次執行。
- FPGA 功耗是 Quartus 估計值（不含 SO-DIMM）；GPU 功耗是 nvidia-smi 板上功耗。
- GPU 基準是筆電 GPU；A100 等級 GPU 的 list-mode 寫法會再快數倍。
