# 目前狀態（2026-11-17）

**list-mode online psv：演算法 PASS（GPU），硬體單元 PASS（DE10-Pro），整機比較是「實測零件 + 模型」。**

| 到 PETRIC 門檻（Esser2） | 時間 | 能量 |
|---|---|---|
| GPU RTX 3070 Ti Laptop，list-mode psv（實測，EXP-S9） | 8.62 s | 745 J |
| FPGA v10 8 lanes + voxel 單元（兩者都板上實測，組合計算，EXP-S11） | 14.9 s | 203 J |
| FPGA slab 32 lanes + voxel ×4（模型，EXP-S5/S11） | 5.1 s | 144 J |
| 最後事件後的延遲：GPU / FPGA 8 lanes / FPGA slab 32（online Br 64/64，EXP-S10） | 0.70 / 1.25 / 0.42 s | 61 / 17 / 12 J |

- 演算法：list-mode、依時間切子集的 psv 收斂和原版相同（98 次更新，EXP-S9）；
  online「成長資料 psv + 最後事件後步長重新開始」把最後事件後的工作量從 18.4 epoch 降到 1.5 epoch（EXP-S10）。
- 硬體：voxel 單元（RDP 3×3×3 stencil + SVRG + 更新）1.0 cycle/voxel、165 MHz、8.6 W（EXP-S11）。

## 下一步

1. 32-lane slab 投影引擎做成硬體（現在只有模型）。
2. voxel 單元和投影 lanes 放進同一個 bitstream，接 DDR4，在板上跑完整 psv 更新。
3. voxel 單元並行 4 份（V = 4）。
4. 預條件（高斯濾波、diag Hessian）硬體化。

## 已知限制

- 投影 lanes 的測試影像只有 64×64×32（每條 lane 一份副本）；voxel 單元用 163×163 平面、4 個平面。
- FPGA 功耗是 Quartus 估計值；GPU 功耗是 nvidia-smi 板上功耗。
- GPU 基準是筆電 GPU；A100 等級 GPU 的 list-mode 寫法會再快數倍。
