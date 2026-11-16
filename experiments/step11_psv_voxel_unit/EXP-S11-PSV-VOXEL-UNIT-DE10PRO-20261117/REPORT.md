# EXP-S11-PSV-VOXEL-UNIT-DE10PRO-20261117 — psv 逐 voxel 單元（RDP stencil + SVRG + 更新），DE10-Pro 板上實測；FPGA 和 GPU 比較

## Verdict

`PASS`（硬體單元）：DE10-Pro 上 1.0 cycle/voxel、165 MHz、結果和軟體一致。
比較結論見最後一節：**能量一定贏（3.7–5 倍）；時間要靠 32-lane slab（模型）才贏筆電 GPU，8 lanes 會輸。**

## What the unit does

psv 每次更新，除了事件投影（Step 1–5 的 lanes），還要對每個 voxel 做：

```
gradR_j = Σ_26 w_jk κ_j κ_k d (2φ − (d + γ|d|)) / φ²        (RDP，3×3×3 stencil)
mode 0：dir = M (B − g_k) − σ (s + β gradR) + g_sum ；x' = max(0, x + α P dir)
mode 1：g_k' = B − (s + β gradR)/M ；g_sum' = g_sum + g_k'        （全梯度時填梯度表）
```

B = 這個子集的反投影結果（c·A_kᵀ(m/ŷ)），g_k、g_sum = SVRG 梯度表，s = sensitivity，P = 預條件，κ = RDP kappa。

- 輸入：每個 voxel 一筆 32 B 記錄 {x, B, g_k, g_sum, s, P, κ, pad}，經 256-bit Avalon-MM host 讀一次（和 DDR 相同的介面）。
- 3×3×3 窗：兩個平面延遲 + 每個平面兩個列延遲 + 3×3×3 移位暫存器（x 和 κ）。
- 中心 voxel 的其他欄位放在片上延遲緩衝（DLY = 163·163 + 163 + 1 個 voxel）等窗口到位。
- 輸出：64-bit {a, b} 寫回。
- 原始碼 `source/psv_update.cpp`（HLS）；系統 `source/psvu_sys.tcl`：JTAG master + 4 MB 256-bit 片上 RAM（代替 DDR）
  + 1 MB 輸出 RAM + 單元；影像平面 163×163（Esser2 的大小）。

## Build history（每一版都在板上量過，`raw/earlier_builds/`）

| 版本 | 改了什麼 | Fmax / PLL | cycles/voxel（nz=4） | 原因 |
|---|---|---|---|---|
| v1 | 第一版：列延遲 rd[3][NX]，兩個讀取埠 | 190 / 200 MHz（時序不過） | 2.35 | 列延遲每圈 3 讀 3 寫，HLS 做成會停頓的仲裁存取 |
| v2 | 列延遲拆成 6 個陣列 | 171 / 175 MHz（不過） | 2.26 | — |
| v3 | 不發 burst | 179 / 165 MHz ✔ | 2.25 | 測 nz = 1–4：啟動段 1 cycle/圈，兩個讀取埠同時讀時 2 cycles/voxel |
| v4 | 每筆記錄只讀一次，中心欄位放片上延遲緩衝（一個 struct 陣列） | 175 / 165 MHz ✔ | 3.17 | HLS 把 struct 拆成 5 個 32-bit 存取，又變成會停頓 |
| **v5** | **延遲緩衝拆成 5 個陣列**（所有片上存取都 stall-free） | **172 / 165 MHz ✔** | **1.28** | 1.00 cycle/圈；nz = 4 時有 25% 是啟動延遲 |

## Results（v5，`analysis/compare_board.txt`、`raw/observe/sc165v4*.log`）

| 項目 | 結果 |
|---|---|
| 正確性 | x' 最大誤差 / 最大值 = 1.3×10⁻⁷（和 HLS 模擬比；模擬和 double 參考比 3.9×10⁻⁵） |
| 每次掃描的 cycles（nz = 1, 2, 3, 4） | 55,976 / 82,583 / 109,148 / 135,671 ＝ n + DLY + 約 2,700（JTAG 啟動）→ **每 voxel 1.00 cycle** |
| Esser2 全影像（95 平面，2.52 M voxels） | 1.031 cycles/voxel（含啟動）→ 165 MHz 時每次 **15.8 ms** |
| 資源 | ALM 35,117（4%）、RAM 3,447（29%，大多是 4 MB 測試 RAM）、DSP 390（7%） |
| 功耗（quartus_pow） | 8.61 W（動態 2.51 W、靜態 6.10 W） |

## FPGA vs GPU（`analysis/fpga_vs_gpu.py`、`fpga_vs_gpu_V1.json`、`fpga_vs_gpu_V4.json`）

工作量（Esser2，到 PETRIC 門檻）：
- **時間一（比賽定義，資料已在裝置上）**：offline list-mode psv，18.375 投影 epoch（EXP-S9）；
  voxel 掃描 158 次（91 次子集更新 + 7 次全梯度 ×（8 表 + 1 步）+ 2 次預條件 × 2）。
- **時間二（最後一個事件之後的延遲）**：online Br 64/64，1.5 投影 epoch、voxel 掃描 15 次（EXP-S10）。

裝置：
- GPU：RTX 3070 Ti Laptop，list-mode psv 實測 8.62 s、86.4 W（EXP-S9，含 voxel 運算）；online 依 epoch 比例換算。
- FPGA 投影：v10 8 lanes 板上實測 1106 M sample/s、11.1 W；slab 32 lanes 是模型（EXP-S5，3.1 G/s，動態功耗依 lane 數線性放大）。
- FPGA voxel 單元：本實驗 v5（V = 1，實測）；V = 4 是模型（4 份單元並行，需要約 4× DDR 頻寬）。
- 同一顆 FPGA：靜態功耗只算一次。

| 工作 | 裝置 | 時間 | 功率 | 能量 |
|---|---|---|---|---|
| 時間一 | GPU（實測） | **8.62 s** | 86 W | 745 J |
| 時間一 | FPGA v10 8 lanes + voxel V=1（實測組合） | 14.9 s | 13.6 W | **203 J** |
| 時間一 | FPGA slab 32 + voxel V=1（模型） | 6.9 s | 28.5 W | 197 J |
| 時間一 | FPGA slab 32 + voxel V=4（模型） | **5.1 s** | 28.5 W | **144 J** |
| 時間二 | GPU（實測換算） | **0.70 s** | 86 W | 61 J |
| 時間二 | FPGA v10 8 lanes + voxel V=1（實測組合） | 1.25 s | 13.6 W | **17 J** |
| 時間二 | FPGA slab 32 + voxel V=4（模型） | **0.42 s** | 28.5 W | 12 J |

（對照：原版 sinogram psv 在同一張 GPU 上要 153 s，A100 排行榜 78–87 s。）

## Analysis and conclusion

1. **能量：FPGA 一定贏。** 用板上實測的部分組合（8 lanes + voxel 單元），每次重建約 200 J，GPU 745 J（3.7 倍）；
   online 的延遲段 17 J 對 61 J。
2. **時間：8 lanes 輸，32-lane slab 會贏筆電 GPU。** 8 lanes 比筆電 GPU 慢 1.7 倍；
   32-lane slab（模型）加 4 份 voxel 單元，時間一 5.1 s 對 8.6 s，時間二 0.42 s 對 0.70 s。
   **但 32-lane slab 和 V = 4 還沒有在板上做出來**，這是下一步要驗證的。
3. **GPU 基準是我們自己寫的 list-mode 版**，比 STIR sinogram 版快 15 倍；A100 等級的 GPU 還會再快數倍。
   所以對資料中心 GPU，FPGA 的主張只能是能量和 online 串流，不是絕對速度。
4. voxel 單元本身不是瓶頸：每次掃描 15.8 ms，比一個子集的投影（v10 約 85 ms）小很多；
   V = 4 時每 voxel 每 cycle 要讀 4×32 B，165 MHz 下約 21 GB/s，DE10-Pro 的 4 組 DDR4 足夠。
5. HLS 的教訓：片上陣列只要每圈超過 1 讀 1 寫（包括 struct 被拆成多個欄位），就會變成會停頓的仲裁存取，
   吞吐量掉到 1/2–1/3。每個 line buffer 都要拆成 1 讀 1 寫的獨立陣列。

## Not done

- voxel 單元還沒和投影 lanes 放在同一個 bitstream；還沒接 DDR4（用片上 RAM 代替）。
- 預條件（高斯濾波 + diag Hessian）用 2 次掃描估計，沒有做成硬體。
- 32-lane slab 投影引擎只有模型（EXP-S5）。
- LM-SPDDY（做法 C）沒有做。
