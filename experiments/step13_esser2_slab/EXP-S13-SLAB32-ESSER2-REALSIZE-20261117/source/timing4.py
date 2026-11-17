"""EXP-S13 timing: per-pass marginal time from rep 1 / rep N, cycles per busiest-lane iteration, samples/s,
and FPGA vs GPU to the PETRIC threshold (Esser2) with the measured slab projector + measured voxel unit (EXP-S11).
Usage: python3 timing4.py <hw dir> <rep> <f_MHz> <P_total_W> <P_static_W>"""
import re, sys, json
hw, REP, F, P, PS = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
meta = dict(l.split() for l in open(f'{hw}/meta.txt'))
log = open(f'{hw}/board4.log').read()
t_total, it_total, rows = 0.0, 0, []
for p, kind, n, a, b in re.findall(r'TIMING pass (\d) (\w+) tokens (\d+) rep1 (\d+) ms rep\d+ (\d+) ms', log):
    t = (int(b) - int(a)) * 1e-3 / (REP - 1)
    it = int(meta[f'pass{p}_{kind}_maxlane'])
    rows.append(f'pass {p} {kind:4s}: {int(n):5d} tokens, {t * 1e3:.4f} ms = {t * F * 1e6:8.0f} cycles, busiest lane {it} iterations '
                f'-> {t * F * 1e6 / it:.3f} cycles/iteration')
    t_total += t; it_total += it
ne, steps = int(meta['events']), int(meta['real_steps'])
sps = 2 * steps / t_total
print('\n'.join(rows))
print(f'all 4 passes, forward + back: {t_total * 1e3:.4f} ms for {ne} events ({steps} Joseph steps) '
      f'-> {t_total * F * 1e6 / it_total:.3f} cycles/iteration, {sps / 1e9:.3f} G samples/s, {P / sps * 1e9:.2f} nJ/sample at {P} W')
NEV = 2601282
t_epoch = t_total / ne * NEV
print(f'one projection epoch (all {NEV} Esser2 events, forward + back): {t_epoch:.4f} s')
# to the PETRIC threshold (work as EXP-S11): offline 18.375 epochs + 158 voxel passes; online Br 64/64 1.5 epochs + 15 passes
t_vox = 0.01577                                   # EXP-S11 voxel unit, one pass over the Esser2 image (V = 1)
Pv, Pvs = 8.61, 6.10
gpu_ep, gpu_W = 8.62 / 18.375, 86.4
# image in / accumulator out: per subset-equivalent (1/8 epoch) 4 half-image loads + 4 accumulator reads of NPP*NU*NZ voxels
NVP = 82 * 163 * 95
words = 8 * NVP
t_io_serial = words / (F * 1e6)                 # as built: through the token chain, 1 voxel per cycle
t_io_par = words / 32 / (F * 1e6)               # model: each lane loads/reads its own slab, 1 voxel per cycle per lane
print(f'image/accumulator transfer per subset: {words} voxels -> as built (serial chain) {t_io_serial * 1e3:.1f} ms; '
      f'per-lane parallel (model, {32 * 4 * F / 1e3:.1f} GB/s from DDR) {t_io_par * 1e3:.2f} ms')
out = {}
for name, ep, passes in (('time 1 (offline, competition definition)', 18.375, 158), ('time 2 (online Br 64/64, after last event)', 1.5, 15)):
    print(f'{name}: GPU {ep * gpu_ep:.2f} s / {ep * gpu_ep * gpu_W:.0f} J')
    for io_name, tio in (('serial load (as built)', t_io_serial), ('per-lane load (model)', t_io_par)):
        for V in (1, 4):
            tp, tv, tt = ep * t_epoch, passes * t_vox / V, ep * 8 * tio
            Pt = P + (Pv - Pvs)
            t = tp + tv + tt
            print(f'   FPGA slab32 + voxel V={V}, {io_name}: {t:.2f} s (projection {tp:.2f} + voxel {tv:.2f} + image/acc transfer {tt:.2f})'
                  f' / {t * Pt:.0f} J at {Pt:.1f} W')
            out[f'{name} V={V} {io_name}'] = dict(t_fpga=t, E_fpga=t * Pt, t_proj=tp, t_vox=tv, t_io=tt, t_gpu=ep * gpu_ep,
                                                  E_gpu=ep * gpu_ep * gpu_W)
json.dump(dict(t_batch=t_total, samples_per_s=sps, t_epoch=t_epoch, compare=out), open(f'{hw}/timing4.json', 'w'), indent=1)
