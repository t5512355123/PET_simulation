// On-chip sequencer (EXP-S19): runs a command list written by the host into its program memory, so the whole psv run
// (40 updates: forward / back / sweeps / RDP passes) needs no host round trips.
// Command {op, addr, val}: op 0 END; 1 WRITE csr[addr] = val; 2 WAIT until (csr[addr] & val) != 0, then csr[addr] = val
// (clears the done bit, as the host's waitdone); 3 COUNT (log[val] = number of commands executed so far, a progress mark).
// csr: 32-bit host on the CSR address space (same addresses as the JTAG view), word address = byte address / 4.
#define NPROG 8192
#define NLOG 256
struct SeqCmd { unsigned op, addr, val, pad; };
hls_avalon_slave_component component int slab_seq(
    hls_avalon_slave_memory_argument(NPROG * sizeof(SeqCmd)) SeqCmd *prog,
    hls_avalon_slave_memory_argument(NLOG * sizeof(unsigned)) unsigned *slog,
    hls_avalon_slave_register_argument ihc::mm_master<unsigned, ihc::aspace<5>, ihc::awidth<24>, ihc::dwidth<32>, ihc::latency<0>, ihc::maxburst<1>,
                   ihc::waitrequest<true>> &csr,
    hls_avalon_slave_register_argument int start) {
  // EXP-S22: the WAIT poll is part of the main loop (one CSR read per pass, the command is re-fetched until the bit is
  // set). The S19 inner spin loop `while ((csr[a] & v) == 0) {}` read the CSR once on the board (the load was not
  // re-issued: a load-only loop gets a cached LSU), so a WAIT on a unit that was still running never ended.
  int pc = start, n = 0;
  bool run = true;
  while (run) {
    SeqCmd c = prog[pc & (NPROG - 1)];
    unsigned r = 0;
    if (c.op == 2) r = ihc::lsu<ihc::style<ihc::PIPELINED>>::load(&csr[c.addr >> 2]);   // uncached, unburst
    bool ok = c.op != 2 || (r & c.val) != 0;
    if (c.op == 1 || (c.op == 2 && ok)) ihc::lsu<ihc::style<ihc::PIPELINED>>::store(&csr[c.addr >> 2], c.val);   // no write coalescing
    if (c.op == 3) slog[c.val & (NLOG - 1)] = (unsigned)n;
    run = c.op != 0;
    if (ok) { pc++; n++; }
  }
  return n;
}
