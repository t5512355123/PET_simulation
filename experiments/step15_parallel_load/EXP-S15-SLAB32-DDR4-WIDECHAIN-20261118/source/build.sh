#!/bin/bash
# EXP-S15 build: usage ./build.sh <lanes> <MHz>. qsf (with DDR4A pins) first, then Platform Designer, then compile.
set -e
Q=/opt/intelFPGA_pro/21.3
L=$1; F=$2
B=~/claude_bsrem/slab5
D=$B/sys${L}_${F}
mkdir -p $D && cd $D
cp $B/slab5_sys.tcl slab_sys.tcl
cp $B/slab5_top.v slab_top.v
cp ~/claude_bsrem/ddr/emif_params.tcl .
sed -i "s/NLANES/$L/; s/PLLMHZ/$F/" slab_sys.tcl
sed "s/bsrem_top/slab_top/; s/bsrem_sys.qsys/slab_sys.qsys/; s/bsrem_top.v/slab_top.v/; s/bsrem_top.sdc/slab_top.sdc/; /IP_SEARCH_PATHS/d; /IP_FILE/d" \
  ~/claude_bsrem/quartus/bsrem_top.qsf > slab_top.qsf
echo "set_global_assignment -name IP_SEARCH_PATHS \"$B/h$L/slab.prj/components/**/*\"" >> slab_top.qsf
grep -v "DDR4A_EVENT_n\|DDR4A_SCL\|DDR4A_SDA" ~/claude_bsrem/ddr/ddr4a_pins.qsf >> slab_top.qsf
echo 'PROJECT_REVISION = "slab_top"' > slab_top.qpf
cp ~/claude_bsrem/quartus/bsrem_top.sdc slab_top.sdc
echo 'create_clock -period "300.000000 MHz" [get_ports DDR4A_REFCLK_p]' >> slab_top.sdc
SP="$B/h$L/slab.prj/components/**/*,\$"
$Q/qsys/bin/qsys-script --script=slab_sys.tcl --quartus-project=slab_top.qpf --search-path="$SP" > script.log 2>&1 || echo "qsys-script returned $? (parameter warnings)"
$Q/qsys/bin/qsys-generate slab_sys.qsys --synthesis=VERILOG --quartus-project=slab_top.qpf --search-path="$SP" > gen.log 2>&1
echo "generate done; IP_FILE lines: $(grep -c IP_FILE slab_top.qsf || true)"
( time $Q/quartus/bin/quartus_sh --flow compile slab_top ) > compile.log 2>&1 && echo "compile exit 0" || echo "compile exit 1"
grep -A8 "; Fmax Summary" slab_top.sta.rpt | grep MHz || true
grep -E "ALMs|RAM Blocks|DSP" slab_top.fit.summary || true
