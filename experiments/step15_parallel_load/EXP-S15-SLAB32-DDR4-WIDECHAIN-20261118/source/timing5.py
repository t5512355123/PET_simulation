"""EXP-S15 timing: event passes, image load and accumulator readout over DDR (all measured on the board, rep 1 vs rep N),
then FPGA vs GPU to the PETRIC threshold (Esser2) with the measured voxel unit (EXP-S11).
Usage: python3 timing5.py <hw dir> <rep> <f_MHz> <P_total_W> <P_static_W>"""
import re, sys, json
hw, REP, F, P, PS = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
meta = dict(l.split() for l in open(f'{hw}/meta.txt'))
log = open(f'{hw}/timing5.log').read()
d = lambda a, b: (int(b) - int(a)) * 1e-3 / (REP - 1)
t_ev, it_ev = 0.0, 0
for p, kind, n, a, b in re.findall(r'TIMING pass (\d) (\w+) tokens (\d+) rep1 (\d+) ms rep\d+ (\d+) ms', log):
    t = d(a, b); it = int(meta[f'pass{p}_{kind}_maxlane'])
    print(f'pass {p} {kind:4s}: {t * 1e3:.4f} ms = {t * F * 1e6:.0f} cycles, busiest lane {it} -> {t * F * 1e6 / it:.3f} cycles/iteration')
    t_ev += t; it_ev += it
w = {name: (int(nw), d(a, b)) for name, nw, a, b in re.findall(r'TIMING wide (\w+) words (\d+) rep1 (\d+) ms rep\d+ (\d+) ms', log)}
for name, (nw, t) in w.items():
    print(f'wide {name}: {nw} words ({nw * 64 / 1e6:.2f} MB) in {t * 1e3:.4f} ms = {nw / (t * F * 1e6):.3f} words/cycle, '
          f'{nw * 64 / t / 1e9:.2f} GB/s')
t_io = 4 * w['load'][1] + 4 * w['read'][1]
ne, steps = int(meta['events']), int(meta['real_steps'])
NEV = 2601282
t_epoch = t_ev / ne * NEV
print(f'events: 4 passes forward + back {t_ev * 1e3:.4f} ms for {ne} events -> {2 * steps / t_ev / 1e9:.3f} G samples/s; '
      f'one projection epoch {t_epoch:.4f} s')
print(f'image/accumulator transfer per subset (4 loads + 4 reads, measured): {t_io * 1e3:.2f} ms '
      f'(EXP-S13 serial chain 67.7 ms; per-lane model 2.12 ms)')
t_vox, Pv, Pvs = 0.01577, 8.61, 6.10
gpu_ep, gpu_W = 8.62 / 18.375, 86.4
Pt = P + (Pv - Pvs)
out = {}
for name, ep, passes in (('time 1 (offline, competition definition)', 18.375, 158), ('time 2 (online Br 64/64, after last event)', 1.5, 15)):
    print(f'{name}: GPU {ep * gpu_ep:.2f} s / {ep * gpu_ep * gpu_W:.0f} J')
    for V in (1, 4):
        tp, tv, tt = ep * t_epoch, passes * t_vox / V, ep * 8 * t_io
        t = tp + tv + tt
        print(f'   FPGA slab32 + DDR wide chain + voxel V={V}: {t:.2f} s (projection {tp:.2f} + voxel {tv:.2f} + transfer {tt:.2f})'
              f' / {t * Pt:.0f} J at {Pt:.1f} W')
        out[f'{name} V={V}'] = dict(t_fpga=t, E_fpga=t * Pt, t_proj=tp, t_vox=tv, t_io=tt, t_gpu=ep * gpu_ep, E_gpu=ep * gpu_ep * gpu_W)
json.dump(dict(t_events=t_ev, t_io_subset=t_io, wide={k: dict(words=v[0], t=v[1]) for k, v in w.items()}, t_epoch=t_epoch,
               P_W=P, compare=out), open(f'{hw}/timing5.json', 'w'), indent=1)
