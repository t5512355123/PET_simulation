# EXP-S1-CSR-LANE-125MHZ-20261115 — 單一 lane，125 MHz，板上測試

## Verdict

`FAIL`：前投影正確，反投影有讀寫衝突（RMW hazard）。

## Build and source provenance

- HLS 原始碼：`source/ev_csr3.cpp`（和上一個實驗相同），PLL 改成 125 MHz。
- Fmax 133.0 MHz，時序通過。
- 測試資料：4096 個事件、240,561 個 Joseph 步、131,072 voxels（`raw/testdata/`）。

## Programming sequence and result

`quartus_pgm -c 1 -m jtag -o "p;bsrem_top.sof@1"`，接著用 System Console 執行
`board_test.tcl`（不加 `-cli`）。

## Runtime observations（`analysis/compare_board.txt`）

| 項目 | 結果 |
|---|---|
| 前投影比值 s | 最大相對誤差 1.2×10⁻⁷ |
| 反投影 | 最大誤差 / 最大值 = **1.2×10⁻²** |
| 重複 2000 次 | 25,638 ms → 3.33 cycles/樣本，37.5 M 樣本/秒，每事件多 391 cycles |

## Analysis and conclusion

兩個原因：

1. 累加器只有 2 份，但管線深度約 216 cycles，同一個 voxel 在管線內被寫兩次時會漏加。
2. 超出範圍的位址被夾到邊界，再寫入「+0」，也會和真正的寫入衝突。

事件之間也沒有重疊，每個事件多花約 274 cycles。

## Next action

`EXP-S2-PREDICATED-STORE-SCHEDULER-20261115`：只在有效 bank 寫入，並在主機端排序事件，避免衝突。
