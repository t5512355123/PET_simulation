#!/bin/bash
# usage: ./build.sh <lanes> <PLL MHz>   (HLS project in ../h<lanes>/slab.prj; Quartus project in ../sys<lanes>_<MHz>)
set -e
Q=/opt/intelFPGA_pro/21.3
L=$1; F=$2
B=~/claude_bsrem/slab4
D=$B/sys${L}_${F}
mkdir -p $D && cd $D
cp $B/slab_sys.tcl $B/slab_top.v $B/slab_top.sdc .
sed "s/bsrem_top/slab_top/; s/bsrem_sys.qsys/slab_sys.qsys/; s/bsrem_top.v/slab_top.v/; s/bsrem_top.sdc/slab_top.sdc/; /IP_SEARCH_PATHS/d; /IP_FILE/d" \
  ~/claude_bsrem/quartus/bsrem_top.qsf > slab_top.qsf
echo "set_global_assignment -name IP_SEARCH_PATHS \"$B/h$L/slab.prj/components/**/*\"" >> slab_top.qsf
echo 'PROJECT_REVISION = "slab_top"' > slab_top.qpf
sed -i "s/NLANES/$L/; s/PLLMHZ/$F/" slab_sys.tcl
SP="$B/h$L/slab.prj/components/**/*,\$"
$Q/qsys/bin/qsys-script --script=slab_sys.tcl --quartus-project=slab_top.qpf --search-path="$SP" > script.log 2>&1
echo "qsys-script done"
$Q/qsys/bin/qsys-generate slab_sys.qsys --synthesis=VERILOG --quartus-project=slab_top.qpf --search-path="$SP" > gen.log 2>&1
echo "qsys-generate done"
( time $Q/quartus/bin/quartus_sh --flow compile slab_top ) > compile.log 2>&1
echo "compile exit $?"
grep -A6 "; Fmax Summary" slab_top.sta.rpt | grep MHz || true
grep -E "ALMs|RAM Blocks|DSP" slab_top.fit.summary || true
