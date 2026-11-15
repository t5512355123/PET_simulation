# EXP-S4-SIXTEEN-LANE-150MHZ-20261115 — 16 條 lane，150 MHz

## Verdict

`INCONCLUSIVE`：HLS 沒有完成，硬體沒有建出來。

## Build and source provenance

- HLS 原始碼 `source/ev_v9.cpp`（16 lanes）。
- `aocl-opt`（HLS 主最佳化器）從 2026-11-15 13:05 跑到 21:14，共 8 小時 9 分，
  記憶體約 4.4 GB，沒有結束。超過 PLAN 的停止條件（6 小時），所以手動停止；
  i++ 回報 `HLS Main Optimizer FAILED`（`raw/build/ev_v9.log`）。

## Analysis and conclusion

HLS 時間隨 lane 數增加得比線性快很多：

| lanes | HLS 時間 |
|---|---|
| 4（v8） | 約 35 分 |
| 8（v10） | 約 3 小時 50 分 |
| 16（v9） | > 8 小時（停止） |

可能原因：component 裡每個事件用 `if (L == k)` 選擇要寫哪一條 lane 的 stream，
16 個分支在同一個迴圈裡，HLS 要分析所有 stream 之間的順序關係。

## Next action

- 改寫事件分配（例如事件先分到每條 lane 自己的 stream，用固定次序輪流，不用 `if` 鏈），
  或把多條 lane 包成一個 task 陣列。
- 或改用影像分區（slab）架構，不需要複製影像，也不需要很多獨立的 lane task。
