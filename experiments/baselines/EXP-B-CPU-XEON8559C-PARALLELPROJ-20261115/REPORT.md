# EXP-B-CPU-XEON8559C-PARALLELPROJ-20261115 — CPU 基準

## Verdict

量測（不是 PASS/FAIL 實驗）。

## Conditions

- 主機 .26，Xeon 8559C，conda env `petric_cpu`，parallelproj（OpenMP）。
- 資料：PETRIC2 NeuroLF Esser2，2,503,978 個非零事件 LOR，參考影像，
  共 358,927,391 個 Joseph 步（`source/cpu_bench.py`）。

## Runtime observations

（輸出當時印在終端機，沒有存成檔案；下表是當時的輸出。）

| 執行緒 | 前投影 | 反投影 | 前＋反（一對） | 前、反分開計 |
|---|---|---|---|---|
| 1 | 4.860 s（74 M/s） | 11.562 s（31 M/s） | 22 M/s | 44 M 樣本/秒 |
| 8 | 0.778 s（461 M/s） | 2.354 s（152 M/s） | 115 M/s | 229 M 樣本/秒 |
| 24 | 0.332 s（1082 M/s） | 1.111 s（323 M/s） | 249 M/s | 497 M 樣本/秒 |

## Analysis

反投影比前投影慢約 3 倍（atomic 加法）。
