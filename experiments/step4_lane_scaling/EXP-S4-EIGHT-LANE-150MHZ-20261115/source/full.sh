#!/bin/bash
source /opt/intelFPGA_pro/21.3/hls/init_hls.sh >/dev/null 2>&1
cd ~/claude_bsrem
i++ -march=1SX280HU2F50E1VG --simulator none -ffp-reassociate --clock 250MHz ev_v10.cpp -o ev_v10 > ev_v10.log 2>&1
echo "hls done $?" 
cd sys10
/opt/intelFPGA_pro/21.3/qsys/bin/qsys-script --script=bsrem_sys.tcl --quartus-project=bsrem_top.qpf --search-path="../ev_v10.prj/components/ev_lane/**/*,\$" > script.log 2>&1
./build.sh
