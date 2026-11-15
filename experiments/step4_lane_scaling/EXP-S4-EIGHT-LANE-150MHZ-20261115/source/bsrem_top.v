// DE10-Pro top: CLK_50_B3I drives the system; reset held until configuration done and CPU_RESET_n released
module bsrem_top(
  input        CLK_50_B3I,
  input        CPU_RESET_n,
  output [3:0] LED
);
  wire ninit_done, locked;
  bsrem_sys u0 (
    .clk_clk              (CLK_50_B3I),
    .reset_reset_n        (CPU_RESET_n & ~ninit_done),
    .pll_locked_export    (locked),
    .ninit_done_ninit_done(ninit_done)
  );
  reg [26:0] cnt = 0;
  always @(posedge CLK_50_B3I) cnt <= cnt + 1'b1;
  assign LED = {~locked, ninit_done, 1'b1, cnt[26]};  // LEDs on DE10-Pro are active-low
endmodule
