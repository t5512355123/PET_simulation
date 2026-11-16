# EXP-S7-PSV-BOTTLENECK-PROFILE-20261116 — PETRIC2 冠軍（Speedy psv）的瓶頸

## Verdict

`PASS`（量測完成）。結論：時間主要花在資料放在 CPU 記憶體造成的複製與 CPU 運算，
其次是 dense 前投影；資料搬到裝置端並改成事件式以後，剩下的瓶頸是 GPU 反投影的 atomic 加法。

## Method

- psv 原始程式需要 SIRF。本機沒有 Docker/WSL，conda-forge 也沒有 SIRF，所以不能直接執行。
- 改成依原始碼重現它的資料流程，逐步計時（`source/psv_flow_profile.py`）：
  - psv `main.py`：`sirf.contrib.partitioner.data_partition`（STIR 子集目標函數）、
    `CudaRelativeDifferencePrior`、SIRF `ImageData`（主記憶體）上的 SVRG 運算。
  - STIR 6.5 `ForwardProjectorByBinParallelproj.h`：`set_input()` 把投影結果寫進主記憶體的
    `ProjDataInMemory`；GPU 上只放 LOR 端點（`ParallelprojHelper::xstart/xend`，CuVec）。
  - PETRIC2 `petric.py`：計時在 `get_data()`（讀檔）之後才 `reset()`，所以讀檔和 list-mode → sinogram 不計時。
- 資料：PETRIC2 NeuroLF_Esser2，psv 用 8 個子集（每個 16 views，6,635,520 bins，其中非零約 313,000）。
- GPU：RTX 3070 Ti Laptop（同時有別的程式在用 GPU 約 20–35%，GPU kernel 時間有 ±2 倍的波動）。
- 三種資料放法：
  - A：SIRF/STIR 放法（冠軍實際的做法）
  - B：所有陣列都在 GPU，仍用 dense sinogram
  - C：所有陣列都在 GPU，只算非零 bin（梯度完全相同）

## Results（每次子集更新，ms；`raw/observe/psv_flow_profile_esser2.json`）

| 步驟 | A：SIRF/STIR | B：GPU dense | C：GPU 事件式 |
|---|---|---|---|
| 前投影 | 82.1（B 同一運算 38.7） | 38.7 | **10.1** |
| 反投影 | 34.4 | 17.5 | 33.0 |
| RDP 梯度（GPU） | 2.4 | 0.9 | 0.8 |
| Poisson 比值 m·y/ŷ | 126.3（CPU 單執行緒）/ 5.7（多執行緒） | 2.6 | 0.6 |
| 影像 SVRG 運算 | 44.2（numpy）/ 3.3（多執行緒） | 1.5 | 1.5 |
| host ↔ GPU 複製（6 次） | 45.1 | 0 | 0 |
| **合計** | **335**（CPU 單執行緒）/ 約 170（多執行緒） | **61** | **46** |

另外：
- setup 時算 8 個子集的 sensitivity（每個 = m 的 dense 反投影）：2.16 s。這段有計時。
- `raw/observe/check_back_output.txt`：parallelproj 反投影會跳過值為 0 的 LOR。
  同一子集：全部值為 1 → 241.9 ms；y = 0 的位置值為 0 → 16.8 ms；只留非零 LOR（緊密排列）→ 33.6 ms；
  隨機順序 → 41.0 ms。所以 dense 反投影本來就只做非零 LOR 的工作，緊密排列反而因為 atomic 衝突比較慢。

## Analysis

1. **A → B（資料留在裝置端）快 2.8–5.5 倍。** 冠軍程式的時間主要是：
   - 6 次 host↔GPU 複製（45 ms）
   - CPU 上對整個子集 6.6 M bins 算比值（大部分是 0）
   - CPU 上的影像運算
2. **B → C（事件式）前投影快 3.8 倍**（dense 前投影對 y = 0 的 bin 也要算）。
3. **C 剩下的瓶頸是反投影：33 / 46 ms = 72%。** GPU 的反投影要用 atomic 加法，事件越集中越慢。
   這是 FPGA 的優勢：我們的 FPGA 反投影用 bank 配置和無衝突排序，速度和前投影一樣
   （`EXP-S3-PARITY-BANK-LAYOUT`、`EXP-S4-EIGHT-LANE-150MHZ`）。

## 硬體化要改的地方

| psv 現在的做法 | 問題 | FPGA 版要改成 |
|---|---|---|
| sinogram 和影像在 CPU，每次投影複製 | 45 ms/更新的複製 + CPU 運算 | 事件、影像、梯度表都放在板上（片上記憶體 + DDR），host 只送一次事件 |
| dense 前投影（所有 bin） | y = 0 的 bin 白算，佔前投影 75% | 事件式：只處理事件（list-mode 天生如此） |
| GPU 反投影用 atomic | C 的 72% 時間 | FPGA 反投影用 bank + 無衝突排序（已驗證） |
| 子集用 view 切（staggered） | list-mode 沒有 view 順序 | 子集改用事件時間或事件編號切；要重新驗證收斂（下一個實驗） |
| 每個子集各算一次 sensitivity（2.16 s，有計時） | dense 反投影 m，佔 setup 大部分 | 時間切的子集：每個子集的 sensitivity = 全部 sensitivity / M，只算一次；可在掃描期間預先算 |
| SVRG 梯度表：M 張子集梯度影像 + 總和（Esser2：9 × 10 MB；ACR2：15 × 41 MB） | 片上放不下 | 放 DDR；每次更新只讀寫 2–3 張影像，或用 fp16 存 |
| RDP 梯度、對角 Hessian（3×3×3 鄰域）、高斯濾波 | 鄰域運算 | 串流 stencil 單元（line buffer），GPU 上只佔 2%，不是瓶頸 |
| 步長 3.5/(1+0.01t)、max(0) | — | 純量與逐點運算，直接做 |

## Limits

- 不是直接執行冠軍程式；STIR 內部（逐 viewgram 的迴圈、正規化套用）和 SIRF 的 Python 開銷沒有量到，
  實際的 A 應該比表中更慢。排行榜在 A100 上 87 s，粗估 psv 約 144 次梯度計算 × 0.17–0.34 s = 24–49 s，
  剩下的時間應該就是這些沒量到的開銷。
- GPU 同時被其他程式使用，kernel 時間有波動；表中 B、C 的 GPU kernel 時間比較可靠。

## Next action

1. list-mode 版 psv（時間切子集），確認能達到 PETRIC2 門檻。
2. FPGA：SVRG 梯度表放 DDR 的頻寬估計；RDP stencil 單元。
