"""Slab-partitioned projector: per-lane load and throughput with a bounded reorder window.
Each lane owns a slab of planes along the ray's principal transaxial axis; Joseph steps are clipped to the image box."""
import sys, numpy as np
d = np.load(sys.argv[1]); NE = int(sys.argv[2]) if len(sys.argv) > 2 else 40000
nz, ny, nx = [int(v) for v in d['img_shape']]; vox = d['vox'].astype(np.float64)
shape = np.array([nz, ny, nx])
rng = np.random.default_rng(0); idx = rng.permutation(len(d['xs']))[:NE]
xs, xe = d['xs'][idx].astype(np.float64), d['xe'][idx].astype(np.float64)
org = -(shape - 1) / 2 * vox
lo_b, hi_b = org - vox / 2, org + (shape - 1) * vox + vox / 2
dv = xe - xs
with np.errstate(divide='ignore', invalid='ignore'):
    ta, tb = (lo_b - xs) / dv, (hi_b - xs) / dv
tin = np.where(dv != 0, np.minimum(ta, tb), -np.inf).max(1)
tout = np.where(dv != 0, np.maximum(ta, tb), np.inf).min(1)
tin, tout = np.clip(tin, 0, 1), np.clip(tout, 0, 1)
ok = tout > tin
A, B = xs + tin[:, None] * dv, xs + tout[:, None] * dv
ax = np.argmax(np.abs(dv[:, 1:]) / vox[1:], 1) + 1
print(f'image {nz}x{ny}x{nx}; events {NE}; rays hitting image {ok.mean():.3f}')

def steps_per_slab(N):
    S = np.zeros((NE, N))
    for a in (1, 2):
        m = (ax == a) & ok; L = shape[a]
        p0 = (A[m, a] - org[a]) / vox[a]; p1 = (B[m, a] - org[a]) / vox[a]
        lo = np.clip(np.ceil(np.minimum(p0, p1)), 0, L - 1); hi = np.clip(np.floor(np.maximum(p0, p1)), 0, L - 1)
        e = np.linspace(0, L, N + 1)
        for k in range(N):
            S[m, k] = np.clip(np.minimum(hi + 1, e[k + 1]) - np.maximum(lo, e[k]), 0, None)
    return S

OVH = 2  # cycles per (event, lane) segment
S1 = steps_per_slab(1)[:, 0]
print(f'mean Joseph steps per event {S1[ok].mean():.1f}')
for N in (8, 16, 32):
    raw = steps_per_slab(N)
    touched = (raw > 0).sum(1)
    S = np.where(raw > 0, raw + OVH, 0.0)
    useful = raw.sum()
    tot = S.sum(0)
    print(f'N={N:2d}: slabs touched per event {touched[ok].mean():.2f}; whole-run lane balance {tot.mean()/tot.max():.3f}')
    for W in (16, 64, 256):
        fin = np.zeros((NE, N)); prev = np.zeros(N)
        for e in range(NE):
            gate = fin[e - W].max() if e >= W else 0.0
            prev = np.maximum(prev, gate) + S[e]
            fin[e] = prev
        T = fin[-1].max()
        print(f'   W={W:3d}: {useful/T:5.2f} useful steps/cycle (ideal {N}); efficiency {useful/T/N:.3f}')
