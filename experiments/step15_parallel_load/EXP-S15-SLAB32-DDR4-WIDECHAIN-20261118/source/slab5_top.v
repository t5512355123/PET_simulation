// EXP-S15 DE10-Pro top: slab v5 with DDR4A. LED[0] blink, LED[1] = cal success, LED[2] = cal fail (active low)
module slab_top(
  input         CLK_50_B3I,
  input         CPU_RESET_n,
  output [3:0]  LED,
  input         DDR4A_REFCLK_p,
  output [16:0] DDR4A_A,
  output [1:0]  DDR4A_BA,
  output [1:0]  DDR4A_BG,
  output        DDR4A_CK,
  output        DDR4A_CK_n,
  output        DDR4A_CKE,
  inout  [8:0]  DDR4A_DQS,
  inout  [8:0]  DDR4A_DQS_n,
  inout  [71:0] DDR4A_DQ,
  inout  [8:0]  DDR4A_DBI_n,
  output        DDR4A_CS_n,
  output        DDR4A_RESET_n,
  output        DDR4A_ODT,
  output        DDR4A_PAR,
  input         DDR4A_ALERT_n,
  output        DDR4A_ACT_n,
  input         DDR4A_RZQ,
  output        SI5340A0_OE_n,
  output        SI5340A0_RST_n,
  output        SI5340A1_OE_n,
  output        SI5340A1_RST_n
);
  assign SI5340A0_OE_n = 1'b0;
  assign SI5340A0_RST_n = 1'b1;
  assign SI5340A1_OE_n = 1'b0;
  assign SI5340A1_RST_n = 1'b1;
  wire ninit_done, locked, cal_ok, cal_fail;
  slab_sys u0 (
    .clk_clk                      (CLK_50_B3I),
    .reset_reset_n                (CPU_RESET_n & ~ninit_done),
    .ddr_ref_clk                  (DDR4A_REFCLK_p),
    .ddr_oct_oct_rzqin            (DDR4A_RZQ),
    .ddr_mem_mem_ck               (DDR4A_CK),
    .ddr_mem_mem_ck_n             (DDR4A_CK_n),
    .ddr_mem_mem_a                (DDR4A_A),
    .ddr_mem_mem_act_n            (DDR4A_ACT_n),
    .ddr_mem_mem_ba               (DDR4A_BA),
    .ddr_mem_mem_bg               (DDR4A_BG),
    .ddr_mem_mem_cke              (DDR4A_CKE),
    .ddr_mem_mem_cs_n             (DDR4A_CS_n),
    .ddr_mem_mem_odt              (DDR4A_ODT),
    .ddr_mem_mem_reset_n          (DDR4A_RESET_n),
    .ddr_mem_mem_par              (DDR4A_PAR),
    .ddr_mem_mem_alert_n          (DDR4A_ALERT_n),
    .ddr_mem_mem_dqs              (DDR4A_DQS),
    .ddr_mem_mem_dqs_n            (DDR4A_DQS_n),
    .ddr_mem_mem_dq               (DDR4A_DQ),
    .ddr_mem_mem_dbi_n            (DDR4A_DBI_n),
    .ddr_status_local_cal_success (cal_ok),
    .ddr_status_local_cal_fail    (cal_fail),
    .pll_locked_export            (locked),
    .ninit_done_ninit_done        (ninit_done)
  );
  reg [26:0] cnt = 0;
  always @(posedge CLK_50_B3I) cnt <= cnt + 1'b1;
  assign LED = {~locked, ~cal_fail, ~cal_ok, cnt[26]};
endmodule
