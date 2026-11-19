# EXP-S17 Platform Designer: R2 slab (TOF, two resident copies, 4 sets per lane) = src + NLANES x (exp + eng + padd) + sink
# placeholders NLANES, PLLMHZ are replaced by build.sh
package require qsys
create_system slab_sys
set_project_property DEVICE_FAMILY {Stratix 10}
set_project_property DEVICE {1SX280HU2F50E1VG}
set N NLANES
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
add_instance src slab_src_internal
add_instance sink slab_sink_internal
add_connection clk_in.clk pll.refclk
add_connection clk_in.clk_reset pll.reset
add_connection pll.outclk0 jtag.clk
add_connection clk_in.clk_reset jtag.clk_reset
foreach c {src sink} {
  add_connection pll.outclk0 $c.clock
  add_connection clk_in.clk_reset $c.reset
}
for {set i 0} {$i < $N} {incr i} {
  add_instance exp$i slab_exp_internal
  add_instance eng$i slab_eng_internal
  add_instance padd$i padd_internal
  foreach c [list exp$i eng$i padd$i] {
    add_connection pll.outclk0 $c.clock
    add_connection clk_in.clk_reset $c.reset
  }
  add_connection exp$i.wq eng$i.wq
  add_connection eng$i.fl padd$i.fl
}
# chain 1: src -> exp0/eng0 -> ... -> expN-1/engN-1 -> sink ; chain 2: src -> padd0 -> ... -> paddN-1 -> sink
add_connection src.tout exp0.in0
add_connection src.pout padd0.pin
for {set i 1} {$i < $N} {incr i} {
  set j [expr {$i - 1}]
  add_connection eng$j.out0 exp$i.in0
  add_connection padd$j.pout padd$i.pin
}
set l [expr {$N - 1}]
add_connection eng$l.out0 sink.tin
add_connection padd$l.pout sink.pin
# JTAG view
foreach {ifc base} {avs_cra 0x00000000 avs_s_in 0x00020000 avs_io 0x00040000 avs_ev 0x00100000 avs_rowt 0x00180000} {
  add_connection jtag.master src.$ifc
  set_connection_parameter_value jtag.master/src.$ifc baseAddress $base
}
foreach {ifc base} {avs_cra 0x00010000 avs_s_out 0x00060000 avs_io 0x00080000} {
  add_connection jtag.master sink.$ifc
  set_connection_parameter_value jtag.master/sink.$ifc baseAddress $base
}
set_interface_property clk EXPORT_OF clk_in.clk_in
set_interface_property reset EXPORT_OF clk_in.clk_in_reset
set_interface_property pll_locked EXPORT_OF pll.locked
set_interface_property ninit_done EXPORT_OF rr.ninit_done
save_system slab_sys.qsys
