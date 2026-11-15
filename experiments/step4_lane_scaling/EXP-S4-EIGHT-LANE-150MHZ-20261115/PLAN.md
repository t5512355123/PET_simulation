# EXP-S4-EIGHT-LANE-150MHZ-20261115 — 8 條 lane，150 MHz

Date: 2026-11-15
Baseline: `EXP-S3-PARITY-BANK-LAYOUT-20261115`（v8，4 lanes，125 MHz）

## Objective and hypothesis

v8 的 Fmax 是 166.7 MHz，ALM 只用 6%。假設 8 條 lane 在 150 MHz 仍能通過時序，
速度約 8 × 150 / 1.17 ≈ 1.0 G 樣本/秒，能量仍低於 GPU 的 36 nJ/樣本。

（這個實驗是 16 lanes 版本的 HLS 超過 2 小時沒結束時加開的備案。）

## Baseline and fixed conditions

- 引擎、bank 配置、排序方式和 v8 相同；影像 64×64×32。
- 測試資料：4000 個事件 → 4016 個（排序後），235,054 步；最忙的 lane 29,735 步（`raw/testdata/`）。
- 軟體模擬（ACTIVE=8）：前投影最大相對誤差 1.6×10⁻⁷，反投影 2.0×10⁻⁷，PASSED。

## Single variable under test

lane 數 8（PLL 150 MHz 是一起改的第二個變數；時序不過時改回 125 MHz 重測）。

## Procedure

1. `i++` → `qsys-script` → `build.sh`（`source/full.sh`）。
2. 檢查 Fmax ≥ 150 MHz。
3. 燒錄，執行 `board_test.tcl`（rep 2000），再執行 `compare_board.py <dir> 2000 <wall_ms> 150`。
4. 執行 quartus_pow。

## Acceptance criteria and stop conditions

- 反投影最大誤差 / 最大值 ≤ 10⁻⁶，前投影比值最大相對誤差 ≤ 10⁻⁶。
- Fmax ≥ 150 MHz。
- 速度 > 850 M 樣本/秒（v8 的 2 倍）。
