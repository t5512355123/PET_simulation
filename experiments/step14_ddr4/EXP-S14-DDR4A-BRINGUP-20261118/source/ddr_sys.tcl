# EXP-S14 Platform Designer: DDR4A EMIF (parameters from the DE10-Pro System CD RTL_DDR4_x4_ECC/16GB) + JTAG master
# + HLS ddrbw at PLLMHZ MHz (its 512-bit host reaches the EMIF through an automatic clock-crossing adapter)
package require qsys
create_system ddr_sys
set_project_property DEVICE_FAMILY {Stratix 10}
set_project_property DEVICE {1SX280HU2F50E1VG}
add_instance clk_in clock_source
set_instance_parameter_value clk_in clockFrequency 50000000.0
set_instance_parameter_value clk_in clockFrequencyKnown 1
set_instance_parameter_value clk_in resetSynchronousEdges DEASSERT
add_instance pll altera_iopll
set_instance_parameter_value pll gui_reference_clock_frequency 50.0
set_instance_parameter_value pll gui_number_of_clocks 1
set_instance_parameter_value pll gui_output_clock_frequency0 PLLMHZ
set_instance_parameter_value pll gui_use_locked 1
add_instance jtag altera_jtag_avalon_master
add_instance rr altera_s10_user_rst_clkgate
add_instance ddr altera_emif
source emif_params.tcl
set_instance_parameter_value ddr PHY_DDR4_DEFAULT_REF_CLK_FREQ false
set_instance_parameter_value ddr PHY_DDR4_USER_REF_CLK_FREQ_MHZ 300.0
add_instance bw ddrbw_internal
add_connection clk_in.clk pll.refclk
add_connection clk_in.clk_reset pll.reset
add_connection pll.outclk0 jtag.clk
add_connection clk_in.clk_reset jtag.clk_reset
add_connection pll.outclk0 bw.clock
add_connection clk_in.clk_reset bw.reset
add_connection clk_in.clk_reset ddr.global_reset_n
add_connection jtag.master bw.avs_cra
set_connection_parameter_value jtag.master/bw.avs_cra baseAddress 0x00000000
add_connection jtag.master ddr.ctrl_amm_0
set_connection_parameter_value jtag.master/ddr.ctrl_amm_0 baseAddress 0x100000000
add_connection bw.avmm_1_rw ddr.ctrl_amm_0
set_connection_parameter_value bw.avmm_1_rw/ddr.ctrl_amm_0 baseAddress 0x00000000
set_interface_property clk EXPORT_OF clk_in.clk_in
set_interface_property reset EXPORT_OF clk_in.clk_in_reset
set_interface_property pll_locked EXPORT_OF pll.locked
set_interface_property ninit_done EXPORT_OF rr.ninit_done
set_interface_property ddr_ref EXPORT_OF ddr.pll_ref_clk
set_interface_property ddr_oct EXPORT_OF ddr.oct
set_interface_property ddr_mem EXPORT_OF ddr.mem
set_interface_property ddr_status EXPORT_OF ddr.status
set_interface_property ddr_vid EXPORT_OF ddr.vid_cal_done_persist
foreach k {PHY_DDR4_REF_CLK_FREQ_MHZ PHY_DDR4_USER_REF_CLK_FREQ_MHZ CTRL_DDR4_ECC_EN} { puts "P $k [get_instance_parameter_value ddr $k]" }
set_domain_assignment {$system} {qsys_mm.clockCrossingAdapter} {FIFO}
set_domain_assignment {$system} {qsys_mm.maxAdditionalLatency} {4}
save_system ddr_sys.qsys
