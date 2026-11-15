# EXP-S3-FOUR-LANE-ROUNDROBIN-20261115 — 4 條 lane，事件輪流分配

## Verdict

`PASS`（結果正確、速度隨 lane 數線性增加；每條 lane 的效率沒有改善）

## Build and source provenance

- HLS 原始碼：`source/ev_v7.cpp`，由 `make_v6.py` / `make_v7.py` 從 `ev_v5.cpp` 和 `lanes_part.cpp` 產生。
- component 把事件 e 分給 lane e % 4；每條 lane 有自己的 producer task、engine task、影像和累加器。
- 125 MHz，Fmax 133.6 MHz。資源：ALM 295,901（32%）、RAM 2,369（20%）、DSP 193。
- 測試資料：3804 個事件（排序後）、182,255 步；最忙的 lane 45,836 步。

## Runtime observations（`analysis/compare_board.txt`）

| 項目 | 結果 |
|---|---|
| 反投影 | 最大誤差 / 最大值 = 8.3×10⁻⁸ |
| 重複 2000 次 | 3,141 ms → 231.6 M 樣本/秒 |
| 每條 lane | 2.14 cycles/樣本 |

`raw/observe/sc_1.log`、`sc_short.log` 是 1 條 lane 和短事件的對照測試。

## Analysis and conclusion

每條 lane 仍約 2 cycles/樣本。原因是 HLS 把 IMG/ACC 重新打包成寬字組，
8 個 bank 的讀寫互相衝突。

## Next action

`EXP-S3-PARITY-BANK-LAYOUT-20261115`：強制 8 個獨立 bank。
