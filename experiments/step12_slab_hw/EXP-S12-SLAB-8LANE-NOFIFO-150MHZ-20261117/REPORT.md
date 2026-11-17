# EXP-S12-SLAB-8LANE-NOFIFO-150MHZ-20261117 — slab 投影引擎第一版（8 lanes，lane 之間沒有 FIFO）

## Verdict

`FAIL`（速度）：結果正確，但只有 426 M samples/s（每 iteration 2.46 cycles）。
原因已在板上找到：前投影部分和鏈（padd）沒有輸入 FIFO，把整條鏈鎖成同步。修正版見 `EXP-S12-SLAB-8-32LANE-150MHZ-20261117`。

## Objective

把 EXP-S5 的 slab 模型做成硬體：影像沿射線主軸切成 N 段，lane k 只存第 k 段，所有 lane 共用一份影像。
先用 8 lanes 驗證正確性和每 iteration 1 cycle。

## Design（`source/slab.cpp`）

- 每個區塊是一個 HLS 元件，Platform Designer 依 lane 數重複放置（`source/slab_sys.tcl`），
  所以 HLS 編譯時間和 lane 數無關（EXP-S4 的 16 lanes 寫成一個元件，HLS 8 小時跑不完）。
- 元件：`slab_src`（從片上記憶體送 token）→ N ×（`slab_exp` 展開步數 → `slab_eng` 記憶體運算與轉送）→ `slab_sink`；
  前投影部分和另走一條鏈：`slab_src` → N × `padd` → `slab_sink`，`slab_eng k` 把本段的部分和送給 `padd k`。
- lane 只走落在自己 slab 的 Joseph 步；每個 token 在每條 lane 多花 1 iteration。
- 反投影 RMW 衝突：主機排序事件，讓同一條 lane 在 HAZ = 64 iterations 內不會寫同一個 voxel（引擎迴圈延遲 35）；
  排不開時插 NOP token，只讓那一條 lane 空轉。
- 測試影像 128×128×32（x、y 兩份主軸副本），8,000 個合成事件（平均 116.7 步），和 EXP-S4 相同的產生方式。

本資料夾的 `source/slab.cpp` 是修正版去掉兩個 FIFO（`TOKBUF`）後的內容，和當時建置的版本相同。

## Build

- HLS 迴圈：`slab_exp`、`slab_eng`、`padd`、`slab_src`、`slab_sink` 全部 II = 1。
  中間兩個失敗的 HLS 版本（沒有上板）：
  1. lane 寫成單一迴圈：II = 36，因為「要不要讀下一個 token」依賴剛讀的 token。改成 exp + eng 兩級。
  2. exp 仍是 II = 2（步數範圍計算在回饋路徑上）。改成由上一級先算好下一條 lane 的範圍放在 token 裡。
- Quartus：Fmax 213.5 MHz，150 MHz 時序通過；ALM 7%、RAM 39%、DSP 3%（`raw/build/`）。

## Runtime observations

| 項目 | 結果 |
|---|---|
| 前投影比值 s | 最大相對誤差 1.2×10⁻⁷ ✔ |
| 反投影 | 最大誤差 / 最大值 = 8.7×10⁻⁸ ✔ |
| 每次前投影 + 反投影 | 4.38 ms = 657,000 cycles；最忙 lane 只需 266,702 iterations → **2.46 cycles/iteration** ✘ |

找原因的板上探測（`source/probe.tcl`，事件檔在 `raw/testdata/`；數字當時在 System Console 讀到）：

| 事件檔 | 每次 pass | 換算 |
|---|---|---|
| `probe_nop.bin`：16,000 個不碰任何 lane 的 NOP token | 0.105 ms | 每個 token 1.0 cycle |
| `probe_nop16.bin`：lane 0 每個 token 16 個空步 | 1.81 ms | 每個 iteration 1.0 cycle |
| 真實事件 | 4.38 ms | 2.46 cycles/iteration |

NOP 測試不送部分和（PTok），速度正常；真實事件的前投影要送部分和，就變慢。

## Analysis and conclusion

- `padd` 先讀上一級的部分和，再等本 lane 的局部和；等待時它不收下一個部分和。
  `padd` 前面沒有 FIFO，所以 src 和所有 lane 只能比部分和鏈領先約 1 個事件，整條鏈變成「每個事件等最慢的 lane」。
- 修正：`padd` 的部分和輸入和每條 lane 的 token 輸入都加 256 深的 FIFO。
  時序模型（`EXP-S12-SLAB-8-32LANE.../source/fifo_model.py`）顯示 32 lanes 需要 FIFO 深度 ≥ 16。

## Next action

- 加 FIFO 重建 8 lanes 和 32 lanes → `EXP-S12-SLAB-8-32LANE-150MHZ-20261117`。
