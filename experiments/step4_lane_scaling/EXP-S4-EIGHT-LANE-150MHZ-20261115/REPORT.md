# EXP-S4-EIGHT-LANE-150MHZ-20261115 — 8 條 lane，150 MHz

## Verdict

`PASS`

## Build and source provenance

- HLS 原始碼 `source/ev_v10.cpp`：和 v9 相同，只把 `LANES` 從 16 改成 8。
- HLS（i++ 21.3）約 3 小時 50 分（v8 的 4 lanes 只要 35 分）；Quartus 43 分。
- Fmax **180.0 MHz**（Slow 100C 模型），150 MHz 時序通過。
- 資源：ALM 99,844（11%）、RAM 4,489（38%）、DSP 387（7%）。
- SOF SHA-256：`raw/build/SOF_SHA256.txt`。

## Programming sequence and result

`quartus_pgm -c 1 -m jtag -o "p;bsrem_top.sof@1"` 成功（`raw/build/pgm.log`），
接著執行 System Console `board_test.tcl`，rep 2000（`raw/observe/sc_10_8.log`）。

## Runtime observations（`analysis/compare_board.txt`）

| 項目 | 結果 | 門檻 |
|---|---|---|
| 前投影比值 s | 最大相對誤差 1.2×10⁻⁷ | ≤ 10⁻⁶ ✔ |
| 反投影 | 最大誤差 / 最大值 = 1.8×10⁻⁷ | ≤ 10⁻⁶ ✔ |
| 重複 2000 次 | 850 ms → **1106 M 樣本/秒** | > 850 M ✔ |
| 每條 lane | 1.072 cycles/樣本 | — |
| 功耗（quartus_pow 估計） | 11.10 W（動態 4.96 W、靜態 6.13 W） | — |
| 能量 | **10.0 nJ/樣本** | — |

## Analysis and conclusion

| | 速度 | 能量 | 
|---|---|---|
| v8（4 lanes，125 MHz） | 424.7 M/s | 19.2 nJ |
| **v10（8 lanes，150 MHz）** | **1106 M/s** | **10.0 nJ** |
| GPU RTX 3070 Ti Laptop | 2660 M/s | 36 nJ |

- 速度是 v8 的 2.6 倍，lane 數加倍、頻率提高 1.2 倍，每條 lane 的效率也稍好（1.17 → 1.07）。
- 能量比筆電 GPU 低 3.6 倍；速度是 GPU 的 0.42 倍。
- 靜態功耗 6.1 W 佔一半以上。lane 越多，每個樣本分到的靜態功耗越少。
- 影像仍是 64×64×32，每條 lane 一份影像副本；RAM 已用 38%，16 lanes 約需 76%。

## Next action

- 16 lanes 的 HLS 跑不完（`EXP-S4-SIXTEEN-LANE-150MHZ-20261115`）。
  要再擴充，需要先讓 HLS 的編譯時間不隨 lane 數暴增，
  或改成影像分區（slab）架構，讓所有 lane 共用一份影像。
- Fmax 有 180 MHz，可以試 175 MHz。
