# EXP-S14-DDR4A-BRINGUP-20261118 — DE10-Pro DDR4A 啟用（EMIF + 校正 + 讀寫驗證）

## Verdict

`PASS`（DDR4 可用）：EMIF 校正通過，4 個位址區域讀寫驗證全部正確。
頻寬只有約 2 GB/s，原因是 Platform Designer 預設的跨時脈轉接器（handshake 型）；改用 FIFO 型後在 EXP-S15 量到 5.0 GB/s。

## Objective

為 slab 的「每條 lane 平行載入」準備外部記憶體：確認 DE10-Pro 上的 DDR4 SO-DIMM 可以用、腳位正確、資料正確。

## Conditions

- 板子：snoopy 上的 DE10-Pro（1SX280HU2F50E1VG），4 個 SO-DIMM 插槽都插滿（使用者確認），只用 DDR4A。
- EMIF 參數和腳位：來自使用者提供的 Terasic System CD（`D:\DE10-Pro_GH2E2-165_v1.1.1_SystemCD`，
  `Demonstrations/RTL_DDR4_x4_ECC/16GB`）。CD 是 GX 1650 版本，封裝 F50 相同；CLK/RESET/LED 腳位和我們的專案一致。
  - DDR4-2400、72 位元（含 ECC）、SO-DIMM 1 rank、row 15 bits、四分之一速率（使用者時脈 300 MHz）、參考時脈 300 MHz（Si5340 預設輸出）。
  - 從 CD 的 `DDR4A.ip` 取出 588 個使用者參數，去掉清單型的 ODT 表（21.3 格式不同），在 Platform Designer 用 `altera_emif_s10` 建立（`source/emif_params.tcl`）。
- 系統：JTAG master + HLS `ddrbw`（512 位元 Avalon-MM host，150 MHz）→ EMIF。頂層把 Si5340A0/A1 的 OE_n 拉低、RST_n 拉高（同 CD 範例）。
- `source/ddr_sys.tcl` 最後兩行（FIFO 跨時脈）是之後為 EXP-S15 加的；這次建置的系統是 `source/ddr_sys_v1.qsys`。
- 建置：Fmax 234.9 MHz（150 MHz 時鐘），EMIF 使用者時脈 335 MHz（300 MHz 需求）；ALM 2%。

## Build history

1. `emif_s10` 不是模組名稱；`altera_emif` 不支援 Stratix 10；正確名稱是 `altera_emif_s10`。
2. 第一次編譯 22 秒失敗：建置腳本重寫 qsf 時把 Platform Designer 加入的 IP_FILE 清掉。改成先寫 qsf 再跑 Platform Designer。

## Runtime observations（`raw/observe/ddr_test.log`）

| 測試 | 結果 |
|---|---|
| 寫入 65,536 個 512 位元字再讀回比對，位址 0、256 MB、2 GB、3.75 GB | 4 個區域都 0 錯 ✔ |
| 用錯誤的種子比對（應全錯） | 1,048,576 個 32 位元字不符（全部）✔ |
| 寫入頻寬（64 MB 與 1 GB 相減） | 2.05 GB/s |
| 讀取頻寬 | 1.90 GB/s |

## Analysis and conclusion

- DDR4A 可以用；腳位和參數沿用 CD 是正確的。
- 2 GB/s 遠低於 150 MHz × 64 B = 9.6 GB/s。HLS 端是 burst 存取；瓶頸在 Platform Designer 自動插入的 handshake 跨時脈轉接器。
  EXP-S15 改成 `qsys_mm.clockCrossingAdapter = FIFO`。

## Next action

- EXP-S15：slab 加上 DDR 寬資料鏈，平行載入影像、讀出累加器。
