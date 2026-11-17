# 目前狀態（2026-11-17）

**32-lane slab 投影引擎在 DE10-Pro 板上 PASS：3.54 G samples/s、4.0 nJ/樣本，超過筆電 GPU（2.66 G/s、36 nJ）。
和 voxel 單元組合後，到 PETRIC 門檻的時間和能量都贏筆電 GPU。**

| 到 PETRIC 門檻（Esser2） | 時間 | 能量 |
|---|---|---|
| GPU RTX 3070 Ti Laptop，list-mode psv（實測，EXP-S9） | 8.62 s | 745 J |
| FPGA v10 8 lanes + voxel 單元（兩者都板上實測，組合計算，EXP-S11） | 14.9 s | 203 J |
| **FPGA slab 32 lanes + voxel 單元 V=1（兩者都板上實測，組合計算，EXP-S12）** | **6.39 s** | **106 J** |
| FPGA slab 32 lanes + voxel 單元 V=4（V=4 是模型） | 4.52 s | 75 J |
| 最後事件後的延遲：GPU / FPGA slab 32 + V=1 / + V=4（online Br 64/64，EXP-S10） | 0.70 / 0.55 / 0.38 s | 61 / 9 / 6 J |

- 演算法：list-mode、依時間切子集的 psv 收斂和原版相同（98 次更新，EXP-S9）；
  online「成長資料 psv + 最後事件後步長重新開始」把最後事件後的工作量從 18.4 epoch 降到 1.5 epoch（EXP-S10）。
- 硬體：voxel 單元 1.0 cycle/voxel、165 MHz、8.6 W（EXP-S11）；
  slab 投影 32 lanes 1.00 cycle/iteration、150 MHz（Fmax 204 MHz）、14.0 W、ALM 25%、RAM 44%（EXP-S12）。

## 下一步

1. 用 Esser2 實際事件和實際影像大小（x、y 主軸分兩次 pass）在板上跑 slab 32。
2. voxel 單元和投影 lanes 放進同一個 bitstream，接 DDR4，在板上跑完整 psv 更新。
3. voxel 單元並行 4 份（V = 4）；預條件（高斯濾波、diag Hessian）硬體化。

## 已知限制

- slab 的測試影像是 128×128×32 和合成事件；Esser2 實際大小兩份副本放不下，要分兩次 pass 或 fp16。
- 投影和 voxel 單元還在不同 bitstream，整機數字是組合計算。
- FPGA 功耗是 Quartus 估計值；GPU 功耗是 nvidia-smi 板上功耗。
- GPU 基準是筆電 GPU；A100 等級 GPU 的 list-mode 寫法會再快數倍。
