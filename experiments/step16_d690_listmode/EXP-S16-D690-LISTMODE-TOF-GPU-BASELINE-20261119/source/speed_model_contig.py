"""EXP-S16 speed model for GE DMI4 TOF list-mode psv on the FPGA vs the measured GPU (1.006 s to threshold, 30 updates).
Per event: principal transaxial axis, Joseph planes inside the image AND inside the TOF window (TOF bin centre
+- (nsig * sigma + bin/2) along the LOR). Slab layout: main axis split into halves (passes), lanes own plane ranges.
Reports steps per subset, per-lane work with and without the per-token overhead, and update time estimates."""
import json, sys
import numpy as np

import os
DS = os.environ.get('DS', 'GE_D690_NEMA_IQ2')
LM = f'D:/PET_DATA/listmode/{DS}'
NSIG = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
PAR = {'GE_DMI4_NEMA_IQ2': ((71, 211, 211), (2.76148, 2.206, 2.206), 25.332462, 375.4, 29, 1.006, 30),
       'GE_D690_NEMA_IQ2': ((47, 201, 201), (3.27, 2.1306, 2.1306), 5 * 89 * 0.299792458 / 2, 550.0, 11, 2.39, 40)}
(NZ, NY, NX), VS, TOF_W, FWHM, NTOF, GPU_T, UPD = PAR[DS]
VS = np.array(VS)
ORG = -(np.array([NZ, NY, NX]) - 1) / 2 * VS
SIG = 0.5 * FWHM * 0.299792458 / 2.354820045
ev = np.load(f'{LM}/events.npy')
lors = np.load(f'{LM}/lors_all.npy', mmap_mode='r')
L = np.asarray(lors[ev['lor']]).astype(np.float64)
p1, p2 = (L[:, 0] - ORG) / VS, (L[:, 1] - ORG) / VS          # index coordinates (z, y, x)
d = p2 - p1
ax = (np.abs(d[:, 1]) > np.abs(d[:, 2])).astype(int)          # 1: y main axis
k = np.where(ax == 1, 1, 2)
dd = d[np.arange(len(d)), k]
length_mm = np.linalg.norm((p2 - p1) * VS, axis=1)
# TOF centre: STIR position tof -> parallelproj index 14 - tof (TOF_SIGN = -1); centre offset from LOR midpoint
# along p1 -> p2 = (idx - 14) * W  => = -tof * W
tc = 0.5 - ev['tof'].astype(np.float64) * TOF_W / length_mm   # fraction along p1 -> p2
half = (NSIG * SIG + TOF_W / 2) / length_mm
t_lo, t_hi = tc - half, tc + half
# principal coordinate along the LOR
c1 = p1[np.arange(len(d)), k]
pa = c1 + np.minimum(t_lo, t_hi) * dd
pb = c1 + np.maximum(t_lo, t_hi) * dd
lo_p = np.ceil(np.minimum(pa, pb)); hi_p = np.floor(np.maximum(pa, pb))
NP = np.where(ax == 1, NY, NX)
lo_p = np.clip(lo_p, 0, NP - 1); hi_p = np.clip(hi_p, -1, NP - 1)
# also clip by the image box in the other two coordinates (approximately: count planes where z, u inside)
P = np.arange(max(NX, NY))[None, :]
frac = (P - c1[:, None]) / dd[:, None]
z = p1[:, 0:1] + frac * d[:, 0:1]
u = np.where(ax[:, None] == 1, p1[:, 2:3] + frac * d[:, 2:3], p1[:, 1:2] + frac * d[:, 1:2])
inside = (P >= lo_p[:, None]) & (P <= hi_p[:, None]) & (z > -0.5) & (z < NZ - 0.5) & (u > -0.5) & (u < NX - 0.5)
steps = inside.sum(1)
full_steps = ((P <= NP[:, None] - 1) & (z > -0.5) & (z < NZ - 0.5) & (u > -0.5) & (u < NX - 0.5)).sum(1)
print(f'events {len(ev)}; steps per event: TOF window ({NSIG} sigma) {steps.mean():.1f}, whole LOR {full_steps.mean():.1f}')
M = 8
S_sub = steps.sum() / M
print(f'Joseph steps per subset {S_sub / 1e6:.2f} M (forward) -> samples per subset (fwd + back) {2 * S_sub / 1e6:.1f} M')


def lane_work_il(lanes, passes_per_axis, overhead):
    """interleaved planes: plane p of a pass -> lane p % lanes"""
    tot = 0
    for a in (0, 1):
        sel = ax == a
        Npl = NY if a == 1 else NX
        edges = np.linspace(0, Npl, passes_per_axis + 1).astype(int)
        ins = inside[sel][:, :Npl]
        for h in range(passes_per_axis):
            p0, p1_ = edges[h], edges[h + 1]
            sub = ins[:, p0:p1_]
            touch = sub.any(1)
            sub = sub[touch]
            cnt = np.zeros((sub.shape[0], lanes), np.int32)
            for j in range(sub.shape[1]):
                cnt[:, j % lanes] += sub[:, j]
            w = np.maximum(1, cnt) if overhead else cnt
            tot += w.sum(0).max()
    return tot / M


def lane_work(lanes, passes_per_axis, overhead):
    """busiest-lane iterations per subset summed over passes (events of each axis in their passes)"""
    tot = 0
    for a in (0, 1):
        sel = ax == a
        Npl = NY if a == 1 else NX
        edges = np.linspace(0, Npl, passes_per_axis + 1).astype(int)
        ins = inside[sel][:, :Npl]
        for h in range(passes_per_axis):
            p0, p1_ = edges[h], edges[h + 1]
            n = p1_ - p0
            le = p0 + (np.arange(lanes + 1) * n) // lanes
            touch = ins[:, p0:p1_].any(1)
            cnt = np.add.reduceat(ins[:, p0:p1_].astype(np.int32), le[:-1] - p0, axis=1)[touch]
            w = np.maximum(1, cnt) if overhead else cnt
            tot += w.sum(0).max()
    return tot / M


out = dict(nsig=NSIG, steps_per_event=float(steps.mean()), steps_full_lor=float(full_steps.mean()), samples_per_subset=2 * S_sub)
for lanes in (32,):
    for pp in (2,):
        for ov in (True, False):
            it = lane_work(lanes, pp, ov)
            eff = S_sub / lanes / it
            out[f'IL{lanes}_p{pp}_{"ovh" if ov else "skip"}'] = dict(busiest_iters_per_subset=float(it), efficiency=float(eff))
            print(f'CONTIGUOUS lanes {lanes:3d}, {pp} passes/axis, token overhead {"yes" if ov else "no "}: busiest-lane iterations per subset '
                  f'(fwd) {it / 1e3:8.1f} k -> efficiency {eff:.3f}; projection per subset at 150/200 MHz: '
                  f'{2 * it / 150e6 * 1e3:.2f} / {2 * it / 200e6 * 1e3:.2f} ms')
json.dump(out, open(f'{LM}/speed_model_contig_nsig{NSIG:g}.json', 'w'), indent=1)
print(f'GPU: {GPU_T / UPD * 1e3:.1f} ms per update on average ({UPD} updates incl. 2 full gradients); target 5x: '
      f'{GPU_T / 5 * 1e3:.0f} ms total, {GPU_T / 5 / UPD * 1e3:.1f} ms per update')
