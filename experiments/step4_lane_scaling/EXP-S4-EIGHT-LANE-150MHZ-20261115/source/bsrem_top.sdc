create_clock -name CLK_50_B3I -period 20.000 [get_ports CLK_50_B3I]
derive_pll_clocks
derive_clock_uncertainty
set_false_path -from [get_ports CPU_RESET_n]
set_false_path -to [get_ports {LED[*]}]
