# Legacy probes

早期試驗程式，只保留原始碼，不是目前的設計。

| 檔案 | 內容 |
|---|---|
| `early-probes/ev_kernel.cpp`、`ev_kernel_tb.cpp` | v1：第一個事件 kernel 與 testbench |
| `early-probes/ev_kernel_v2.cpp` | v2 |
| `early-probes/ev_csr.cpp`、`ev_csr2.cpp` | CSR slave component 試驗（`ev_csr3.cpp` 在 Step 1） |
| `early-probes/ev_v6.cpp` | 多 lane 的第一版（被 v7 取代） |
| `early-probes/hls_test_t.cpp`、`lim_t.cpp`、`lim_u.cpp` | HLS 限制測試（slave memory 超過 256 KB 會讓 i++ 21.3 當掉） |
| `early-probes/cosim_ev_v7.cpp` | ModelSim ASE 19.1 co-simulation 試驗（停在 time 0，放棄） |
