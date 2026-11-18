# EXP-S15-SLAB32-DDR4-WIDECHAIN-20261118 — slab 32 + DDR4 寬資料鏈：影像平行載入、累加器平行讀出

## Verdict

`PASS`：影像從 DDR4 載入、累加器寫回 DDR4，結果和 EXP-S13 完全相同（對 GPU parallelproj：s 3.0×10⁻⁵、反投影 7.9×10⁻⁵）。
每個子集的搬移從 67.7 ms（EXP-S13 串列）降到 **9.86 ms（實測）**。
到 PETRIC 門檻：**FPGA 7.67 s / 236 J，筆電 GPU 8.62 s / 745 J**——用板上實測的零件，時間和能量都贏。

## Objective

EXP-S13 的瓶頸是每次 psv 更新把影像載入 lanes、把累加器讀出（經 token 鏈每 cycle 一個 voxel）。
這次讓影像和累加器經 DDR4 和寬資料鏈搬移，量實際時間。

## Design（`source/slab5.cpp`，事件路徑和 EXP-S13 的 slab4 相同）

- 寬資料鏈：`slab_ld`（DDR → 512 位元字，每字 16 個 voxel = 4 組 2×2）→ 32 個 `slab_wp`（每條 lane 一個）→ `slab_st`（→ DDR）。
- `slab_wp`：別條 lane 的字一圈就轉送；自己的字拆成 4 組送給 `slab_eng`（每組一圈，4 個 bank 同一位址），
  讀出時收回 4 組結果再轉送。每個字都送到 storer，storer 依 (lane, slot) 算 DDR 位址，所以字的順序可以改變。
- `slab_eng`：每圈處理一個事件 item（優先）或一組寬資料；沒有額外狀態。
- `slab_dma`：主機經 JTAG ↔ 片上 64 KB ↔ DDR（只在測試時把影像放進 DDR、把累加器拿回來）。
- 三個 512 位元 host 接 DDR4A EMIF；跨時脈轉接器設為 FIFO 型（EXP-S14 的 handshake 型只有 2 GB/s）。
- DDR 內的排列（`source/pack5.py`）：先每條 lane 輪流各一字（前 2 個平面），再只輪 3 平面的 lane；每個 pass 80,688 字（5.16 MB）。

HLS 時兩個問題（都沒有上板）：
1. 引擎自己保存寬字狀態：II = 8（字的暫存被做成會停頓的記憶體，加上回饋路徑）→ 改成獨立的 `slab_wp`。
2. 引擎的前投影累加被放進 `if` 裡：II = 8（不能用每圈一次的累加器）→ 每圈都累加（沒有 item 時加 0）。
之後所有迴圈 II = 1。

## Build（`raw/build/`）

- Quartus：Fmax 172.5 MHz（150 MHz 時序通過），EMIF 使用者時脈 332 MHz；ALM 525,999（56%）、RAM 9,685（83%）、DSP 711（12%）。
- 功耗（quartus_pow）：28.24 W（核心動態 16.31、靜態 6.41、其餘大多是 DDR4 I/O）；不含 SO-DIMM 本身。

## Runtime observations（`raw/observe/board5.log`、`timing5.log`；`analysis/`）

正確性（`analysis/compare_board.txt`）：和 EXP-S13 完全相同的數字——每個 pass 對軟體模型 ≤ 2.9×10⁻⁷；
4 個 pass 合起來 s 對 GPU 3.0×10⁻⁵、反投影 7.9×10⁻⁵。

時間（rep 1 和 rep 2001 相減，150 MHz）：

| 項目 | 每次 | 換算 |
|---|---|---|
| 事件 pass（4 個 pass 前投影 + 反投影，15,977 個事件） | 1.246 ms | 每 iteration 1.00 cycle，3.69 G samples/s（同 EXP-S13） |
| 寬鏈載入一個 pass 的影像（80,688 字，5.16 MB） | 1.042 ms | 0.52 字/cycle，4.96 GB/s |
| 寬鏈讀出一個 pass 的累加器 | 1.424 ms | 0.38 字/cycle，3.63 GB/s |
| **每個子集的搬移（4 載入 + 4 讀出）** | **9.86 ms** | EXP-S13 串列 67.7 ms（6.9 倍）；每 lane 平行模型 2.12 ms |

## FPGA vs GPU 到 PETRIC 門檻（`source/timing5.py`；工作量同 EXP-S11/S13；投影、搬移、voxel 單元都是板上實測，組合計算）

| 工作 | 裝置 | 時間 | 能量 |
|---|---|---|---|
| 時間一（比賽定義） | GPU RTX 3070 Ti Laptop | 8.62 s | 745 J |
| | **FPGA slab 32 + DDR 寬鏈 + voxel V=1** | **7.67 s**（投影 3.73 + voxel 2.49 + 搬移 1.45） | **236 J**（30.8 W） |
| | FPGA，voxel V=4（V=4 是模型） | 5.80 s | 178 J |
| 時間二（最後事件後） | GPU | 0.70 s | 61 J |
| | **FPGA，voxel V=1** | **0.66 s** | **20 J** |
| | FPGA，voxel V=4（模型） | 0.48 s | 15 J |

## Analysis and conclusion

1. **平行載入在板上可行而且正確**：影像和累加器經 DDR 搬移後結果不變。
2. **搬移從整機的 62% 降到 19%**；整機時間一 7.67 s，比筆電 GPU 快 11%，能量少 3.2 倍。時間二 0.66 s 對 0.70 s。
3. 寬鏈只到 0.52（載入）/ 0.38（讀出）字/cycle，不是 1。可能原因：DDR 經 150 MHz 跨時脈、讀寫切換、寫入 burst 長度。
   做到 1 字/cycle 時搬移為每子集約 4.3 ms，時間一約 6.9 s。
4. 剩下最大的一塊是 voxel 單元（V=1 時 2.49 s）。V=4 是模型（4 份單元並行），還沒做。
5. 限制：
   - 投影 lanes 和 voxel 單元還在不同 bitstream；整機是零件實測加組合計算。
   - 主軸是 z 的事件（0.11%）還沒處理。
   - FPGA 功耗是 Quartus 估計（不含 SO-DIMM）；GPU 是 nvidia-smi 板上量測（含其記憶體）。
   - GPU 基準是筆電 GPU。

## Next action

1. voxel 單元放進同一個 bitstream（讀寫 DDR），在板上跑完整的 psv 子集更新（投影 + 搬移 + voxel）。
2. 寬鏈提高到 1 字/cycle（EMIF 時脈端的 loader/storer、較長的 burst）。
3. voxel 單元並行 4 份。
