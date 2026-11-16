# Milestones

| Step | 實驗 | 判定 | 重點數字 |
|---|---|---|---|
| 0 演算法 | `EXP-S0-PSV-VS-BSREM-PETRIC2-20261115` | PASS | psv 5.3–12.3 epoch 達標；BSREM 40 epoch 未達標 |
| 1 單一 lane | `EXP-S1-FIRST-LANE-200MHZ-20261115` | FAIL | 200 MHz 時序不過（Fmax 141 MHz） |
| 1 單一 lane | `EXP-S1-CSR-LANE-125MHZ-20261115` | FAIL | 前投影正確；反投影 RMW 衝突，誤差 1.2%；3.33 cycles/樣本 |
| 2 無衝突反投影 | `EXP-S2-PREDICATED-STORE-SCHEDULER-20261115` | PASS | 誤差 9×10⁻⁸；1.87 cycles/樣本；66.9 M/s；7.61 W |
| 3 多 lane | `EXP-S3-FOUR-LANE-ROUNDROBIN-20261115` | PASS | 4 lanes 231.6 M/s；每 lane 2.14 cycles/樣本（bank 衝突） |
| 3 多 lane | `EXP-S3-PARITY-BANK-LAYOUT-20261115` | PASS | 424.7 M/s；每 lane 1.17 cycles/樣本；Fmax 166.7 MHz；8.16 W |
| 4 lane 擴充 | `EXP-S4-EIGHT-LANE-150MHZ-20261115` | PASS | 1106 M/s；Fmax 180 MHz；RAM 38%；11.1 W → 10.0 nJ/樣本 |
| 4 lane 擴充 | `EXP-S4-SIXTEEN-LANE-150MHZ-20261115` | INCONCLUSIVE | HLS 8 小時未完成，停止 |
| 5 slab 分區 | `EXP-S5-SLAB-PARTITION-MODEL-20261116` | PASS（模型） | 16 lanes 效率 0.76、32 lanes 0.65；32 lanes 約 3.1 G/s（150 MHz），實際影像放得下 |
| 6 list-mode 資料 | `EXP-S6-SINOGRAM-TO-LISTMODE-PETRIC2-20261116` | PASS | Esser2/Hoffman2/ACR2 重新直方圖化完全相同；梯度差 ≤ 5.5×10⁻⁶ |
| 7 冠軍瓶頸 | `EXP-S7-PSV-BOTTLENECK-PROFILE-20261116` | PASS（量測） | SIRF 放法 170–335 ms/更新 → GPU 事件式 46 ms；剩下 72% 是 GPU 反投影 atomic |
| 基準 | `EXP-B-CPU-XEON8559C-PARALLELPROJ-20261115` | 量測 | 1 執行緒 44 M/s；24 執行緒約 500 M/s |
| 基準 | `EXP-B-GPU-RTX3070TI-LAPTOP-20261115` | 量測 | 2660 M/s；約 95 W；36 nJ/樣本 |

Step 1–3 的紀錄是 2026-11-15 當天實驗結束後整理的回溯紀錄；
原始紀錄（System Console 輸出、Quartus 摘要、板上讀回資料）都是當時的檔案，未修改。
