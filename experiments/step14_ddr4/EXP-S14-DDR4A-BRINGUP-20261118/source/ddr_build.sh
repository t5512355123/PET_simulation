#!/bin/bash
# EXP-S14 build: write qsf first, then Platform Designer script + generate (adds IP_FILE lines), then compile
set -e
Q=/opt/intelFPGA_pro/21.3
B=~/claude_bsrem/ddr
cd $B/sys
rm -rf ddr_sys ddr_sys.qsys ip qdb db
cp ../ddr_top.v ../emif_params.tcl .
sed "s/PLLMHZ/150/" ../ddr_sys.tcl > ddr_sys.tcl
sed "s/bsrem_top/ddr_top/; s/bsrem_sys.qsys/ddr_sys.qsys/; s/bsrem_top.v/ddr_top.v/; s/bsrem_top.sdc/ddr_top.sdc/; /IP_SEARCH_PATHS/d; /IP_FILE/d" ~/claude_bsrem/quartus/bsrem_top.qsf > ddr_top.qsf
echo "set_global_assignment -name IP_SEARCH_PATHS \"$B/ddrbw.prj/components/**/*\"" >> ddr_top.qsf
grep -v "DDR4A_EVENT_n\|DDR4A_SCL\|DDR4A_SDA" ../ddr4a_pins.qsf >> ddr_top.qsf
echo 'PROJECT_REVISION = "ddr_top"' > ddr_top.qpf
cp ~/claude_bsrem/quartus/bsrem_top.sdc ddr_top.sdc
echo 'create_clock -period "300.000000 MHz" [get_ports DDR4A_REFCLK_p]' >> ddr_top.sdc
SP="$B/ddrbw.prj/components/**/*,\$"
$Q/qsys/bin/qsys-script --script=ddr_sys.tcl --quartus-project=ddr_top.qpf --search-path="$SP" > script.log 2>&1 || echo "qsys-script returned $? (parameter warnings)"
$Q/qsys/bin/qsys-generate ddr_sys.qsys --synthesis=VERILOG --quartus-project=ddr_top.qpf --search-path="$SP" > gen.log 2>&1
echo "generate done; IP_FILE lines: $(grep -c IP_FILE ddr_top.qsf || true)"
( time $Q/quartus/bin/quartus_sh --flow compile ddr_top ) > compile.log 2>&1 && echo "compile exit 0" || echo "compile exit 1"
grep -A8 "; Fmax Summary" ddr_top.sta.rpt | grep MHz || true
grep -E "ALMs|RAM Blocks|DSP" ddr_top.fit.summary || true
