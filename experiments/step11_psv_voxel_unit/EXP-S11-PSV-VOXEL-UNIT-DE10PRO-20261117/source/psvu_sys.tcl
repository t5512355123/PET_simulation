# Platform Designer: psv voxel unit + 4 MB single-port 256-bit on-chip RAM (stands in for DDR) + output RAM + JTAG master
package require qsys
create_system psvu_sys
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
add_instance u psv_update_internal
add_instance rr altera_s10_user_rst_clkgate
add_instance mem intel_onchip_memory
set_instance_parameter_value mem dataWidth 256
set_instance_parameter_value mem dualPort 0
set_instance_parameter_value mem memorySize 4194304
set_instance_parameter_value mem singleClockOperation 1
set_instance_parameter_value mem initMemContent 0
add_instance omem intel_onchip_memory
set_instance_parameter_value omem dataWidth 64
set_instance_parameter_value omem dualPort 0
set_instance_parameter_value omem memorySize 1048576
set_instance_parameter_value omem initMemContent 0
add_connection clk_in.clk pll.refclk
add_connection clk_in.clk_reset pll.reset
foreach c {jtag.clk u.clock mem.clk1 omem.clk1} { add_connection pll.outclk0 $c }
foreach r {jtag.clk_reset u.reset mem.reset1 omem.reset1} { add_connection clk_in.clk_reset $r }
# JTAG view: rec RAM at 0, output RAM at 0x400000, unit CSR at 0x500000
add_connection jtag.master mem.s1
set_connection_parameter_value jtag.master/mem.s1 baseAddress 0x00000000
add_connection jtag.master omem.s1
set_connection_parameter_value jtag.master/omem.s1 baseAddress 0x00400000
add_connection jtag.master u.avs_cra
set_connection_parameter_value jtag.master/u.avs_cra baseAddress 0x00500000
# unit view: each host port sees its RAM at address 0
add_connection u.avmm_1_rw mem.s1
set_connection_parameter_value u.avmm_1_rw/mem.s1 baseAddress 0x00000000
add_connection u.avmm_3_rw omem.s1
set_connection_parameter_value u.avmm_3_rw/omem.s1 baseAddress 0x00000000
set_interface_property clk EXPORT_OF clk_in.clk_in
set_interface_property reset EXPORT_OF clk_in.clk_in_reset
set_interface_property pll_locked EXPORT_OF pll.locked
set_interface_property ninit_done EXPORT_OF rr.ninit_done
save_system psvu_sys.qsys
