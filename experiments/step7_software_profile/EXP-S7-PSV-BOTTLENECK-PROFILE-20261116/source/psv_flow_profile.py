"""Time one psv (PETRIC2 winner) subset update, step by step, with three data layouts.

A. SIRF/STIR layout (what the winner runs): sinograms and images live in host memory (STIR ProjDataInMemory,
   SIRF ImageData). Each projection copies the image to the GPU, projects the subset, and copies the result back;
   the Poisson ratio is computed on the CPU over every bin of the subset (zeros included); the image algebra
   of the SVRG update runs on the CPU. The RDP gradient runs on the GPU (CudaRelativeDifferencePrior) with copies.
B. GPU-resident dense sinogram: same maths, every array stays on the GPU.
C. GPU-resident event-driven: only bins with y > 0 are projected for the ratio term (identical gradient).

Data: PETRIC2 NeuroLF_Esser2 (8 subsets x 16 views, as psv chooses). Projector: parallelproj Joseph (CUDA).
Usage: python -I psv_flow_profile.py <listmode_dir> <dataset_dir> [repeats]
"""
import json
import os
import re
import sys
import time

import numpy as np
import cupy as cp
import parallelproj_core as ppc

LM, SRC = sys.argv[1], sys.argv[2]
REP = int(sys.argv[3]) if len(sys.argv) > 3 else 3
NSUB = 8


def read_hv(path):
    h = open(path, encoding='latin-1').read()
    size = {int(i): int(float(v)) for i, v in re.findall(r'!matrix size \[(\d)\] := ([\d.]+)', h)}
    vox = {int(i): float(v) for i, v in re.findall(r'scaling factor \(mm/pixel\) \[(\d)\] := ([-\d.e+]+)', h)}
    shape = (size[3], size[2], size[1])
    img = np.fromfile(os.path.join(os.path.dirname(path), re.search(r'name of data file := (.+)', h).group(1).strip()), '<f4')
    return img.reshape(shape), np.array([vox[3], vox[2], vox[1]], np.float32)


x_h, vs = read_hv(os.path.join(SRC, 'OSEM_image.hv'))
kappa_h, _ = read_hv(os.path.join(SRC, 'kappa.hv'))
shape = x_h.shape
org = (-(np.array(shape) - 1) / 2 * vs).astype(np.float32)
c = np.float32(1.0 / vs[2])
lors = np.load(os.path.join(LM, 'lors_all.npy'), mmap_mode='r')            # (sumA, V, T, 2, 3)
ymA = np.load(os.path.join(LM, 'sino_y_m_a.npy'), mmap_mode='r')
A_, V, T = lors.shape[:3]
y_all, m_all, a_all = (ymA[i].reshape(A_, V, T) for i in range(3))
orgg, vsg = cp.asarray(org), cp.asarray(vs)

sub = []
for k in range(NSUB):
    views = np.arange(k, V, NSUB)
    L = np.ascontiguousarray(lors[:, views].reshape(-1, 2, 3))
    y = np.ascontiguousarray(y_all[:, views].reshape(-1))
    m = np.ascontiguousarray(m_all[:, views].reshape(-1))
    a = np.ascontiguousarray(a_all[:, views].reshape(-1))
    nz = np.nonzero(y > 0)[0]
    sub.append(dict(L=L, y=y, m=m, a=a, nz=nz))
nbins_sub = sub[0]['y'].size
print(f'{NSUB} subsets, {nbins_sub:,} bins per subset, non-zero {np.mean([s["nz"].size for s in sub]):,.0f} per subset', flush=True)


def sync():
    cp.cuda.Device().synchronize()


class Timer:
    def __init__(self):
        self.t = {}

    def __call__(self, k, f):
        sync(); t0 = time.perf_counter(); r = f(); sync()
        self.t[k] = self.t.get(k, 0.0) + time.perf_counter() - t0
        return r


def fwd(xs, xe, img, n):
    out = cp.zeros(n, cp.float32); ppc.joseph3d_fwd(xs, xe, img, orgg, vsg, out); return out


def back(xs, xe, val, acc):
    ppc.joseph3d_back(xs, xe, acc, orgg, vsg, val); return acc


# --- RDP gradient (26 neighbours, smoothed, kappa-weighted), GPU
eps = np.float32(x_h.max() * 1e-3)
shifts = [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1) if (i, j, k) != (0, 0, 0)]


_rdp_src = r"""
extern "C" __global__ void rdp_grad(const float* x, const float* k, float* g, int nz, int ny, int nx, float eps) {
  long idx = (long)blockDim.x * blockIdx.x + threadIdx.x;
  long n = (long)nz * ny * nx;
  if (idx >= n) return;
  int i = idx / (ny * nx), j = (idx / nx) % ny, l = idx % nx;
  float xj = x[idx], kj = k[idx], acc = 0.f;
  for (int di = -1; di <= 1; di++) for (int dj = -1; dj <= 1; dj++) for (int dl = -1; dl <= 1; dl++) {
    if (di == 0 && dj == 0 && dl == 0) continue;
    int a = i + di, b = j + dj, c = l + dl;
    if (a < 0 || a >= nz || b < 0 || b >= ny || c < 0 || c >= nx) continue;
    long q = ((long)a * ny + b) * nx + c;
    float xk = x[q], d = xj - xk, ad = fabsf(d);
    float w = rsqrtf((float)(abs(di) + abs(dj) + abs(dl)));
    float den = xj + xk + 2.f * ad + eps;
    acc += w * kj * k[q] * d * (2.f * ad + xj + 3.f * xk + 2.f * eps) / (den * den);
  }
  g[idx] = acc;
}
"""
_rdp_k = cp.RawKernel(_rdp_src, 'rdp_grad')


def rdp_grad(x, kap, beta=1.0):
    g = cp.empty_like(x)
    n = x.size
    _rdp_k(((n + 255) // 256,), (256,), (x, kap, g, np.int32(x.shape[0]), np.int32(x.shape[1]), np.int32(x.shape[2]), eps))
    return g


import numba


@numba.njit(parallel=True, fastmath=True)
def ratio_mt(m, y, a, f, c):
    out = np.empty_like(f)
    for i in numba.prange(f.size):
        yh = m[i] * (c * f[i] + a[i])
        out[i] = c * m[i] * y[i] / yh if yh > 0 else 0.0
    return out


@numba.njit(parallel=True, fastmath=True)
def update_mt(x, gl, sens, gp, stored, summed, pre, step, nsub):
    xf, glf, sf, gpf, stf, smf, pf = x.ravel(), gl.ravel(), sens.ravel(), gp.ravel(), stored.ravel(), summed.ravel(), pre.ravel()
    for i in numba.prange(xf.size):
        approx = (glf[i] - sf[i] - gpf[i] - stf[i]) * nsub + smf[i]
        v = xf[i] + step * pf[i] * approx
        xf[i] = v if v > 0 else 0.0


# --- per-subset LORs on the GPU (STIR keeps xstart/xend on the device: ParallelprojHelper CuVec)
for s in sub:
    s['xs'] = cp.asarray(np.ascontiguousarray(s['L'][:, 0])); s['xe'] = cp.asarray(np.ascontiguousarray(s['L'][:, 1]))
    s['xs_nz'] = s['xs'][cp.asarray(s['nz'])]; s['xe_nz'] = s['xe'][cp.asarray(s['nz'])]

# setup cost shared by all layouts: subset sensitivities c*A_k^T m_k
tm = Timer()
sens_sub = []
for s in sub:
    sens_sub.append(tm('setup: subset sensitivity (GPU back of m)', lambda: back(s['xs'], s['xe'], cp.asarray(c * s['m']), cp.zeros(shape, cp.float32))))
setup_sens = tm.t['setup: subset sensitivity (GPU back of m)']

sens_h = [cp.asnumpy(g) for g in sens_sub]
kap_g = cp.asarray(kappa_h)
precond_h = (x_h / np.maximum(sum(sens_h), 1e-6)).astype(np.float32)
stored_h = [np.zeros(shape, np.float32) for _ in range(NSUB)]
summed_h = np.zeros(shape, np.float32)
step = np.float32(1.0)

# ---------------- A: SIRF/STIR layout
tA = Timer()
x = x_h.copy()
for r in range(REP + 1):
    if r == 1: tA.t.clear()
    for k in range(NSUB):
        s = sub[k]
        # prior gradient on GPU, image copied in and out
        xg = tA('A1 prior: image host->GPU', lambda: cp.asarray(x))
        gp = tA('A2 prior: RDP gradient on GPU', lambda: rdp_grad(xg, kap_g))
        gp_h = tA('A3 prior: gradient GPU->host', lambda: cp.asnumpy(gp))
        # likelihood subset gradient: STIR forward project (whole subset), result into host ProjDataInMemory
        xg2 = tA('A4 like: image host->GPU', lambda: cp.asarray(x))
        f = tA('A5 like: forward projection GPU (all subset bins)', lambda: fwd(s['xs'], s['xe'], xg2, nbins_sub))
        f_h = tA('A6 like: projection GPU->host', lambda: cp.asnumpy(f))
        ratio_h = tA('A7 like: CPU ratio m*y/yhat over all subset bins', lambda: (lambda yh: np.where(yh > 0, s['m'] * s['y'] / np.maximum(yh, 1e-30), 0).astype(np.float32))(s['m'] * (c * f_h + s['a'])))
        tA('A7mt like: CPU ratio, numba multithread (STIR uses OpenMP)', lambda: ratio_mt(s['m'], s['y'], s['a'], f_h, c))
        rg = tA('A8 like: ratio host->GPU', lambda: cp.asarray(c * ratio_h))
        gl = tA('A9 like: back projection GPU (all subset bins)', lambda: back(s['xs'], s['xe'], rg, cp.zeros(shape, cp.float32)))
        gl_h = tA('A10 like: gradient GPU->host', lambda: cp.asnumpy(gl))
        # SVRG combination + preconditioned step + non-negativity on host images (SIRF ImageData)
        def upd():
            g = gl_h - sens_h[k] - gp_h
            approx = (g - stored_h[k]) * NSUB + summed_h
            x[...] = np.maximum(x + step * (precond_h * approx), 0)
        tA('A11 CPU image algebra (SVRG combine, precond step, max 0)', upd)
        xm = x.copy()
        tA('A11mt CPU image algebra, numba multithread', lambda: update_mt(xm, gl_h, sens_h[k], gp_h, stored_h[k], summed_h, precond_h, step, np.float32(NSUB)))
nA = REP * NSUB

# ---------------- B: GPU-resident dense
tB = Timer()
xg = cp.asarray(x_h); pg = cp.asarray(precond_h); summed = cp.zeros(shape, cp.float32)
stored = [cp.zeros(shape, cp.float32) for _ in range(NSUB)]
for s in sub:
    s['y_g'], s['m_g'], s['a_g'] = cp.asarray(s['y']), cp.asarray(s['m']), cp.asarray(s['a'])
for r in range(REP + 1):
    if r == 1: tB.t.clear()
    for k in range(NSUB):
        s = sub[k]
        gp = tB('B1 RDP gradient', lambda: rdp_grad(xg, kap_g))
        f = tB('B2 forward (all subset bins)', lambda: fwd(s['xs'], s['xe'], xg, nbins_sub))
        rg = tB('B3 ratio on GPU', lambda: c * cp.where((yh := s['m_g'] * (c * f + s['a_g'])) > 0, s['m_g'] * s['y_g'] / cp.maximum(yh, 1e-30), 0).astype(cp.float32))
        gl = tB('B4 back (all subset bins)', lambda: back(s['xs'], s['xe'], rg, cp.zeros(shape, cp.float32)))
        def upd():
            approx = (gl - sens_sub[k] - gp - stored[k]) * NSUB + summed
            cp.maximum(xg + step * (pg * approx), 0, out=xg)
        tB('B5 image algebra on GPU', upd)

# ---------------- C: GPU-resident event-driven
tC = Timer()
xg = cp.asarray(x_h)
for s in sub:
    nzg = cp.asarray(s['nz']); s['y_nz'], s['m_nz'], s['a_nz'] = s['y_g'][nzg], s['m_g'][nzg], s['a_g'][nzg]
for r in range(REP + 1):
    if r == 1: tC.t.clear()
    for k in range(NSUB):
        s = sub[k]; n = s['nz'].size
        gp = tC('C1 RDP gradient', lambda: rdp_grad(xg, kap_g))
        f = tC('C2 forward (non-zero bins only)', lambda: fwd(s['xs_nz'], s['xe_nz'], xg, n))
        rg = tC('C3 ratio on GPU', lambda: c * s['m_nz'] * s['y_nz'] / cp.maximum(s['m_nz'] * (c * f + s['a_nz']), 1e-30))
        gl = tC('C4 back (non-zero bins only)', lambda: back(s['xs_nz'], s['xe_nz'], rg.astype(cp.float32), cp.zeros(shape, cp.float32)))
        def upd():
            approx = (gl - sens_sub[k] - gp - stored[k]) * NSUB + summed
            cp.maximum(xg + step * (pg * approx), 0, out=xg)
        tC('C5 image algebra on GPU', upd)

res = dict(dataset=os.path.basename(os.path.normpath(SRC)), subsets=NSUB, bins_per_subset=int(nbins_sub),
           nonzero_per_subset=float(np.mean([s['nz'].size for s in sub])), image_shape=list(shape),
           setup_subset_sensitivities_s=setup_sens, repeats=REP,
           per_update_ms={'A': {k: v / nA * 1e3 for k, v in tA.t.items()},
                          'B': {k: v / nA * 1e3 for k, v in tB.t.items()},
                          'C': {k: v / nA * 1e3 for k, v in tC.t.items()}})
for L in 'ABC':
    d = res['per_update_ms'][L]
    d['TOTAL'] = sum(v for k, v in d.items() if 'mt' not in k.split()[0])
d = res['per_update_ms']['A']
d['TOTAL_with_multithread_CPU'] = d['TOTAL'] - d['A7 like: CPU ratio m*y/yhat over all subset bins'] - d['A11 CPU image algebra (SVRG combine, precond step, max 0)'] + d['A7mt like: CPU ratio, numba multithread (STIR uses OpenMP)'] + d['A11mt CPU image algebra, numba multithread']
print(json.dumps(res, indent=1))
json.dump(res, open(sys.argv[4] if len(sys.argv) > 4 else 'psv_flow_profile.json', 'w'), indent=1)
