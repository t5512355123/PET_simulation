"""Time and energy to the PETRIC threshold, Esser2: GPU (measured) vs FPGA (measured parts + stated model).

Work (measured in EXP-S9 / EXP-S10):
  offline LM-psv : 18.375 projection-epochs, 98 updates -> voxel passes = 91 subset steps + 7 full gradients x (8 table + 1 step)
                   + 2 preconditioner refreshes x 2 passes = 158
  online Br 64/64: after the last event 1.5 projection-epochs, 5 updates -> 1 refresh (8 table + 1 step) + 4 steps + 1 precond x 2 = 15
FPGA voxel unit: cycles/voxel from the board (EXP-S11), times (1 + DLY/N) start-up for the full image.
Usage: python fpga_vs_gpu.py <cyc_per_voxel_board_nz4> <f_unit_MHz> <P_unit_W> <P_unit_static_W> [V lanes of the voxel unit]
"""
import json
import sys

cv4, fu, Pu, Pus = (float(a) for a in sys.argv[1:5])
V = int(sys.argv[5]) if len(sys.argv) > 5 else 1
NEV, STEPS = 2601282, 143.4
SAMPLES = 2 * NEV * STEPS                          # forward + back samples per projection-epoch
NVOX, PLANE, NX = 95 * 163 * 163, 163 * 163, 163
DLY = PLANE + NX + 1
cyc_iter = cv4 / ((4 * PLANE + DLY) / (4 * PLANE))   # board run had nz = 4: remove its start-up share
cyc_full = cyc_iter * (NVOX + DLY) / NVOX
t_pass = NVOX * cyc_full / (fu * 1e6) / V

WORK = {'offline LM-psv (time 1)': (18.375, 158), 'online Br 64/64 (time 2)': (1.5, 15)}
GPU = {'s_per_epoch': 8.62 / 18.375, 'W': 86.4}     # EXP-S9: 8.62 s at 86.4 W for 18.375 epochs incl. voxel ops
FPGA = {'v10 8 lanes (board)': (1106e6, 11.10, 6.13), 'slab 32 lanes (model)': (3.1e9, None, 6.13)}
rows = []
for wname, (ep, passes) in WORK.items():
    tg = ep * GPU['s_per_epoch']
    rows.append(dict(work=wname, device='GPU RTX 3070 Ti Laptop (measured, list-mode)', t_s=tg, E_J=tg * GPU['W']))
    for fname, (thr, P, Pst) in FPGA.items():
        tp = ep * SAMPLES / thr
        tv = passes * t_pass
        if P is None:                                  # slab-32: dynamic power scaled by lanes from v10 (8 lanes)
            P = Pst + (11.10 - 6.13) * 32 / 8
        Ptot = P + (Pu - Pus)                          # one device: count static power once
        t = tp + tv
        rows.append(dict(work=wname, device=f'FPGA {fname} + voxel unit V={V}', t_proj_s=tp, t_voxel_s=tv, t_s=t,
                         P_W=Ptot, E_J=t * Ptot))
print(f'voxel unit: {cyc_full:.3f} cycles/voxel on the full image, {t_pass*1e3:.1f} ms per pass (V={V}, {fu} MHz)')
for r in rows:
    extra = f"  (projection {r['t_proj_s']:.2f} s + voxel {r['t_voxel_s']:.2f} s, {r['P_W']:.1f} W)" if 't_proj_s' in r else ''
    print(f"{r['work']:26s} {r['device']:52s} {r['t_s']:7.2f} s {r['E_J']:7.0f} J{extra}")
json.dump(dict(inputs=dict(cyc_per_voxel_board_nz4=cv4, f_unit_MHz=fu, P_unit_W=Pu, P_unit_static_W=Pus, V=V),
               cyc_per_voxel_full=cyc_full, t_pass_s=t_pass, rows=rows), open(f'fpga_vs_gpu_V{V}.json', 'w'), indent=1)
