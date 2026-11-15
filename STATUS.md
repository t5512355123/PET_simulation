# 目前狀態（2026-11-15 晚上）

**Step 4 lane 擴充：8 lanes PASS，16 lanes INCONCLUSIVE。**

| | 速度 | 能量 |
|---|---|---|
| v10（8 lanes，150 MHz，板上實測） | 1106 M 樣本/秒 | 10.0 nJ/樣本（Quartus 估計 11.1 W） |
| GPU RTX 3070 Ti Laptop | 2660 M 樣本/秒 | 36 nJ/樣本 |

FPGA 能量低 3.6 倍，速度是筆電 GPU 的 0.42 倍。

## 下一步

1. 解決 HLS 編譯時間隨 lane 數暴增的問題（16 lanes 跑 8 小時沒完成）。
2. 影像分區（slab）架構：每條 lane 只存影像的一段平面，所有 lane 共用一份影像，
   才能放進 PETRIC 的實際影像（Esser2：95×163×163 = 2.5 M voxels，fp32 一份 81 Mb，晶片 M20K 共 234 Mb）。

## 已知限制

- 測試影像只有 64×64×32，每條 lane 一份副本。
- FPGA 功耗是 Quartus 估計值，不是實測值；GPU 功耗是 nvidia-smi 讀到的板上功耗。
