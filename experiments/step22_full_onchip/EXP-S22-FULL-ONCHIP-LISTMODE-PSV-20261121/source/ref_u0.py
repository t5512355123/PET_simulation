"""EXP-S22 debug: GPU reference of update 0 (full gradient) in hardware formats -> slot-order arrays, compared with
the board read-back (GS, GP, X1). Usage (env pp, LMDIR=clmbin): python ref_u0.py <board dbg dir>"""
import os, sys
os.environ.setdefault('DS', 'GE_D690_NEMA_IQ2'); os.environ.setdefault('TOF_NSIG', '5')
import numpy as np, cupy as cp
sys.path.insert(0, 'C:/Users/t5512/AppData/Local/Temp/claude/9d475279f3617f93/5142366d-c9a0-40dd-a9b5-3424c81b8845/scratchpad/lmpsv')
import tofcore
D = sys.argv[1]
W = os.environ.get('PREPW', 'D:/PET/claude_house/work/r2_fpga/s20')
NZ, L, NT = 47, 40, 5; NSL = NZ * 40000
n = np.arange(NSL); si = n % L; sk = (n // L) % L; sT = (n // (L * L)) % (NT * NT); sz = n // (L * L * NT * NT)
sy = L * (sT // NT) + si; sx = L * (sT % NT) + (si + sk) % L
def q(a):
    u = a.astype(cp.float32).view(cp.uint32)
    return ((u + cp.uint32(0x7fff) + ((u >> 16) & cp.uint32(1))) & cp.uint32(0xffff0000)).view(cp.float32)
P = tofcore.TOFProblem()
x0 = cp.asarray(np.load(f'{W}/x0.npy').astype(np.float32))
s_all = cp.maximum(P.sens, 1e-6)
xs = P.gauss(x0, 5.0)
P0 = q(P.fov * x0 / (s_all + 2.0 * P.prior_diag_hess(xs) * x0))
gp = P.prior_grad(x0)
acc = P.lik_grad(slice(0, P.n_ev), x0, 0.0)
gsum = acc - s_all - gp
x1 = cp.maximum(x0 + 3.5 * P0 * gsum, 0)
ref = {k: cp.asnumpy(v)[sz, sy, sx] for k, v in dict(GS=gsum, GP=gp, X1=x1, ACC=acc, SENS=s_all, P0=P0).items()}
np.savez(os.path.join(D, 'ref_u0.npz'), **ref)
def cmp(name, b, r):
    m = np.abs(r).max(); d = np.abs(b - r)
    print(f'{name}: ref max {m:.4g} mean {r.mean():.4g} | board max {np.abs(b).max():.4g} mean {b.mean():.4g} | max|d|/max {d.max() / m:.3e}'
          f' worst slot {int(d.argmax())} (b {b[d.argmax()]:.4g} r {r[d.argmax()]:.4g}) | frac |d|>1e-2 max {(d > 1e-2 * m).mean():.4f}')
for k in ('GS', 'GP', 'X1'):
    fn = os.path.join(D, f'{k}.bin')
    if os.path.exists(fn):
        cmp(k, np.fromfile(fn, '<f4')[:NSL], ref[k])
b = np.fromfile(os.path.join(D, 'GS.bin'), '<f4')[:NSL] if os.path.exists(os.path.join(D, 'GS.bin')) else None
if b is not None:
    for k in ('ACC', 'SENS', 'GP'):
        r = ref[k]; c = np.dot(b, r) / np.dot(r, r); print(f'GS ~ {c:.4g} * {k} projection')
