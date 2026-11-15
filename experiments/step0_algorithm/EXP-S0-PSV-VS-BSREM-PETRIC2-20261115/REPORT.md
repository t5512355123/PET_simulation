# EXP-S0-PSV-VS-BSREM-PETRIC2-20261115 — 硬體該做哪個演算法

## Verdict

`PASS`：硬體要實作 psv（SVRG），不是 BSREM。

## Build and source provenance

- 主機：.26（`~/claude_svrg_prof/`），conda env `petric_cpu`（STIR 6.5、parallelproj CPU、numba）。
- `source/make_lors_stir.py`：用 STIR `get_LOR` 取得每個 bin 的 LOR，順序和 `ProjData.to_array()` 相同。
- `source/algo_study2.py`：psv、PETRIC BSREM、online BSREM（psv 預條件子、無變異數縮減）。
- 前向模型和 SIRF 相同：ŷ = m·(c·Ax + a)，c = 1/橫向 voxel 大小。

## Runtime observations

PETRIC2 三組測試資料，第一次達標的 epoch（自己的收斂參考 / 官方參考）：

| 演算法 | Esser2 | Hoffman2 | ACR2 |
|---|---|---|---|
| psv | 12.25 / 未達標（官方 RMSE 停在 1.25%） | 10.5 / 10.75 | 5.29 / 4.93 |
| PETRIC BSREM，40 epoch | 未達標（RMSE 4.9%） | 未達標（3.7%） | 未達標（8.9%） |
| online BSREM，40 epoch | 未達標 | 未達標（1.38%） | 未達標（1.92%） |

門檻：全物件 RMSE ≤ 1%、背景 RMSE ≤ 1%、VOI AEM ≤ 0.5%，連續 10 次更新。

## Analysis and conclusion

達標的關鍵是變異數縮減（SVRG），所以 FPGA 要做 psv 需要的運算：
事件式前投影＋反投影、子集梯度表、RDP 先驗。前兩者是本分支 Step 1–4 的內容。

## Evidence

- `raw/observe/*_study.json`：每次更新的指標。
- `raw/observe/*.log`：執行紀錄。
