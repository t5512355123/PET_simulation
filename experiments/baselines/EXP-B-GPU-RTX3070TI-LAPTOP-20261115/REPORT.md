# EXP-B-GPU-RTX3070TI-LAPTOP-20261115 — GPU 基準

## Verdict

量測（不是 PASS/FAIL 實驗）。

## Conditions

- 筆電 RTX 3070 Ti Laptop GPU，驅動 616.56，閒置功耗 13.8 W。
  （.26 與 trader3 的 GPU 當時都在忙，所以用筆電。）
- conda env `pp`：libparallelproj 2.0.7（cuda130）、cupy。
- 資料和 CPU 基準相同：Esser2 2,503,978 個事件、358,927,391 步（`source/gpu_bench.py`）。
- 前投影、反投影各重複 50 次取平均，再連續執行 20 秒量功耗；
  `nvidia-smi` 每 200 ms 記錄一次（`raw/observe/nvidia_smi_power.csv`）。

## Runtime observations

| 項目 | 結果 |
|---|---|
| 前投影 | 56.4 ms → 6359 M/s |
| 反投影 | 213.3 ms → 1682 M/s |
| 前＋反（一對） | 1330 M/s → 前、反分開計 **2660 M 樣本/秒** |
| 功耗（使用率 ≥ 90% 的 155 筆平均） | 95.1 W（最大 112.4 W），SM 時脈 1635 MHz |
| 能量 | **36 nJ/樣本** |

## Analysis

- GPU 的反投影比前投影慢 3.8 倍（atomic 加法），FPGA 的反投影沒有這個問題。
- 功耗只算 GPU 板子；FPGA 是 Quartus 的晶片估計值。兩者的量測範圍不完全相同。
- 這是筆電 GPU。桌上型或資料中心 GPU 會更快，但功耗也更高。
