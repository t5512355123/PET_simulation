"""EXP-S17 input: TOF list-mode events -> hardware event format, and a numpy model of the hardware TOF Joseph step
loop checked against parallelproj (GPU).
Hardware event: axis (0: x planes, 1: y planes), first plane i0, n steps, u0 du v0 dv (fixed point FRAC, index units),
TOF: d0 = signed distance (mm) of the first sample from the TOF bin centre along the stepping direction, dd = mm per
plane step; per-step TOF weight = tofk(d) = 0.5 * (erf((d + W/2) / (sqrt2 sigma)) - erf((d - W/2) / (sqrt2 sigma))),
zero for |d| > NSIG * sigma + W/2 (parallelproj truncation, to be confirmed by the check).
Planes: inside the image box (voxel edges, as EXP-S13) AND inside the TOF window.
Usage (env pp): python prep_tof.py <dataset> <out dir> <first event> <n events> [nsig]"""
import json, os, sys
import numpy as np
from math import erf, sqrt

DS, OUT, E0, NE = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
NSIG = float(sys.argv[5]) if len(sys.argv) > 5 else 5.0
os.environ['DS'] = DS
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lmpsv'))
import tofcore                                                              # noqa: E402
FRAC = 20
S = float(1 << FRAC)
LM = f'D:/PET/data/list_mode/petric2/{DS}'
os.makedirs(OUT, exist_ok=True)
x, vs = tofcore.read_hv(f'D:/PET/data/sinogram/petric2/{DS}/OSEM_image.hv')
NZ, NY, NX = x.shape
assert NX == NY and abs(vs[1] - vs[2]) < 1e-6
org = -(np.array(x.shape) - 1) / 2 * vs
W, SIG, NT, SGN = tofcore.TOF_W, tofcore.TOF_SIGMA, tofcore.NTOF, tofcore.TOF_SIGN
HALF = NSIG * SIG + (W / 2 if os.environ.get('HALFW', '0') == '1' else 0.0)
ev = np.load(f'{LM}/events.npy')[E0:E0 + NE]
lors = np.load(f'{LM}/lors_all.npy', mmap_mode='r')
L = np.asarray(lors[ev['lor']]).astype(np.float64)
P1, P2 = L[:, 0], L[:, 1]
p1, p2 = (P1 - org) / vs, (P2 - org) / vs                                 # index coordinates (z, y, x)
d = p2 - p1
ax = (np.abs(d[:, 1]) > np.abs(d[:, 2])).astype(np.int64)
zdom = np.abs(d[:, 0]) * vs[0] > np.maximum(np.abs(d[:, 1]), np.abs(d[:, 2])) * vs[2]   # physical z dominance
k_main = np.where(ax == 1, 1, 2); k_u = np.where(ax == 1, 2, 1)
idx = np.arange(len(ev))
dmain = d[idx, k_main]
sgn = np.sign(dmain); sgn[sgn == 0] = 1
# step along increasing plane index; parameter t along p1 -> p2: plane p at t = (p - p1_main) / dmain
lenmm = np.linalg.norm(P2 - P1, axis=1)
# TOF bin centre along p1 -> p2 (mm from p1): pp index = NT//2 + SGN * k -> centre = L/2 + SGN * k * W
sc = lenmm / 2 + SGN * ev['tof'].astype(np.float64) * W
P = np.arange(NX)[None, :]
t = (P - p1[idx, k_main][:, None]) / dmain[:, None]
U = p1[idx, k_u][:, None] + t * d[idx, k_u][:, None]
Vz = p1[:, 0:1] + t * d[:, 0:1]
smm = t * lenmm[:, None]
box = (U > -0.5) & (U < NX - 0.5) & (Vz > -0.5) & (Vz < NZ - 0.5) & (t >= 0) & (t <= 1)
tofw = np.abs(smm - sc[:, None]) <= HALF
inside = box & tofw & ~zdom[:, None]
has = inside.any(1)
a_p = np.where(has, inside.argmax(1), 0)
b_p = np.where(has, NX - 1 - inside[:, ::-1].argmax(1), -1)
n = np.where(has, b_p - a_p + 1, 0)
assert np.all(inside.sum(1)[has] == n[has])
du = d[idx, k_u] / dmain; dv = d[:, 0] / dmain
u0 = p1[idx, k_u] + (a_p - p1[idx, k_main]) * du
v0 = p1[:, 0] + (a_p - p1[idx, k_main]) * dv
s0 = (a_p - p1[idx, k_main]) / dmain * lenmm                                 # mm from p1 at the first plane
dd = lenmm / dmain                                                           # mm per +1 plane (signed)
d0 = s0 - sc
mw = np.sqrt(1 + du ** 2 + (dv * vs[0] / vs[2]) ** 2)                       # step length in units of the x voxel size
keep = np.nonzero(has)[0]
dt = np.dtype([('i0', '<i2'), ('na', '<i2'), ('u0', '<i4'), ('v0', '<i4'), ('du', '<i4'), ('dv', '<i4'),
               ('d0', '<f4'), ('dd', '<f4'), ('mw', '<f4'), ('y', '<f4'), ('a', '<f4'), ('pad', '<f4')])
hw = np.zeros(keep.size, dt)
hw['i0'] = a_p[keep]; hw['na'] = (n[keep] | (ax[keep] << 15)).astype(np.int32).astype(np.int16)
hw['u0'] = np.round(u0[keep] * S); hw['v0'] = np.round(v0[keep] * S)
hw['du'] = np.round(du[keep] * S); hw['dv'] = np.round(dv[keep] * S)
hw['d0'] = d0[keep]; hw['dd'] = dd[keep]; hw['mw'] = mw[keep]; hw['y'] = 1.0; hw['a'] = ev['a'][keep]
hw.tofile(f'{OUT}/ev_hw.bin')
x.astype('<f4').tofile(f'{OUT}/img.bin')
np.save(f'{OUT}/keep_index.npy', keep + E0)


def tofk(dist):
    a = (dist + W / 2) / (sqrt(2) * SIG); b = (dist - W / 2) / (sqrt(2) * SIG)
    from scipy.special import erf as verf
    return np.where(np.abs(dist) <= HALF, 0.5 * (verf(a) - verf(b)), 0.0)


def fwd_hw(e, img):
    """numpy model of the hardware step loop (double precision, from the fixed-point / float parameters)"""
    F = np.zeros(e.size)
    for i, r in enumerate(e):
        a_ = (int(r['na']) >> 15) & 1; nn = int(r['na']) & 0x7fff
        k = np.arange(nn)
        uu = (r['u0'] + k * np.int64(r['du'])) / S; vv = (r['v0'] + k * np.int64(r['dv'])) / S
        p = r['i0'] + k
        tw = tofk(r['d0'] + k * r['dd'])
        iu, iv = np.floor(uu).astype(int), np.floor(vv).astype(int)
        fu, fv = uu - iu, vv - iv
        acc = 0.0
        for du_, wu in ((0, 1 - fu), (1, fu)):
            for dz_, wz in ((0, 1 - fv), (1, fv)):
                cu, cz = iu + du_, iv + dz_
                ok = (cu >= 0) & (cu < NX) & (cz >= 0) & (cz < NZ)
                xx = np.where(a_ == 1, cu, p); yy = np.where(a_ == 1, p, cu)
                val = np.where(ok, img[np.clip(cz, 0, NZ - 1), np.clip(yy, 0, NY - 1), np.clip(xx, 0, NX - 1)], 0.0)
                acc += np.sum(wu * wz * val * tw)
        F[i] = acc * r['mw']
    return F


if os.environ.get('NOCHECK') == '1':
    print(dict(kept=int(keep.size), steps_mean=float(n[keep].mean()), z_dominant=int(zdom.sum())))
    sys.exit(0)
import cupy as cp
import parallelproj_core as ppc
# parallelproj reference on the same events
xs = cp.asarray(P1[keep].astype(np.float32)); xe = cp.asarray(P2[keep].astype(np.float32))
tb = cp.asarray((NT // 2 + SGN * ev['tof'][keep].astype(np.int32)).astype(np.int16))
Fpp = cp.zeros(keep.size, cp.float32)
ppc.joseph3d_tof_lm_fwd(xs, xe, cp.asarray(x), cp.asarray(org.astype(np.float32)), cp.asarray(vs), Fpp, W,
                        cp.asarray(np.array([SIG], np.float32)), cp.asarray(np.array([0.0], np.float32)), tb, NT, NSIG)
Fpp = (tofcore.np.float32(1.0 / vs[2]) * Fpp).get().astype(np.float64)
nchk = min(2000, keep.size)
Fhw = fwd_hw(hw[:nchk], x.astype(np.float64))
rel = np.abs(Fhw - Fpp[:nchk]) / np.maximum(np.abs(Fpp[:nchk]), 1e-12)
info = dict(dataset=DS, first=E0, n=NE, kept=int(keep.size), z_dominant=int(zdom.sum()), nsig=NSIG,
            steps_mean=float(n[keep].mean()), F_rel_max=float(rel.max()), F_rel_median=float(np.median(rel)),
            F_rel_p99=float(np.percentile(rel, 99)), n_bad_1e3=int((rel > 1e-3).sum()),
            F_abs_over_medianF_max=float((np.abs(Fhw - Fpp[:nchk]) / np.median(Fpp[:nchk])).max()),
            n_bad_rel_F_nontiny=int(((rel > 1e-3) & (Fpp[:nchk] > 1e-3 * np.median(Fpp[:nchk]))).sum()))
json.dump(info, open(f'{OUT}/prep.json', 'w'), indent=1)
np.save(f'{OUT}/Fpp.npy', Fpp)
print(json.dumps(info, indent=1))
if info['n_bad_1e3']:
    bad = np.nonzero(rel > 1e-3)[0][:5]
    for i in bad:
        print(i, 'rel', rel[i], 'hw', Fhw[i], 'pp', Fpp[i], 'axis', (int(hw[i]['na']) >> 15) & 1, 'n', int(hw[i]['na']) & 0x7fff,
              'd0', hw[i]['d0'], 'dd', hw[i]['dd'])
