# EXP-S4-SIXTEEN-LANE-150MHZ-20261115 — 16 條 lane，150 MHz

Date: 2026-11-15
Baseline: `EXP-S3-PARITY-BANK-LAYOUT-20261115`（v8，4 lanes，125 MHz）

## Objective and hypothesis

16 × 150 / 1.17 ≈ 2.05 G 樣本/秒，接近筆電 GPU 的 2.66 G 樣本/秒；
能量若維持在 GPU 以下，就在速度相近的情況下省電。

## Baseline and fixed conditions

- HLS 原始碼 `source/ev_v9.cpp`，由 `patch_lanes16.py` 把 `lanes_part.cpp` 擴充到 16 lanes。
- 測試資料：4000 → 4016 個事件，235,054 步；最忙的 lane 14,883 步，平衡度 0.987（`raw/testdata/`）。
- 軟體模擬（ACTIVE=16）通過。

## Single variable under test

lane 數 16（PLL 150 MHz）。

## Procedure

和 `EXP-S4-EIGHT-LANE-150MHZ-20261115` 相同。

## Acceptance criteria and stop conditions

- 正確性門檻和 8 lanes 版相同。
- Fmax ≥ 150 MHz；時序不過時改回 125 MHz。
- quartus_syn 記憶體不足或 HLS 超過 6 小時就停止，改用 8 lanes 的結果。
