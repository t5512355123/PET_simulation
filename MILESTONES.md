# Milestones

| Step | 實驗 | 判定 | 重點數字 |
|---|---|---|---|
| 0 演算法 | `EXP-S0-PSV-VS-BSREM-PETRIC2-20261115` | PASS | psv 5.3–12.3 epoch 達標；BSREM 40 epoch 未達標 |
| 1 單一 lane | `EXP-S1-FIRST-LANE-200MHZ-20261115` | FAIL | 200 MHz 時序不過（Fmax 141 MHz） |
| 1 單一 lane | `EXP-S1-CSR-LANE-125MHZ-20261115` | FAIL | 前投影正確；反投影 RMW 衝突，誤差 1.2%；3.33 cycles/樣本 |
| 2 無衝突反投影 | `EXP-S2-PREDICATED-STORE-SCHEDULER-20261115` | PASS | 誤差 9×10⁻⁸；1.87 cycles/樣本；66.9 M/s；7.61 W |
| 3 多 lane | `EXP-S3-FOUR-LANE-ROUNDROBIN-20261115` | PASS | 4 lanes 231.6 M/s；每 lane 2.14 cycles/樣本（bank 衝突） |
| 3 多 lane | `EXP-S3-PARITY-BANK-LAYOUT-20261115` | PASS | 424.7 M/s；每 lane 1.17 cycles/樣本；Fmax 166.7 MHz；8.16 W |
| 4 lane 擴充 | `EXP-S4-EIGHT-LANE-150MHZ-20261115` | 進行中 | — |
| 4 lane 擴充 | `EXP-S4-SIXTEEN-LANE-150MHZ-20261115` | 進行中 | — |
| 基準 | `EXP-B-CPU-XEON8559C-PARALLELPROJ-20261115` | 量測 | 1 執行緒 44 M/s；24 執行緒約 500 M/s |
| 基準 | `EXP-B-GPU-RTX3070TI-LAPTOP-20261115` | 量測 | 2660 M/s；約 95 W；36 nJ/樣本 |

Step 1–3 的紀錄是 2026-11-15 當天實驗結束後整理的回溯紀錄；
原始紀錄（System Console 輸出、Quartus 摘要、板上讀回資料）都是當時的檔案，未修改。
