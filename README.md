# PET 事件式投影器：DE10-Pro FPGA 實作

最新紀錄整理日期：**2026-11-15**；分支：`fpga-event-projector`。

本分支記錄 PET list-mode（事件式）重建的 FPGA 硬體化實驗。
目標是在 DE10-Pro（Stratix 10 SX 2800）上做出比 GPU 更省電、
速度接近或超過 GPU 的前投影＋反投影引擎，給 SVRG 類演算法（PETRIC2 冠軍 psv）使用。

`main` 分支是 OpenGATE 模擬與 TOF 重建的另一條工作線，本分支不修改它。

## 目前結論

| 項目 | 結果 |
|---|---|
| 演算法 | psv（SVRG）在 PETRIC2 測試資料 5–12 epoch 達標；BSREM 與 online BSREM 40 epoch 內都沒有達標。所以硬體要做 psv。 |
| FPGA 最佳版（v10，8 lanes，150 MHz） | 1106 M 樣本/秒（板上實測，含 JTAG 控制時間）；結果和軟體模擬一致（反投影相對誤差 1.8×10⁻⁷）；Quartus 功耗估計 11.1 W → **10.0 nJ/樣本** |
| GPU（RTX 3070 Ti Laptop，parallelproj CUDA） | 2660 M 樣本/秒；板上功耗約 95 W → **36 nJ/樣本** |
| CPU（Xeon 8559C，24 執行緒） | 約 500 M 樣本/秒 |

「樣本」= Joseph 投影沿主軸走一步，前投影與反投影各算一次。

FPGA 目前每個樣本省 3.6 倍能量，速度是筆電 GPU 的 0.42 倍。
16 lanes 的 HLS 跑不完；下一步是讓所有 lane 共用一份影像的分區（slab）架構。

## 目錄

| 路徑 | 內容 |
|---|---|
| `hls/` | 目前開發中的 HLS 原始碼與產生器（`lanes_part.cpp`、`make_v7.py`、`patch_*.py`、`ev_v5.cpp`、`ev_v10.cpp`） |
| `quartus/` | 目前的 Platform Designer 系統與 Quartus 專案範本 |
| `scripts/` | 板上測試（System Console）、結果比對、建置狀態、CPU/GPU 基準量測 |
| `experiments/` | 每個實驗的 PLAN、REPORT、凍結原始碼、原始紀錄、分析與 SHA256SUMS |
| `MILESTONES.md` | 各階段 PASS/FAIL 一覽 |
| `STATUS.md` | 目前進行中的工作 |

建置工作區（`sysN/`、`ev_*.prj/`、`boardN/`）留在 snoopy 的 `~/claude_bsrem/`，
不進 git。SOF 檔約 196 MB，超過 GitHub 單檔上限，只記錄 SHA-256。

## 建置方式（snoopy）

```bash
source /opt/intelFPGA_pro/21.3/hls/init_hls.sh
i++ -march=1SX280HU2F50E1VG --simulator none -ffp-reassociate --clock 250MHz hls/ev_v10.cpp -o ev_v10   # HLS
i++ -march=x86-64 -O2 -ffp-reassociate hls/ev_v10.cpp -o v10_emu                                           # 軟體模擬
ACTIVE=8 DUMP=1 ./v10_emu 4000                                                                             # 產生測試資料
```

接著用 `quartus/full.sh`（qsys-script → qsys-generate → Quartus compile），
`quartus_pgm -c 1 -m jtag -o "p;bsrem_top.sof@1"` 燒錄，
再用 `scripts/board_test.tcl` 與 `scripts/compare_board.py` 比對結果。
