#!/bin/bash
# EXP-S20 build: usage ./build11.sh <PLL MHz> <RDP MHz> <h dir> <hr dir>
#   <h dir>: finished HLS project dir holding slab.prj (slab10.cpp -DNO_RDP -DIOCHUNK=4096), <hr dir>: rdp.prj dir
# Quartus project in sys13_<MHz>_<RDP MHz>; 4 DDR4 EMIFs behind pipeline bridges (mksys11.py); RDP clock = PLL outclk1.
# quartus_syn forks ip-deploy at ~57 GB: LD_PRELOAD shim (fork -> vfork when RSS >= 20 GB) for the CentOS 7 overcommit check.
Q=/opt/intelFPGA_pro/21.3
F=$1; FR=$2; H=$3; HR=$4
B=~/06_PET/r3
D=$B/sys13_${F}_${FR}
mkdir -p $D && cd $D || exit 1
python3 $B/mksys11.py ~/06_PET/r2/slab7_sys.tcl slab_sys.tcl $FR || { echo "compile exit failed (mksys)"; exit 1; }
cp $B/slab_top4.v slab_top.v
sed 's/set_instance_parameter_value ddr /set_instance_parameter_value $inst /' ~/06_PET/ddr/emif_params.tcl > emif_params_inst.tcl
sed "s/bsrem_top/slab_top/; s/bsrem_sys.qsys/slab_sys.qsys/; s/bsrem_top.v/slab_top.v/; s/bsrem_top.sdc/slab_top.sdc/; /IP_SEARCH_PATHS/d; /IP_FILE/d" \
  ~/06_PET/quartus/bsrem_top.qsf > slab_top.qsf
echo "set_global_assignment -name IP_SEARCH_PATHS \"$H/slab.prj/components/**/*;$HR/rdp.prj/components/**/*\"" >> slab_top.qsf
grep -v "DDR4A_EVENT_n\|DDR4A_SCL\|DDR4A_SDA" ~/06_PET/ddr/ddr4a_pins.qsf >> slab_top.qsf
cat ~/06_PET/ddr/ddr4bcd_pins.qsf >> slab_top.qsf
echo "set_global_assignment -name NUM_PARALLEL_PROCESSORS 4" >> slab_top.qsf
echo 'PROJECT_REVISION = "slab_top"' > slab_top.qpf
cp ~/06_PET/quartus/bsrem_top.sdc slab_top.sdc
for c in A B C D; do echo "create_clock -period \"300.000000 MHz\" [get_ports DDR4${c}_REFCLK_p]" >> slab_top.sdc; done
sed -i "s/NLANES/40/; s/PLLMHZ/$F/" slab_sys.tcl
SP="$H/slab.prj/components/**/*,$HR/rdp.prj/components/**/*,\$"
$Q/qsys/bin/qsys-script --script=slab_sys.tcl --quartus-project=slab_top.qpf --search-path="$SP" > script.log 2>&1 || echo "qsys-script returned $? (parameter warnings)"
grep -E "^.*Error" script.log | grep -v "No parameter named" | head -5
echo "qsys-script done"
$Q/qsys/bin/qsys-generate slab_sys.qsys --synthesis=VERILOG --quartus-project=slab_top.qpf --search-path="$SP" > gen.log 2>&1 || { echo "compile exit failed (generate)"; grep -i error gen.log | head; exit 1; }
echo "qsys-generate done; IP_FILE lines: $(grep -c IP_FILE slab_top.qsf || true)"
export LD_PRELOAD=$B/libvf.so
cat >> slab_top.qsf <<'QSF'
set_global_assignment -name SEED 3
set_instance_assignment -name PLACE_REGION "X150 Y0 X232 Y110" -to u0|rdp
set_instance_assignment -name RESERVE_PLACE_REGION OFF -to u0|rdp
set_instance_assignment -name CORE_ONLY_PLACE_REGION ON -to u0|rdp
set_instance_assignment -name REGION_NAME rdp_region -to u0|rdp
QSF
( time $Q/quartus/bin/quartus_syn slab_top ) > compile.log 2>&1 || { echo "compile exit failed (syn)"; exit 1; }
unset LD_PRELOAD
( time ( $Q/quartus/bin/quartus_fit slab_top && $Q/quartus/bin/quartus_sta slab_top && $Q/quartus/bin/quartus_asm slab_top ) ) > fit.log 2>&1 && echo "compile exit 0" || echo "compile exit failed"
unset LD_PRELOAD
grep -A8 "; Fmax Summary" slab_top.sta.rpt | grep MHz || true
grep -E "ALMs|RAM Blocks|DSP" slab_top.fit.summary || true
