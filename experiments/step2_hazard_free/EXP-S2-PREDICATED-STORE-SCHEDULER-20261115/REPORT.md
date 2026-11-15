# EXP-S2-PREDICATED-STORE-SCHEDULER-20261115 — 無衝突反投影

## Verdict

`PASS`

## Build and source provenance

- HLS 原始碼：`source/ev_v5.cpp`。
  - producer task 把事件展開成步，經 stream 送給 flat engine task，事件之間連續執行。
  - 反投影只在有效 bank 寫入（predicated store），不再寫「+0」。
  - 主機端貪婪排序：任兩個事件在 HAZ = 210 步內不會碰到同一個 voxel；排不進去時插入空事件（bubble）。
- 125 MHz，Fmax 131.2 MHz。資源：ALM 73,134（8%）、RAM 659（6%）、DSP 48。
- 測試資料：3500 個事件、205,619 步，bubble 0。

## Runtime observations（`analysis/compare_board.txt`）

| 項目 | 結果 |
|---|---|
| 前投影比值 s | 最大相對誤差 1.2×10⁻⁷ |
| 反投影 | 最大誤差 / 最大值 = **9.3×10⁻⁸** |
| 重複 2000 次 | 12,296 ms → 1.87 cycles/樣本，66.9 M 樣本/秒 |
| 功耗（quartus_pow 估計） | 7.61 W |

## Analysis and conclusion

反投影錯誤已修好，速度比 Step 1 快 1.8 倍。
理想值是 1 cycle/樣本，剩下的差距在 Step 3 處理。

## Next action

同一個引擎複製成多條 lane：`EXP-S3-FOUR-LANE-ROUNDROBIN-20261115`。
