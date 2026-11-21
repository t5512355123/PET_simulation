#!/bin/bash
# EXP-S22: sys12 + fixed sequencer (WAIT poll in the main loop, pipelined LSUs) + RDP place region; seed 3; shim only for syn
B=~/06_PET/r3; cd $B
rm -rf engx/h13; cp -a engx/h12 engx/h13
rm -rf engx/h13/slab.prj/components/slab_seq; cp -a hseq/seq.prj/components/slab_seq engx/h13/slab.prj/components/
cp seq_comp.inc engx/h13/
sed 's/sys12_/sys13_/; s/^( time \$Q\/quartus\/bin\/quartus_sh --flow compile slab_top ) > compile.log 2>&1 \&\& echo "compile exit 0" || echo "compile exit failed"$/RUNQ/' build12.sh > build13.sh
python3 - <<'PY'
s=open('build13.sh').read()
q='''cat >> slab_top.qsf <<'QSF'
set_global_assignment -name SEED 3
set_instance_assignment -name PLACE_REGION "X150 Y0 X232 Y110" -to u0|rdp
set_instance_assignment -name RESERVE_PLACE_REGION OFF -to u0|rdp
set_instance_assignment -name CORE_ONLY_PLACE_REGION ON -to u0|rdp
set_instance_assignment -name REGION_NAME rdp_region -to u0|rdp
QSF
( time $Q/quartus/bin/quartus_syn slab_top ) > compile.log 2>&1 || { echo "compile exit failed (syn)"; exit 1; }
unset LD_PRELOAD
( time ( $Q/quartus/bin/quartus_fit slab_top && $Q/quartus/bin/quartus_sta slab_top && $Q/quartus/bin/quartus_asm slab_top ) ) > fit.log 2>&1 && echo "compile exit 0" || echo "compile exit failed"'''
assert 'RUNQ' in s
s=s.replace('RUNQ',q); open('build13.sh','w').write(s)
PY
chmod +x build13.sh
grep -n 'SEED\|quartus_syn\|quartus_fit\|sys13' build13.sh
./build13.sh 150 300 $B/engx/h13 $B/hr11
