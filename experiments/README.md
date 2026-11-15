# PET FPGA experiments

每個實驗放在 `stepX_.../EXP-SX-<短標題>-<YYYYMMDD>/`，一個實驗只改一個變數。
資料夾內容：

| 檔案 | 內容 |
|---|---|
| `PLAN.md` | 目的、假設、固定條件、要改的變數、步驟、通過條件（實驗開始前寫） |
| `REPORT.md` | 判定（PASS / FAIL / INCONCLUSIVE）、建置來源、燒錄、觀測、分析、下一步 |
| `source/` | 這次實驗用的 HLS 原始碼與 Quartus 系統檔（凍結版本） |
| `raw/build/` | Quartus/HLS 摘要、時序報告、功耗報告、SOF 的 SHA-256 |
| `raw/observe/` | System Console 輸出、板上讀回的資料（`board_*.bin`） |
| `raw/testdata/` | 軟體模擬產生的輸入與預期輸出（`ev.bin`、`img.bin`、`expect_*.bin`、`meta.txt`） |
| `analysis/` | 由原始紀錄算出的結果（`compare_board.txt`、`fmax.txt`） |
| `SHA256SUMS` | 所有原始紀錄的 SHA-256 |

原始紀錄必須保持原樣，不可改寫。SOF 檔（約 196 MB）不進 git，只記錄 SHA-256。

Commit 訊息前綴：

- `exp:` 開始或記錄一個實驗（例如 `exp: start Step4 8-lane 150 MHz build`、`exp: record Step4 8-lane PASS`）
- `fix:` 修正硬體或腳本錯誤
- `timing:` 時序約束或頻率調整
- `docs:` 只改文件

`legacy/` 放早期的試驗程式（v1/v2 kernel、CSR 試驗、HLS 限制測試），只留原始碼。
