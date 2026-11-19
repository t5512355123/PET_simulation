# EXP-S17-R2-RESIDENT-TOF-PROJECTOR-20261119 — R2 投影器（40 lane × 4 set，TOF，兩個主軸副本常駐片上）DE10-Pro 實測

## Verdict

`PASS`（投影器部分）；`NOT YET`（整個 5 倍目標）：
- 40-lane R2 投影器在 DE10-Pro 上以 150 MHz 跑通（Fmax 162 MHz），使用 ALM 71%、RAM 86%、DSP 84%。
- 結果和軟體模型一致：forward 比值相對誤差最大 2.7×10⁻⁷，back projection（兩個副本，297 萬個 voxel）誤差 6.4×10⁻⁸（相對最大值）。軟體模型和 parallelproj（GPU）在 FOV 內的誤差為 forward 1.0×10⁻⁴、back 8.1×10⁻⁵。
- 速度：**每個事件 1.026 個 cycle**（2010 個 token 用 2063 cycles，等於最忙 lane 的 item 數），forward 和 back 相同。
  一個 subset（D690，M = 8，約 38.4 萬事件）fwd + back = **5.25 ms**；GPU 同樣工作是 9.8 + 35.1 = 44.9 ms → **8.6 倍**。
- 還沒做：voxel update、RDP、前處理器、事件從 DDR 串流、晶片內流程控制。所以還沒有「從事件到門檻」的實測時間。

## 1. 架構（`source/slab7.cpp`）

- 平面交錯分給 lane：plane p → lane p % 40，lane 內 local index t = p / 40；每個 lane 有 4 個 bank set（set = t % 4），
  同一個事件一個 cycle 最多做 4 個相鄰的 local step。
- 兩個主軸副本（x 平面、y 平面）都常駐片上，只存 FOV 內的 row。每個 voxel 一個 fp32 字：forward 時放影像，
  back 時放累加器（中間 K_CLEAR）。
- TOF 權重：|d| < 5σ（175.05 mm）的 1024 格表 + 線性內插；截斷不加 W/2（和 parallelproj 一致）。
- exp 只做計數；eng 算步進（u、v、d）。eng 記憶體 load→store 距離 11 cycles → host 排程 HAZ = 16（每 4000 事件約 4 個 NOP）。
- 第一次建置 RAM 不夠（14,191 > 11,721）：用 `hls_force_pow2_depth(0)` 去掉 2 的冪次填充、READ 改走 padd 鏈、
  不用 struct 型 slave memory、MAXEV 2048 → 10,087 blocks。

## 2. 實測（`raw/board7_rep20000.log`、`analysis/compare7_rep20000.txt`）

| 項目 | 值 |
|---|---|
| 事件 | 2,000 個 D690 事件（+ 10 個 hazard NOP） |
| forward s 相對誤差（板子 vs 模型） | 最大 2.7×10⁻⁷，1404/2010 bit 完全相同 |
| back projection（兩個副本 2,970,024 voxel） | 誤差 / 最大值 6.4×10⁻⁸ |
| 時間（REP 20000） | fwd 275 ms、back 275 ms → 每遍 13.8 µs = 2063 cycles → 1.026 cycles/事件 |
| 一個 subset（38.4 萬事件）fwd + back | 5.25 ms（GPU 44.9 ms） |

注意：system-console 21.3 的 `--script` 參數在 snoopy 上沒有執行腳本（連 `puts` 都沒有輸出），
改成從 stdin 餵 `set argv [...]; source board7.tcl`。

## 3. 和 5 倍目標的距離（`source/budget_r2.py`）

GPU psv 在第 40 次更新達門檻（3 次 full gradient）→ 61 次 subset 投影 + 40 次 voxel update + 24 次 full-gradient 讀出。

- 投影：61 × 5.25 ms = 320 ms（實測速率）。
- voxel update：SVRG 表和前處理器用 fp16 仍在第 40 次更新達門檻（`analysis/d690_psv_hwq_both.json`）→ 每 voxel 20 B DDR。
  4 條 DDR4 合計 20 GB/s 時每次 1.48 ms；讀出 0.74 ms。
- 合計約 **397 ms → 6.0 倍**；若 DDR 只有 10 GB/s 約 474 ms（5.04 倍，幾乎沒有餘裕）。
- RDP 梯度與前處理器需要和投影同時跑（只依賴 x）。

## 4. 其他

- D690 online Br（`source/online_tof.py`）：ŷ = 0 的事件要給 0 權重（原本產生 NaN）。修正後擷取結束後第 7 次更新達門檻
  （擷取後 1.75 個投影 epoch）。

## 5. 下一步（EXP-S18）

1. eng 加每 lane 的 voxel 讀寫通道（不走 token 鏈），以 40×40 對角順序讀 ACC、寫新影像。
2. voxel update 單元（SVRG 組合、前處理器、clip）+ 4 條 DDR4。
3. RDP 梯度單元（和投影同時跑）；前處理器（高斯 + RDP Hessian 對角）。
4. 事件從 DDR 以 1 事件/cycle 串流；每事件 F 暫存在 DDR。
5. 晶片內流程控制器，跑完整 40 次更新並量從事件到門檻的時間。
