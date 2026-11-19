"""Single resident x-plane layout (no passes): lane L owns x planes p % LANES == L, each lane has W step pipelines
(banks keyed by local plane index % W, and (y&1, z&1)).
x-major event: one step per x plane -> lane cycles = ceil(steps in lane / W) (consecutive local planes differ mod W).
y-major event: step j at y_j touches x columns cu_j, cu_j+1 (2 voxels each, z pair); two consecutive steps in the same
column differ in y parity -> one pipeline does 2 half-steps of one column per cycle.
lane cycles = max over the W bank sets of ceil(half-steps in that set / 2)  (half-step = one column of one step).
Every event costs at least 1 cycle in every lane (token)."""
import os, sys, json
import numpy as np
exec(open('speed_model_tof.py', encoding='utf-8').read().split('def lane_work_il')[0])
GPU_SUB = 0.0098 + 0.0351
LANES = 32
# x-major: planes along x are the step planes; y-major: columns from u (= x index) along the steps
Pidx = np.arange(max(NX, NY))[None, :]


def model(W):
    tot = np.zeros(LANES)
    # x-major events
    sel = ax == 0
    ins = inside[sel][:, :NX]
    cnt = np.zeros((ins.shape[0], LANES), np.int32)
    for p in range(NX):
        cnt[:, p % LANES] += ins[:, p]
    tot += (-(-cnt // W)).sum(0)
    # y-major events: columns cu_j and cu_j + 1 for active steps
    sel = ax == 1
    ins = inside[sel][:, :NY]
    uu = u[sel][:, :NY]
    cu = np.floor(uu).astype(np.int64)
    n = ins.shape[0]
    B = 20000
    for i0 in range(0, n, B):
        a = ins[i0:i0 + B]; c = cu[i0:i0 + B]
        hs = np.zeros((a.shape[0], LANES, W), np.int32)       # half-steps per lane per bank set
        for off in (0, 1):
            col = c + off
            ok = a & (col >= 0) & (col < NX)
            lane = np.where(ok, col % LANES, 0)
            bset = np.where(ok, (col // LANES) % W, 0)
            idx = np.nonzero(ok)
            np.add.at(hs, (idx[0], lane[idx], bset[idx]), 1)
        cyc = (-(-hs // 2)).max(2)
        tot += cyc.sum(0)
    nev = ins.shape[0]; return max(tot.max(), len(ev) / 1.0) / M, tot.mean() / M


res = {}
for W in (1, 2, 4):
    mx, mean = model(W)
    for f in (150e6, 200e6):
        t = 2 * mx / f
        res[f'W{W}_{int(f / 1e6)}MHz'] = dict(cycles_fwd=float(mx), balance=float(mean / mx), t_sub_ms=t * 1e3, x_gpu=GPU_SUB / t)
        print(f'resident + token skip, 32 lanes, W {W}, {f / 1e6:.0f} MHz: {mx / 1e3:.0f} k cycles/subset fwd (balance {mean / mx:.3f})'
              f' -> fwd+back {t * 1e3:.2f} ms, {GPU_SUB / t:.2f}x GPU projection')
json.dump(res, open(f'{LM}/resident_skip_model_nsig{NSIG:g}.json', 'w'), indent=1)
