# EXP-S5-SLAB-PARTITION-MODEL-20261116 — 影像分區（slab）架構的效率模型

## Verdict

`PASS`（離線模型；還沒有硬體）：值得做成硬體。

## Objective

Step 3–4 的每條 lane 都存一份完整影像，因此：
- PETRIC 的實際影像（2.5–16 M voxels）放不進片上記憶體；
- lane 數擴充時，RAM 和 HLS 編譯時間都暴增（16 lanes 的 HLS 8 小時沒跑完）。

slab 架構：沿射線的主軸（橫向的 x 或 y）把影像切成 N 段平面，第 k 條 lane 只存第 k 段。
每個事件同時送到所有 lane，每條 lane 只走射線落在自己那一段的 Joseph 步；
前投影的部分和在事件結束時加總，算出比值 s 後再廣播回所有 lane 做反投影。
全部 lane 合起來只需要一份影像（x 主軸、y 主軸的事件各一次 pass，或各存一份）。

## Conditions

- 資料：PETRIC2 NeuroLF Esser2，影像 95×163×163（2.52 M voxels，1.66 mm），
  隨機抽 40,000 個非零事件（list-mode 時間順序近似隨機），輸入 SHA-256 在 `raw/observe/slab_input_sha.txt`。
- 射線裁切到影像框內，平均每個事件 143.4 個 Joseph 步。
- 每條 lane 每接一段事件多 2 cycles（事件載入與結束旗標，依 v8 量測估計）。
- 模型：lane k 處理事件 e 之前，所有 lane 必須已完成事件 e − W（有限的部分和緩衝區）。
- 程式 `source/slab_fifo.py`，輸出 `raw/observe/slab_fifo_out.txt`。

## Results

| lanes N | 每個事件碰到的 slab 數 | 整體負載平衡 | 每 cycle 有用步數（W = 16–256） | 效率 |
|---|---|---|---|---|
| 8 | 7.28 | 0.919 | 6.67 | 0.83 |
| 16 | 14.33 | 0.914 | 12.18 | 0.76 |
| 32 | 28.41 | 0.912 | 20.90 | 0.65 |

- 緩衝區深度 W 從 16 到 256，結果都一樣：瓶頸不是 lane 之間的等待。
- 效率損失有兩個來源：
  1. 邊緣的 slab 分到的步數較少（平衡 0.91），因為影像框邊緣的射線較短。
  2. 每段 2 cycles 的額外時間：N = 32 時每段平均只有 4.5 步，額外時間佔很大比例。

## Analysis and conclusion

以 150 MHz 換算（樣本的定義和 `compare_board.py` 相同）：

| | 樣本/秒 | 每條 lane 存的影像 |
|---|---|---|
| v10（8 lanes，每條 lane 一份影像，實測） | 1.11 G | 64×64×32 完整副本 |
| slab 16 lanes（模型） | 約 1.8 G | 1/16 的實際影像 |
| slab 32 lanes（模型） | 約 3.1 G | 1/32 的實際影像 |
| GPU RTX 3070 Ti Laptop（實測） | 2.66 G | — |

記憶體：Esser2 fp32 影像一份 81 Mb，加上累加器共 162 Mb；Stratix 10 SX 2800 的 M20K 共 234 Mb。
x、y 主軸的事件分兩次 pass 時，放得下實際大小的影像。

slab 32 lanes 預估可以超過筆電 GPU，而且是用實際影像大小。

## Next action

1. 用累積負載切 slab 邊界（不平均切），把平衡從 0.91 拉到接近 1。
2. 讓 lane 之間的事件交接管線化，把每段 2 cycles 降低。
3. 寫 HLS：先用 64×64×32 和 8 lanes 驗證正確性，再放大影像。
