# EXP-S9-LISTMODE-PSV-GPU-20261117 — list-mode psv（GPU 實作）

## Verdict

`PASS`：改成 list-mode、依時間切子集後，psv 和原版一樣在第 98 次更新（12.25 epoch）到達門檻。

## Objective

PETRIC2 冠軍 psv（Speedy，MaGeZ ALG1）原本吃 sinogram、依 view 切子集。
硬體 online 版需要：(1) 事件式輸入；(2) 依時間 / 事件編號切子集；(3) 子集 sensitivity = s / M（只算一次）。
這個實驗確認這三個改動不會讓收斂變慢。

## Conditions

- 資料：PETRIC2 NeuroLF_Esser2，EXP-S6 的 list-mode 事件（2,601,282 個，時間順序是合成的均勻分布）。
- 投影：parallelproj 2.0.7 CUDA Joseph（本機 RTX 3070 Ti Laptop），模型 ŷ = m(c·Ax + a)，c = 1/1.6565 mm。
- 其他和 Speedy main.py 相同：步長 3.5/(1+0.01u)；每 2 epoch 一次全梯度；第 4 次更新和第 1 epoch 開頭重算預條件；
  OSEM 先做 6 mm 高斯濾波；預條件前 5 mm 濾波；P = FOV·x/(s + 2·diagH_RDP·x)；子集先驗梯度 = β/M·∇R。
- RDP：γ = 2、ε = 10⁻³·max(OSEM)、κ、26 鄰居，權重 = vx/|offset·vox|（和 Speedy rdp.py 相同，CUDA kernel 實作）。
- FOV mask：STIR TruncateToCylindricalFOV（和 petric.py 相同）。
- 評分：petric.py 公式；全物體 RMSE 去掉最後 2 個軸向平面（理由見 EXP-S8 和下方 KKT 檢查）。
- 程式：`source/lmcore.py`、`source/lm_psv.py`、`source/kkt.py`。

## Model check（`raw/observe/kkt_NeuroLF_Esser2.json`）

在官方參考影像上算目標函數的 KKT 殘差（|梯度|/sensitivity）：

| 位置 | 殘差中位數 |
|---|---|
| 物體內全部 | 3.6×10⁻⁵ |
| 中間平面 | 2.6×10⁻⁵ |
| 最後 3 個軸向平面 | 1.4×10⁻³、6.4×10⁻³、6.5×10⁻² |

和 EXP-S8（STIR 版）一致：內部接近駐點，最後兩個平面不是，所以評分去掉這兩個平面。
OSEM 影像的指標（RMSE 0.763 / 0.541、VOI 最大 0.118）也和 EXP-S8 相同。

## Results（`raw/observe/lmpsv_esser2_M8*.json`）

| 項目 | sinogram psv（EXP-S8，STIR） | **list-mode psv（本實驗）** |
|---|---|---|
| 到門檻的更新次數 | 98 | **98** |
| epoch | 12.25 | **12.25** |
| 投影量（事件全部前＋反投影一次 = 1） | 18.4 epoch | **18.375 epoch** |
| 演算法時間（3070 Ti Laptop） | 126 s（迭代）＋ 26.5 s setup | **8.62 s**（迭代）；sensitivity 事先算好 |
| GPU 功耗（nvidia-smi，100–200 ms 取樣） | — | 平均 86.4 W（最大 92.8 W，閒置 9.6 W） |
| 能量 | > 14 kJ | **約 745 J** |

兩次執行的時間是 9.36 s 和 8.62 s（第一次包含 cupy kernel 編譯）。

## Analysis and conclusion

- 依時間切子集、sensitivity 用 s/M，收斂曲線和原版幾乎相同。所以硬體可以直接吃事件流，
  不需要先 histogram 成 sinogram。
- 同一張 GPU，list-mode 寫法比 STIR sinogram 寫法快約 15 倍（只處理 260 萬事件，全部留在 GPU）。
  **這也是 FPGA 要比的 GPU 基準**：8.62 s、約 745 J。
- sensitivity（c·Aᵀm，全部 5308 萬 bin）只和掃描儀、衰減有關，掃描前或掃描中就能算，兩邊都不計入。

## Next action

EXP-S10：online（邊收資料邊算），量最後一個事件之後的延遲。
