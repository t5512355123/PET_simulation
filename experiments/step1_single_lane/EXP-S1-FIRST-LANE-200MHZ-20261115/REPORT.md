# EXP-S1-FIRST-LANE-200MHZ-20261115 — 第一版單一 lane，200 MHz

## Verdict

`FAIL`：時序不過。

## Build and source provenance

- HLS 原始碼：`source/ev_csr3.cpp`（CSR slave component，8 個 parity bank，2 份累加器）。
- 系統：JTAG-to-Avalon master + IOPLL（50 → 200 MHz）+ ev_lane。
- 影像 64×64×32（96×96×48 會讓 quartus_syn 用掉 55 GB 記憶體而被終止）。

## Runtime observations

- Fmax 141.3 MHz（Slow 100C 模型），低於目標 200 MHz（`analysis/fmax.txt`）。
- 資源：ALM 138,728（15%）、RAM 964（8%）、DSP 56。

## Next action

同一份原始碼改用 125 MHz：`EXP-S1-CSR-LANE-125MHZ-20261115`。

## Evidence

`raw/build/`（Quartus 摘要、時序報告、SOF SHA-256）。
