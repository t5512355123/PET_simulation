# EXP-S3-PARITY-BANK-LAYOUT-20261115 — 強制 8 個獨立 bank

## Verdict

`PASS`

## Build and source provenance

- HLS 原始碼：`source/ev_v8.cpp`，由 `patch_banks.py` 修改 `lanes_part.cpp`：
  `hls_numbanks(8) hls_bankwidth(4) hls_singlepump`，陣列改成 `[BANKSZ][NB]`。
- 唯一改變的變數：記憶體的 bank 配置。其他和 `EXP-S3-FOUR-LANE-ROUNDROBIN-20261115` 相同。
- 125 MHz，Fmax **166.7 MHz**。資源：ALM 52,175（6%）、RAM 2,297（20%）、DSP 193。
- 測試資料和上一個實驗相同（`raw/testdata/`）；`board7_1/`、`board7_short/` 是對照組。

## Runtime observations（`analysis/compare_board.txt`）

| 項目 | 結果 |
|---|---|
| 反投影 | 最大誤差 / 最大值 = 8.3×10⁻⁸ |
| 重複 2000 次 | 1,713 ms → **424.7 M 樣本/秒** |
| 每條 lane | 1.17 cycles/樣本（含 JTAG 啟動與事件分配時間） |
| 功耗（quartus_pow 估計） | 8.16 W → 19 nJ/樣本 |

## Analysis and conclusion

- 每條 lane 從 2.14 降到 1.17 cycles/樣本，ALM 從 32% 降到 6%。
- RAM 用了 20%，大多是 stream 緩衝和影像副本；Fmax 166.7 MHz 表示可以再提高頻率。
- 和 GPU（`EXP-B-GPU-RTX3070TI-LAPTOP-20261115`，36 nJ/樣本）比，能量省約 1.9 倍，但速度只有 GPU 的 1/6。

## Next action

Step 4：8 與 16 條 lane，150 MHz。
