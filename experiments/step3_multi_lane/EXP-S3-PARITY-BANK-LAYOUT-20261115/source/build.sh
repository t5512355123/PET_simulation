#!/bin/bash
set -e
Q=/opt/intelFPGA_pro/21.3
cd ~/claude_bsrem/sys8
$Q/qsys/bin/qsys-generate bsrem_sys.qsys --synthesis=VERILOG --quartus-project=bsrem_top.qpf --search-path="../ev_v8.prj/components/ev_lane/**/*,\$" > gen.log 2>&1
echo "qsys-generate done"
grep -q "QIP_FILE\|IP_FILE" bsrem_top.qsf || true
time $Q/quartus/bin/quartus_sh --flow compile bsrem_top > compile.log 2>&1
echo "compile exit $?"
