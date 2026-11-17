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
| 8 冠軍實跑 | `EXP-S8-PSV-LOCAL-RUN-PROFILE-20261116` | PASS（有條件） | 冠軍 psv 本機實跑：比賽計時 152.9 s 到門檻（去掉最後 2 平面）；likelihood 梯度 76%（CPU 逐 bin 31%、前投影 30%、反投影 11%）、sensitivity 15% |
| 9 list-mode psv | `EXP-S9-LISTMODE-PSV-GPU-20261117` | PASS | 依時間切子集、s/M：98 次更新 / 12.25 epoch（和原版相同）；3070 Ti 8.62 s、約 745 J |
| 10 online | `EXP-S10-ONLINE-PSV-LATENCY-20261117` | PASS | 成長資料 psv + 步長重新開始：最後事件後 1.5–4.6 epoch（原版 18.4） |
| 11 voxel 單元 | `EXP-S11-PSV-VOXEL-UNIT-DE10PRO-20261117` | PASS | RDP stencil + SVRG + 更新：1.0 cycle/voxel、165 MHz、8.6 W；整機比較：能量少 3.7 倍，時間要 32-lane slab 才贏 |
| 12 slab 硬體 | `EXP-S12-SLAB-8LANE-NOFIFO-150MHZ-20261117` | FAIL | 結果正確；2.46 cycles/iteration（部分和鏈沒有 FIFO，所有 lane 被鎖成同步） |
| 12 slab 硬體 | `EXP-S12-SLAB-8-32LANE-150MHZ-20261117` | PASS | 1.00 cycle/iteration；32 lanes 3.54 G/s、14.0 W、4.0 nJ/樣本；加 voxel 單元到門檻 6.4 s / 106 J（GPU 8.6 s / 745 J） |
| 13 Esser2 實際大小 | `EXP-S13-SLAB32-ESSER2-REALSIZE-20261117` | PASS（投影）/ FAIL（整機時間） | 實際影像 4 次 pass、真實事件：3.69 G/s、4.7 nJ/樣本、對 GPU 差 3×10⁻⁵；串列載入影像使整機 16.2 s（GPU 8.6 s），平行載入模型 6.5 s；更正 S12 比較 |
| 基準 | `EXP-B-CPU-XEON8559C-PARALLELPROJ-20261115` | 量測 | 1 執行緒 44 M/s；24 執行緒約 500 M/s |
| 基準 | `EXP-B-GPU-RTX3070TI-LAPTOP-20261115` | 量測 | 2660 M/s；約 95 W；36 nJ/樣本 |

Step 1–3 的紀錄是 2026-11-15 當天實驗結束後整理的回溯紀錄；
原始紀錄（System Console 輸出、Quartus 摘要、板上讀回資料）都是當時的檔案，未修改。
