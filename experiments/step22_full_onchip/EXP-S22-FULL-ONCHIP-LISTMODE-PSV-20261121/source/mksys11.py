"""slab7_sys.tcl -> slab11 system (EXP-S20): R2 projector + voxel unit v10 + RDP + Gaussian + DMA + sequencer +
4 DDR4 EMIFs (ddra..ddrd = address spaces 1..4 of the HLS hosts).
Changes from mksys10 (EXP-S19 did not fit: RAM 120 %, DSP 106 %, two IOPLLs on one refclk pin):
  - one pipeline bridge br{a..d} per EMIF in the EMIF clock domain (16 pending reads): the EMIF declares 64 pending
    reads x burst 64, so its interconnect agent kept a 4096 x 512-bit rdata FIFO (~205 M20K per EMIF); behind the bridge
    the agent FIFO is 16 x 64 beats and bridge -> EMIF is point to point;
  - the RDP clock is outclk1 of the main PLL (no second IOPLL).
Usage: python3 mksys11.py <slab7_sys.tcl> <out tcl> <rdp MHz>"""
import sys
s = open(sys.argv[1]).read()
RDPMHZ = sys.argv[3] if len(sys.argv) > 3 else '250'


def rep(a, b):
    global s
    assert s.count(a) == 1, a
    s = s.replace(a, b)


rep("set_instance_parameter_value pll gui_number_of_clocks 1\n",
    "set_instance_parameter_value pll gui_number_of_clocks 2\n"
    f"set_instance_parameter_value pll gui_output_clock_frequency1 {RDPMHZ}\n")
emifs = ''
for c in 'abcd':
    emifs += (f"add_instance ddr{c} altera_emif_s10\nset inst ddr{c}\nsource emif_params_inst.tcl\n"
              f"set_instance_parameter_value ddr{c} PHY_DDR4_DEFAULT_REF_CLK_FREQ false\n"
              f"set_instance_parameter_value ddr{c} PHY_DDR4_USER_REF_CLK_FREQ_MHZ 300.0\n"
              f"add_connection clk_in.clk_reset ddr{c}.global_reset_n\n")
rep("add_instance rr altera_s10_user_rst_clkgate\n",
    "add_instance rr altera_s10_user_rst_clkgate\n" + emifs +
    "add_instance vox slab_vox_internal\nadd_instance dma slab_dma_internal\nadd_instance gs slab_gs_internal\n"
    "add_instance seq slab_seq_internal\nadd_instance rdp slab_rdp_internal\n"
    "add_connection pll.outclk1 rdp.clock\nadd_connection clk_in.clk_reset rdp.reset\n")
rep("foreach c {src sink} {", "foreach c {src sink vox dma gs seq} {")
rep("  add_connection eng$i.fl padd$i.fl\n",
    "  add_connection eng$i.fl padd$i.fl\n  add_connection eng$i.vout vox.o$i\n  add_connection vox.i$i exp$i.vin\n")
hosts = {'src': [1, 2, 3, 4], 'sink': [4], 'vox': [1, 2, 3, 4], 'dma': [1, 2, 3, 4], 'rdp': [3, 4], 'gs': [3]}
conn = "# 512-bit hosts -> br{a,b,c,d} (EMIF clock, 16 pending reads) -> EMIF; address space k -> ddr{a,b,c,d}[k-1]\n"
for e in 'abcd':
    b = f"br{e}"
    for p, v in [('DATA_WIDTH', 512), ('SYMBOL_WIDTH', 8), ('ADDRESS_WIDTH', 34), ('USE_AUTO_ADDRESS_WIDTH', 1),
                 ('ADDRESS_UNITS', 'SYMBOLS'), ('MAX_BURST_SIZE', 64), ('MAX_PENDING_RESPONSES', 16),
                 ('LINEWRAPBURSTS', 0), ('PIPELINE_COMMAND', 1), ('PIPELINE_RESPONSE', 1)]:
        conn += f"set_instance_parameter_value {b} {p} {v}\n" if p != 'DATA_WIDTH' else (
            f"add_instance {b} altera_avalon_mm_bridge\nset_instance_parameter_value {b} {p} {v}\n")
    conn += (f"add_connection ddr{e}.emif_usr_clk {b}.clk\nadd_connection ddr{e}.emif_usr_reset_n {b}.reset\n"
             f"add_connection {b}.m0 ddr{e}.ctrl_amm_0\n"
             f"set_connection_parameter_value {b}.m0/ddr{e}.ctrl_amm_0 baseAddress 0x00000000\n")
for comp, asps in hosts.items():
    for k in asps:
        e = 'abcd'[k - 1]
        conn += (f"add_connection {comp}.avmm_{k}_rw br{e}.s0\n"
                 f"set_connection_parameter_value {comp}.avmm_{k}_rw/br{e}.s0 baseAddress 0x00000000\n")
seqv = ("foreach {c ifc base} {src avs_cra 0x00000000 sink avs_cra 0x00010000 vox avs_cra 0x00220000 rdp avs_cra 0x00230000 "
        "gs avs_cra 0x00240000 dma avs_cra 0x00210000} {\n"
        "  add_connection seq.avmm_5_rw $c.$ifc\n"
        "  set_connection_parameter_value seq.avmm_5_rw/$c.$ifc baseAddress $base\n}\n")
rep("# JTAG view\n", conn + seqv + "# JTAG view\n"
    "foreach {c ifc base} {dma avs_io 0x00200000 dma avs_cra 0x00210000 vox avs_cra 0x00220000 rdp avs_cra 0x00230000 "
    "gs avs_cra 0x00240000 seq avs_cra 0x00250000 seq avs_prog 0x00260000 seq avs_slog 0x00280000} {\n"
    "  add_connection jtag.master $c.$ifc\n"
    "  set_connection_parameter_value jtag.master/$c.$ifc baseAddress $base\n}\n")
exp = ""
for c in 'abcd':
    exp += (f"set_interface_property ddr{c}_ref EXPORT_OF ddr{c}.pll_ref_clk\n"
            f"set_interface_property ddr{c}_oct EXPORT_OF ddr{c}.oct\n"
            f"set_interface_property ddr{c}_mem EXPORT_OF ddr{c}.mem\n"
            f"set_interface_property ddr{c}_status EXPORT_OF ddr{c}.status\n")
rep("set_interface_property ninit_done EXPORT_OF rr.ninit_done\n",
    "set_interface_property ninit_done EXPORT_OF rr.ninit_done\n" + exp +
    "set_domain_assignment {$system} {qsys_mm.clockCrossingAdapter} {FIFO}\n"
    "set_domain_assignment {$system} {qsys_mm.maxAdditionalLatency} {4}\n")
s = s.replace("# EXP-S17 Platform Designer:", "# EXP-S20 Platform Designer (R2 + voxel v10 + RDP + Gaussian + sequencer + 4 x DDR4 behind bridges):")
open(sys.argv[2], 'w').write(s)
print('ok')
