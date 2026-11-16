# EXP-S8-PSV-LOCAL-RUN-PROFILE-20261116 — psv 本機實跑與時間分解

## Verdict

`PASS（有條件）`：
- 冠軍程式在本機完整執行。背景 RMSE 和 VOI 誤差都達到門檻。
- 全物體 RMSE 停在 1.22%，原因是最後兩個軸向平面的模型差異（見 Analysis 3）。去掉這兩個平面後，第 98 次更新（12.25 epoch）達到門檻，比賽計時 152.9 s。

完整說明見 `analysis/psv_report.html`（同一份也在 06_PET）。

## Results（Esser2，8 個子集；`raw/observe/summary.json`、`run_log.txt`）

| 項目 | 數值 |
|---|---|
| 讀檔（不計時） | 2.14 s |
| setup | 26.55 s（子集 sensitivity 23.71 s） |
| 一般子集更新 / 全梯度更新 / 含預條件 | 0.86 / 6.59 / 1.93 s |
| 到門檻（去掉最後 2 平面） | 第 98 次更新，12.25 epoch，比賽計時 152.9 s |
| 到門檻為止的子集梯度數 | 147 個（= 18.4 epoch 的投影量） |

### 時間佔比（讀檔到達門檻，共 155.0 s）

| 步驟 | 佔比 |
|---|---|
| 讀檔 | 1.4% |
| 子集 sensitivity | 15.3% |
| 前投影 GPU | 30.4% |
| 取出 viewgram | 3.8% |
| CPU 逐 bin（加 a、乘 m、y/ŷ） | 31.4% |
| 反投影 GPU | 10.5% |
| 其他（RDP、預條件、影像運算、相容層） | 7.2% |

### 一個子集梯度（0.80 s，`decompose.json`）

| 步驟 | 時間 |
|---|---|
| 前投影 `set_input`（所有 view，GPU→host） | 0.32 s |
| 取出子集 | 0.04 s |
| 反投影 | 0.11 s |
| STIR CPU 逐 viewgram 運算（剩餘） | 0.33 s |

## Analysis

1. likelihood 子集梯度佔迭代時間 93%。其中 CPU 對 663 萬個 bin（95% 為 0）的逐點運算和 GPU 前投影各約 40%。
2. 用 list-mode 時：
   - 前投影只做 260 萬事件。每事件平均 143 個 Joseph sample，一個 epoch 前投影＋反投影共 7.46 億 sample。
   - 估計到門檻：
     - FPGA v10（8 lanes）12.3 s
     - 32-lane slab 4.4 s
     - GPU 事件式（EXP-S7 layout C）6.8 s
     - psv 原版 153 s（本機）／78–87 s（A100 排行榜）
3. 最後兩個平面的問題（`kkt_at_ref.txt`）：
   - 在參考影像上，我們目標函數的 KKT 殘差：內部平面約 3e-5，z=94 為 6.5e-2。
   - CUDA 和 CPU 版 RDP 的結果相同（相對差 2.8e-7）。
   - 所以是本機 STIR 6.5 在軸向邊緣的投影模型和官方產生參考影像時不同，不是演算法造成的。

## Limits

- 不是 SIRF。STIR Python 沒有 ProjDataInfoSubsetByView，所以用 STIR 內建子集，parallelproj 每次前投影都會算全部 view。
  - 照 SIRF 的做法估計：子集梯度約 0.52 s，到門檻約 100 s。
  - 因此前投影的佔比被高估了。
- CPU 逐 bin 那一項是「總時間減去其他三項」算出來的。
- 三次執行的 sensitivity setup 分別是 57、28、24 s（磁碟快取影響），表中用第三次。
  - 第二次執行的相容層用了慢的 `fill(.flat)`，資料見 `summary_run2_slowconvert.json`，只作參考。
- 執行時 GPU 有其他程式共用。

## Next action

交給 PET 研究 session：
1. list-mode psv（依時間切子集）；
2. online 做法 A/B/C 的「最後事件後延遲」；
3. 把逐點單元和 stencil 加進 slab 引擎，在 DE10-Pro 合成；
4. 和 GPU 比時間與能量。
