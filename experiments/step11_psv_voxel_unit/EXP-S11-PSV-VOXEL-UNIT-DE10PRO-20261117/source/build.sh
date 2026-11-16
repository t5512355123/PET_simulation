#!/bin/bash
# usage: ./build.sh <PLL MHz>
set -e
Q=/opt/intelFPGA_pro/21.3
cd ~/claude_bsrem/sys_psvu
sed "s/PLLMHZ/$1/" psvu_sys.tcl > psvu_sys_gen.tcl
SP="../psvu/psvu.prj/components/psv_update/**/*,\$"
$Q/qsys/bin/qsys-script --script=psvu_sys_gen.tcl --quartus-project=psvu_top.qpf --search-path="$SP" > script.log 2>&1
echo "qsys-script done"
$Q/qsys/bin/qsys-generate psvu_sys.qsys --synthesis=VERILOG --quartus-project=psvu_top.qpf --search-path="$SP" > gen.log 2>&1
echo "qsys-generate done"
( time $Q/quartus/bin/quartus_sh --flow compile psvu_top ) > compile.log 2>&1
echo "compile exit $?"
grep -A6 "; Fmax Summary" psvu_top.sta.rpt | grep MHz
grep -E "ALMs|RAM Blocks|DSP" psvu_top.fit.summary
