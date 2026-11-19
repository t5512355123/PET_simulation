"""W-wide interleaved lanes: lane L owns planes p with p % LANES == L (inside a pass); its banks are split by
(local plane index) % W, so up to W local steps of one event run in one cycle. Lane cycles per event =
max(1, ceil(local steps / W)). Time per subset = sum over passes of the busiest lane (forward; back the same)."""
import os, sys, json
import numpy as np
exec(open('speed_model_tof.py', encoding='utf-8').read().split('def lane_work_il')[0])   # geometry: inside, ax, M, S_sub
GPU_SUB = 0.0098 + 0.0351          # measured GPU forward + back per subset (D690, 383,867 events)
res = {}


def cycles(lanes, W, passes=2, nsig_inside=None):
    ins_all = inside if nsig_inside is None else nsig_inside
    tot = 0
    for a in (0, 1):
        sel = ax == a
        Npl = NY if a == 1 else NX
        edges = np.linspace(0, Npl, passes + 1).astype(int)
        ins = ins_all[sel][:, :Npl]
        for h in range(passes):
            sub = ins[:, edges[h]:edges[h + 1]]
            sub = sub[sub.any(1)]
            cnt = np.zeros((sub.shape[0], lanes), np.int32)
            for j in range(sub.shape[1]):
                cnt[:, j % lanes] += sub[:, j]
            c = np.maximum(1, -(-cnt // W))
            tot += c.sum(0).max()
    return tot / M


for lanes in (32,):
    for W in (1, 2, 4):
        c = cycles(lanes, W)
        for f in (150e6, 200e6):
            t_sub = 2 * c / f
            res[f'L{lanes}_W{W}_{int(f / 1e6)}MHz'] = dict(cycles_fwd=float(c), t_sub_ms=t_sub * 1e3, x_gpu_projection=GPU_SUB / t_sub)
            print(f'lanes {lanes} W {W} {f / 1e6:.0f} MHz: {c / 1e3:.0f} k cycles per subset forward -> fwd+back {t_sub * 1e3:.2f} ms '
                  f'(GPU {GPU_SUB * 1e3:.1f} ms, {GPU_SUB / t_sub:.2f}x)')
json.dump(res, open(f'{LM}/wide_model_nsig{NSIG:g}.json', 'w'), indent=1)
