"""Online (event-driven) BSREM vs PETRIC BSREM vs PETRIC2 winner psv, same projector, PETRIC metrics.
Non-TOF datasets. CPU parallelproj (joseph3d_fwd/back on event LORs only; the y=0 part is the subset sensitivity).
Usage: python -I algo_study.py <dataset_dir> <headers.json> <dataset> <out_prefix> [ref_epochs] [run_epochs]
"""
import json
import math
import os
import re
import sys
import time

import numpy as np
import parallelproj_core as ppc
from scipy.ndimage import gaussian_filter

DDIR, TABLE, DS, OUT = sys.argv[1:5]
REF_EP = int(sys.argv[5]) if len(sys.argv) > 5 else 150
RUN_EP = int(sys.argv[6]) if len(sys.argv) > 6 else 40
r = [x for x in json.load(open(TABLE)) if x['dataset'] == DS][0]
d = os.path.join(DDIR, DS)
assert r['tof_bins'] == 1, 'non-TOF only'


def kv(path):
    out = {}
    for line in open(path, errors='replace'):
        if ':=' in line:
            k, v = line.split(':=', 1)
            out[' '.join(k.strip().lstrip('!').lower().split())] = v.strip()
    return out


ints = lambda s: [int(x) for x in re.findall(r'-?\d+', s)]
h = kv(os.path.join(d, 'prompts.hs'))
V, T = r['views'], r['tangential']
axial = ints(h['matrix size [2]'])
A = sum(axial)
nz, ny, nx = r['img_shape']
vox = np.array(r['voxel_mm'], np.float32)
origin = (-(np.array([nz, ny, nx]) - 1) / 2 * vox).astype(np.float32)

# ---- exact STIR geometry and data (to_array order: sinograms x views x tangential) ----
import stir
LOR_ALL = np.load(os.path.join(os.path.dirname(OUT), DS + '_lors.npy'), mmap_mode='r')  # (S, V, T, 2, 3)
rd = lambda n: np.asarray(stir.ProjData.read_from_file(os.path.join(d, n)).to_array().as_array())[0].astype(np.float32)
y, m, add = rd('prompts.hs'), rd('mult_factors.hs'), rd('additive_term.hs')
S_, V, T = y.shape
A = S_
R = 1000.0


def lors(view_idx):
    sub = LOR_ALL[:, view_idx]  # (S, nv, T, 2, 3)
    sub = np.moveaxis(np.asarray(sub), 1, 0)  # (nv, S, T, 2, 3)
    return np.ascontiguousarray(sub[..., 0, :].reshape(-1, 3)), np.ascontiguousarray(sub[..., 1, :].reshape(-1, 3))


y = np.ascontiguousarray(np.moveaxis(y, 1, 0))   # (V, S, T) so that y[vi] selects views
m = np.ascontiguousarray(np.moveaxis(m, 1, 0))
add = np.ascontiguousarray(np.moveaxis(add, 1, 0))
img_rd = lambda n: np.fromfile(os.path.join(d, n), dtype='<f4').reshape(nz, ny, nx)
osem, kappa = img_rd('OSEM_image.v'), img_rd('kappa.v')
pf_file = os.path.join(d, 'penalisation_factor.txt')
beta = float(open(pf_file).read()) if os.path.exists(pf_file) else 1 / 700
ref_official = img_rd('PETRIC/reference_image.v')
voi = {f[4:-2]: img_rd('PETRIC/' + f) > 0 for f in os.listdir(os.path.join(d, 'PETRIC')) if f.startswith('VOI_') and f.endswith('.v')}
fov = np.zeros((nz, ny, nx), bool)
yy, xx = np.mgrid[:ny, :nx]
fov[:] = (((yy - (ny - 1) / 2) * vox[1]) ** 2 + ((xx - (nx - 1) / 2) * vox[2]) ** 2) < (min(ny * vox[1], nx * vox[2]) / 2) ** 2
org, vs = origin, vox


C_STIR = np.float32(1.0 / vox[2])  # STIR line integrals are in transaxial-voxel units (checked against the official reference)


def fwd(xs, xe, img):
    o = np.zeros(xs.shape[0], np.float32)
    ppc.joseph3d_fwd(xs, xe, img, org, vs, o)
    return o * C_STIR


def back(xs, xe, val):
    o = np.zeros((nz, ny, nx), np.float32)
    ppc.joseph3d_back(xs, xe, o, org, vs, np.ascontiguousarray(val, dtype=np.float32))
    return o * C_STIR


# ---- subsets (staggered views) and event lists (y > 0 only) ----
def make_subsets(M):
    subs = []
    for k in range(M):
        vi = np.arange(k, V, M)
        xs, xe = lors(vi)
        yk, mk, ak = (q[vi].reshape(-1) for q in (y, m, add))
        nzi = np.nonzero(yk > 0)[0]
        sens = back(xs, xe, mk)  # subset sensitivity A_k^T m_k (dense, once)
        subs.append({'xs': np.ascontiguousarray(xs[nzi]), 'xe': np.ascontiguousarray(xe[nzi]), 'y': yk[nzi], 'm': mk[nzi],
                     'a': ak[nzi], 'sens': sens, 'nnz': nzi.size})
    return subs


# ---- RDP (STIR / Speedy rdp.py definition), gradient and diagonal Hessian ----
OFF = [(a, b, c_) for a in (-1, 0, 1) for b in (-1, 0, 1) for c_ in (-1, 0, 1) if (a, b, c_) != (0, 0, 0)]
eps_rdp = float(osem.max()) * 1e-3


def shifted(arr, o):
    out = np.zeros_like(arr)
    src = tuple(slice(max(0, k), arr.shape[i] + min(0, k)) for i, k in enumerate(o))
    dst = tuple(slice(max(0, -k), arr.shape[i] + min(0, -k)) for i, k in enumerate(o))
    out[dst] = arr[src]
    return out  # out[j] = arr[j + o] (0 outside)


def rdp_grad_hess(x, want_h=False):
    g = np.zeros_like(x)
    hd = np.zeros_like(x) if want_h else None
    for o in OFF:
        xk = shifted(x, o)
        kk = shifted(kappa, o)
        valid = shifted(np.ones_like(x), o)
        w = vox[2] / np.sqrt(sum((o[i] * vox[i]) ** 2 for i in range(3))) * kappa * kk * valid
        dd = x - xk
        ss = x + xk
        phi_ = ss + 2.0 * np.abs(dd) + eps_rdp
        g += w * dd * (2 * phi_ - (dd + 2.0 * np.abs(dd))) / (phi_ * phi_)
        if want_h:
            t = ss - dd + eps_rdp
            hd += w * 2 * t * t / phi_ ** 3
    return g, hd


try:
    import numba

    @numba.njit(parallel=True, fastmath=False, cache=True)
    def _rdp_nb(x, kap, vz, vy, vx, eps, want_h, g, hd):
        nz_, ny_, nx_ = x.shape
        for iz in numba.prange(nz_):
            for iy in range(ny_):
                for ix in range(nx_):
                    xj = x[iz, iy, ix]
                    kj = kap[iz, iy, ix]
                    acc = 0.0
                    acch = 0.0
                    for oz in (-1, 0, 1):
                        jz = iz + oz
                        if jz < 0 or jz >= nz_:
                            continue
                        for oy in (-1, 0, 1):
                            jy = iy + oy
                            if jy < 0 or jy >= ny_:
                                continue
                            for ox in (-1, 0, 1):
                                jx = ix + ox
                                if (oz == 0 and oy == 0 and ox == 0) or jx < 0 or jx >= nx_:
                                    continue
                                xk = x[jz, jy, jx]
                                w = vx / np.sqrt((oz * vz) ** 2 + (oy * vy) ** 2 + (ox * vx) ** 2) * kj * kap[jz, jy, jx]
                                dd = xj - xk
                                ss = xj + xk
                                ph = ss + 2.0 * abs(dd) + eps
                                acc += w * dd * (2 * ph - (dd + 2.0 * abs(dd))) / (ph * ph)
                                if want_h:
                                    t = ss - dd + eps
                                    acch += w * 2 * t * t / (ph * ph * ph)
                    g[iz, iy, ix] = acc
                    if want_h:
                        hd[iz, iy, ix] = acch

    _rdp_np = rdp_grad_hess

    def rdp_grad_hess(x, want_h=False):
        g = np.zeros_like(x)
        hd = np.zeros_like(x)
        _rdp_nb(np.ascontiguousarray(x, np.float32), kappa, float(vox[0]), float(vox[1]), float(vox[2]), eps_rdp, want_h, g, hd)
        return g, (hd if want_h else None)

    _t = np.random.default_rng(0).random((8, 9, 10)).astype(np.float32)
    _k = kappa
    kappa = np.random.default_rng(1).random((8, 9, 10)).astype(np.float32) + 0.5
    _a, _ah = _rdp_np(_t, True)
    _b, _bh = rdp_grad_hess(_t, True)
    assert np.allclose(_a, _b, rtol=1e-4, atol=1e-6) and np.allclose(_ah, _bh, rtol=1e-4, atol=1e-6), 'numba RDP mismatch'
    kappa = _k
    print('numba RDP enabled (checked against numpy)', flush=True)
except ImportError:
    pass


def lik_grad(sub, x):
    f = fwd(sub['xs'], sub['xe'], x)
    yh = np.maximum(sub['m'] * (f + sub['a']), 1e-8)  # SIRF model: mult * (A x + additive)
    return back(sub['xs'], sub['xe'], sub['m'] * sub['y'] / yh) - sub['sens']


# ---- metrics (PETRIC: relative to background mean of the reference) ----
def metrics(x, ref):
    bg = ref[voi['background']].mean()
    wo, bgm = voi['whole_object'], voi['background']
    out = {'RMSE_whole_object': float(np.sqrt(((x[wo] - ref[wo]) ** 2).mean()) / bg),
           'RMSE_background': float(np.sqrt(((x[bgm] - ref[bgm]) ** 2).mean()) / bg)}
    for k, msk in voi.items():
        if k not in ('background', 'whole_object'):
            out['AEM_VOI_' + k] = float(abs(x[msk].mean() - ref[msk].mean()) / bg)
    return out


THR = {'AEM_VOI': 0.005, 'RMSE_whole_object': 0.01, 'RMSE_background': 0.01}
def _thr_key(k):
    return 'AEM_VOI' if k.startswith('AEM_VOI') else k


passes = lambda mt: all(v <= THR[_thr_key(k)] for k, v in mt.items() if k.startswith(('AEM', 'RMSE')))


# ---- algorithms ----
def psv(subs, x0, epochs, ref=None, log=None):
    M = len(subs)
    sens_full = sum(sb['sens'] for sb in subs)
    sens_full = np.maximum(sens_full, 1e-6)

    def precond(x):
        xs_ = gaussian_filter(x, [5.0 / 2.355 / v for v in vox])
        _, hd = rdp_grad_hess(xs_, True)
        return fov * x / (sens_full + 2.0 * beta * hd * x)

    x = x0.copy()
    P = precond(x)
    upd = 0
    gtab = [None] * M
    gsum = None
    hist = []
    for ep in range(epochs):
        if ep % 2 == 0:  # full gradient epoch
            gp = rdp_grad_hess(x)[0] * (beta / M)
            gtab = [lik_grad(sb, x) - gp for sb in subs]
            gsum = sum(gtab)
        order = np.random.default_rng(ep).permutation(M)
        for j, k in enumerate(order):
            if ep == 1 and j == 0:
                P = precond(x)
            if upd == 4:
                P = precond(x)
            if ep % 2 == 0 and j == 0:
                g = gsum
            else:
                g = (lik_grad(subs[k], x) - rdp_grad_hess(x)[0] * (beta / M) - gtab[k]) * M + gsum
            step = 3.5 / (1 + 0.01 * upd)
            x = np.maximum(x + step * P * g, 0)
            upd += 1
            if ref is not None:
                mt = metrics(x, ref)
                mo = {'OFF_' + k: v for k, v in metrics(x, ref_official).items()}
                hist.append({'update': upd, 'epoch': ep + (j + 1) / M, **mt, **mo})
        if log:
            print(f'  psv ep {ep} t={time.time() - T0:.0f}s', flush=True)
    return x, hist


def bsrem(subs, x0, epochs, ref, mode):
    """mode 'petric': SIRF BSREM1 (step 0.3/(1+0.01 epoch), precond (x+eps)/avg sens).
       mode 'online': same loop, psv preconditioner (harmonic mean with RDP Hessian), step 1.0/(1+0.05 epoch)."""
    M = len(subs)
    sens_full = np.maximum(sum(sb['sens'] for sb in subs), 1e-6)
    eps_b = float(x0.max()) * 1e-3
    x = x0.copy()
    hist = []
    upd = 0

    def precond(x):
        xs_ = gaussian_filter(x, [5.0 / 2.355 / v for v in vox])
        _, hd = rdp_grad_hess(xs_, True)
        return fov * x / (sens_full + 2.0 * beta * hd * x)

    P = precond(x) if mode == 'online' else None
    for ep in range(epochs):
        order = np.random.default_rng(100 + ep).permutation(M)
        if mode == 'online' and ep in (1, 2):
            P = precond(x)
        for j, k in enumerate(order):
            g = lik_grad(subs[k], x) - rdp_grad_hess(x)[0] * (beta / M)
            if mode == 'petric':
                step = 0.3 / (1 + 0.01 * ep)
                x = np.maximum(x + step * (x + eps_b) * g / (sens_full / M), 0)
            else:
                step = 1.0 / (1 + 0.05 * ep)
                x = np.maximum(x + step * M * P * g, 0)
            upd += 1
            mt = metrics(x, ref)
            mo = {'OFF_' + k: v for k, v in metrics(x, ref_official).items()}
            hist.append({'update': upd, 'epoch': ep + (j + 1) / M, **mt, **mo})
        print(f'  {mode} ep {ep} t={time.time() - T0:.0f}s pass={passes(hist[-1])}', flush=True)
    return x, hist


def first_pass(hist, window=10, prefix=''):
    run = 0
    for i, hrow in enumerate(hist):
        mt = {k[len(prefix):]: v for k, v in hrow.items() if k.startswith(prefix + 'AEM') or k.startswith(prefix + 'RMSE')}
        run = run + 1 if passes(mt) else 0
        if run >= window:
            return hist[i - window + 1]
    return None


T0 = time.time()
M_psv = r['speedy_subsets']
subs_psv = make_subsets(M_psv)
subs_7 = make_subsets(7)
nnz = sum(sb['nnz'] for sb in subs_psv)
print(f'{DS}: views {V}, M_psv {M_psv}, nnz {nnz} ({100 * nnz / (V * A * T):.2f}%), beta {beta:.3g}, setup {time.time() - T0:.0f}s', flush=True)
x0 = gaussian_filter(osem, [6.0 / 2.355 / v for v in vox]).astype(np.float32)
ref_path = OUT + '_ref.npy'
if os.path.exists(ref_path):
    ref = np.load(ref_path)
else:
    ref, _ = psv(subs_psv, x0, REF_EP, None, True)
    np.save(ref_path, ref)
print('own reference vs official reference:', {k: round(v, 4) for k, v in metrics(ref, ref_official).items()}, flush=True)
# convergence check of the reference: compare with 20 more epochs
res = {'dataset': DS, 'nnz': int(nnz), 'M_psv': M_psv, 'beta': beta, 'ref_epochs': REF_EP, 'runs': {}}
if os.path.exists(OUT + '_study.json'):
    res['runs'] = json.load(open(OUT + '_study.json'))['runs']
for name, fn in (('psv', lambda: psv(subs_psv, x0, RUN_EP, ref)), ('bsrem_petric', lambda: bsrem(subs_7, osem.astype(np.float32), RUN_EP, ref, 'petric')),
                 ('bsrem_online', lambda: bsrem(subs_psv, x0, RUN_EP, ref, 'online'))):
    if name in res['runs']:
        print(name, 'already done, skipped', flush=True)
        continue
    t = time.time()
    _, hist = fn()
    fp = first_pass(hist)
    fpo = first_pass(hist, prefix='OFF_')
    res['runs'][name] = {'first_pass_official': fpo, 'first_pass': fp, 'final': hist[-1], 'cpu_s': time.time() - t, 'hist': hist[::max(1, len(hist) // 200)]}
    print(name, 'first pass own-ref:', None if fp is None else (fp['update'], round(fp['epoch'], 2)), '| official ref:', None if fpo is None else (fpo['update'], round(fpo['epoch'], 2)), flush=True)
    print('   final', {k: round(v, 4) for k, v in hist[-1].items()}, flush=True)
    json.dump(res, open(OUT + '_study.json', 'w'), indent=1)
print('done', time.time() - T0)
