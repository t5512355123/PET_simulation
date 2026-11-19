"""R2: both main-axis copies resident on chip (x-copy and y-copy), lane L owns planes p % LANES == L of each copy,
W pipelines per lane (banks keyed by local plane index % W). Every event passes the chain once and works in the copy
of its main axis; lane cycles = ceil(local steps / W); a forwarder passes tokens without local work (chain: 1 token
per cycle -> at least #events cycles). Also reports on-chip memory for fp16 IMG + fp32 ACC (FOV only)."""
import os, sys, json
import numpy as np
exec(open('speed_model_tof.py', encoding='utf-8').read().split('def lane_work_il')[0])
GPU_SUB = 0.0098 + 0.0351
GPU_TOTAL, N_SUBPROJ, N_UPD = 2.39, 61, 40
res = {}
for LANES in (32, 48):
    for W in (2, 4):
        tot = np.zeros(LANES)
        for a in (0, 1):
            Npl = NY if a == 1 else NX
            ins = inside[ax == a][:, :Npl]
            cnt = np.zeros((ins.shape[0], LANES), np.int32)
            for p in range(Npl):
                cnt[:, p % LANES] += ins[:, p]
            tot += (-(-cnt // W)).sum(0)
        cyc = max(tot.max(), len(ev)) / M
        for f in (150e6, 200e6):
            t = 2 * cyc / f
            proj_total = N_SUBPROJ * t
            res[f'L{LANES}_W{W}_{int(f / 1e6)}'] = dict(cycles=float(cyc), t_sub_ms=t * 1e3, x_gpu_proj=GPU_SUB / t, proj_total_s=proj_total)
            print(f'R2 lanes {LANES} W {W} {f / 1e6:.0f} MHz: {cyc / 1e3:.0f} k cycles/subset fwd (balance {tot.mean() / tot.max():.3f}) -> '
                  f'fwd+back {t * 1e3:.2f} ms ({GPU_SUB / t:.2f}x GPU); 61 subset projections {proj_total * 1e3:.0f} ms; '
                  f'budget left for 40 voxel updates at 5x: {(GPU_TOTAL / 5 - proj_total) / N_UPD * 1e3:.2f} ms each')
fov = np.load(f'{LM}/fov_mask.npy') > 0
nv = int(fov.sum())
blk32 = 2 * nv / 512; blk16 = 2 * nv / 1024
print(f'FOV voxels {nv}; M20K blocks: ACC fp32 x2 copies {blk32:.0f}, IMG fp16 x2 copies {blk16:.0f}, total {blk32 + blk16:.0f} of 11721')
res['m20k'] = dict(fov_voxels=nv, acc_blocks=blk32, img_blocks=blk16)
json.dump(res, open(f'{LM}/r2_model_nsig{NSIG:g}.json', 'w'), indent=1)
