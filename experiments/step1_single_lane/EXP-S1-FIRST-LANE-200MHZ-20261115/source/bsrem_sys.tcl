# Platform Designer system: 50 MHz -> IOPLL -> HLS ev_lane + JTAG-to-Avalon master; Stratix 10 reset release
package require qsys
create_system bsrem_sys
set_project_property DEVICE_FAMILY {Stratix 10}
set_project_property DEVICE {1SX280HU2F50E1VG}

add_instance clk_in clock_source
set_instance_parameter_value clk_in clockFrequency 50000000.0
set_instance_parameter_value clk_in clockFrequencyKnown 1
set_instance_parameter_value clk_in resetSynchronousEdges DEASSERT

add_instance pll altera_iopll
set_instance_parameter_value pll gui_reference_clock_frequency 50.0
set_instance_parameter_value pll gui_number_of_clocks 1
set_instance_parameter_value pll gui_output_clock_frequency0 200.0
set_instance_parameter_value pll gui_use_locked 1

add_instance jtag altera_jtag_avalon_master
add_instance lane ev_lane_internal
add_instance rr altera_s10_user_rst_clkgate

add_connection clk_in.clk pll.refclk
add_connection clk_in.clk_reset pll.reset
add_connection pll.outclk0 jtag.clk
add_connection pll.outclk0 lane.clock
add_connection clk_in.clk_reset jtag.clk_reset
add_connection clk_in.clk_reset lane.reset

foreach {ifc base} {avs_cra 0x00000000 avs_s_out 0x00010000 avs_io 0x00020000 avs_ev 0x00040000} {
  add_connection jtag.master lane.$ifc
  set_connection_parameter_value jtag.master/lane.$ifc baseAddress $base
}

set_interface_property clk EXPORT_OF clk_in.clk_in
set_interface_property reset EXPORT_OF clk_in.clk_in_reset
set_interface_property pll_locked EXPORT_OF pll.locked
set_interface_property ninit_done EXPORT_OF rr.ninit_done
save_system bsrem_sys.qsys
