# EXP-S22-FULL-ONCHIP-LISTMODE-PSV-20261121 — 完整 online list-mode psv 在 DE10-Pro 上跑到 PETRIC 門檻（EXP-S18～S22）

## Verdict

- 結果和 GPU 一致：`PASS`
  - 板子讀回 x₁…x₅₀，第一次通過 PETRIC 門檻是第 41 次更新，之後連續 10 次都通過。
  - GPU 用同樣的硬體儲存格式跑，也是第 41 次更新第一次通過。
  - 各項 PETRIC 指標，板子和 GPU 最大相差 9.2×10⁻⁴。
- 5 倍速度：`FAIL`
  - 計時範圍是 41 次更新（0～40），全部由晶片內 sequencer 執行，主機不介入。
  - 實測 1.712 s；GPU 在同一份 crystal-pair list-mode 資料上是 2.33 s，所以只快 1.36 倍。
  - 5 倍的目標是 ≤ 0.466 s。
- 慢的原因：DDR 讀取頻寬只有預期的 1/3 到 1/10。細節見第 3 節，修正方法是 EXP-S23。

資料：PETRIC2 GE_D690_NEMA_IQ2。事件是 crystal-pair list-mode，每個事件依 STIR 的 bin 給一條 LOR，另外帶 TOF bin、m（乘法校正）、a（加法校正）。全部 2,911,687 個事件，M = 8 個 subset。

## 1. 架構（`source/slab12.cpp`）

| 單元 | 內容 | 時脈 |
|---|---|---|
| src / exp / eng（40 lane × 4 bank set）/ sink | R2 TOF 投影器。事件以 32 B 一筆，從 DDR 串流進來（E1/E2 兩條通道交錯）；每個事件的比值 m·y/ŷ 由 sink 寫回 DDR | 150 MHz |
| vox | 中央 voxel 單元。用 40×40 對角順序讀 lane 的 ACC、寫新影像。模式：0 SVRG 更新、1 full 更新、2/3 full-gradient 讀出（T_k = bf16(ACC_k − gp/M)，GS 累加）、4 載入、5 前處理器 | 150 MHz |
| rdp | RDP（γ = 2）梯度和 Hessian 對角。一個 cycle 處理一個 voxel，和投影同時跑 | 300 MHz（outclk1） |
| gs | 前處理器用的 5 mm 高斯濾波 | 150 MHz |
| seq | 晶片內 sequencer。整個 41 次更新共 3081 道指令，跑的時候主機完全不介入 | 150 MHz |
| 4 × DDR4 EMIF | 每條通道前面各接一個 `altera_avalon_mm_bridge`（16 pending） | 約 300 MHz |

軟體模型（`g++ -DSWSIM`）和 HLS 是同一份原始碼。軟體模型和 parallelproj 在 FOV 內的誤差：forward 1.0×10⁻⁴，back 8.1×10⁻⁵。

## 2. 這段期間修掉的問題

1. **EXP-S20：fit 時 RAM 和 DSP 放不下**
   - eng 的累加改用 select，DSP 從每 lane 135 降到 105。
   - vin 改由 exp 讀，避開 stall-free cluster 被切開。
   - bank set 依每個 lane 排列，記憶體深度從 5808 降到 5120。
   - 每條 EMIF 前加 bridge，省掉約 205 個 M20K 的 rdata FIFO。
   - RDP 改用自己的時脈。
2. **EXP-S21：ALM 用到 110%**
   - Tok.d 改成定點數（DFRAC 16）。
   - TOF 表改存 A = 2k₀ − k₁、B = k₁ − k₀，權重 w = A + (1 + f)·B。
   - vox 的除法改成計數器（原本要 39k ALUT）。
   - 結果 ALM 降到 88%。
3. **EXP-S22：fitter 內部錯誤和時序**
   - fitter 出現 Internal Error（DBCM、LBLK），原因是合成用的 LD_PRELOAD fork→vfork shim。fit、sta、asm 改成不載入 shim，並用 seed 3。
   - RDP 原本被攤在晶片底部 X60–X230 的長條帶上，Fmax 只有 162 MHz。加了 `PLACE_REGION "X150 Y0 X232 Y110"` 後到 291 MHz，最差 slack −0.103 ns（Slow 100C 模型）。
4. **sequencer 卡死**
   - WAIT 用的內層 spin 迴圈只有讀取，HLS 給它配了會快取的 LSU，CSR 只讀一次，所以單元還在跑時 WAIT 永遠等不完。
   - 改成在主迴圈裡每一輪重讀一次 CSR，讀寫都用 pipelined LSU（`source/seq_comp.inc`）。
5. **DDR 配置重疊**
   - GS 放在 ch3 0x01000000，而 SENS 從 ch3 0x00C00000 開始、長 7.52 MB，所以 GS 會蓋掉 z ≥ 26 的 SENS。
   - 只跑第 0 次更新、讀回中間緩衝區做除錯時找到（`analysis/update0_debug.txt`，比對腳本是 `source/ref_u0.py`）：GP 與 GPU 差 3.1×10⁻³，Σ T_k 與 ACC 差 4.6×10⁻³，都正確；GS 在 z ≥ 26 的平面幾乎全錯。
   - GS 移到 0x01400000；`prog10.py` 加了 DDR 區域重疊的 assert。
   - HLS CSR 的語意：0x18 的 bit1 是 done，唯讀，下一次 start 時才清掉；bit0 是 irq，寫 1 清除。寫 2 什麼都不會清。

## 3. 時間分析（`raw/board_segments.txt`，每段由主機計時，各含約 0.3 ms 的 JTAG 輪詢開銷）

| 段落 | 實測 | 依計算量估的值 |
|---|---|---|
| 一次 subset 更新（37 次） | 32.7 ms | 約 8 ms |
| 　forward（約 36 萬 token） | 6.0 ms | 2.5 ms |
| 　back | 5.9 ms | 2.5 ms |
| 　RDP（從開始到等完） | 約 24 ms | 6.5 ms（300 MHz） |
| 　vox 模式 0 | 16.5 ms | 1.6 ms |
| full-gradient 更新（u = 0、16、32） | 141 ms | 約 55 ms |
| 　全部 subset 的 forward | 46.6 ms | 20 ms |
| 　vox 讀出（模式 2/3），每個 | 5.7 ms | 1.6 ms |
| 前處理器更新（u = 4、8） | 59.6 ms | — |

- 換算頻寬：forward 約 2.2 GB/s（兩條通道合計），RDP 約 0.8 GB/s。
- 這相當於 bridge 的 16 個 pending 全是單拍（64 B）讀取、再乘上延遲的結果。HLS 的 burst-coalesced LSU 遇到這種「每 2～16 次迭代才讀一次」的條件式讀取時，沒有組成 burst。

## 4. 下一步（EXP-S23，已開始建置）

1. 所有連續讀取的 DDR 串流改用 `ihc::lsu<ihc::style<ihc::PREFETCHING>>`：src 的事件 / a′ / s，vox 的 x / g / gp / P / T，RDP 的 x / κ，gs 的 x。改完後軟體模型輸出和 S22 相同。
2. 預估時間：每次 subset 更新約 8.5 ms，full-gradient 更新約 57 ms，總計約 0.5 s。還差一點才到 0.466 s，可能還需要：
   - full-gradient 時讓讀出和下一個 back 重疊；
   - vox 每次迭代處理 16 個 slot；
   - RDP 一個 cycle 處理 2 個 voxel。
