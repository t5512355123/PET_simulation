"""List-mode PETRIC2 problem on the GPU (parallelproj Joseph, cupy).

Model (same as SIRF/PETRIC, see EXP-S6 lm_check.py):
  yhat_e = m_e * (c * (A x)_e + a_e),  c = 1 / transaxial voxel size
  log-likelihood gradient over an event set E:  c * A_E^T (m_E / yhat_E) - s_E
  s = c * A^T m (all bins, sensitivity.npy);  for a time/event-number subset of fraction f: s_E = f * s
Prior: beta * RDP (gamma 2, eps = 1e-3 * max(OSEM), kappa, 26 neighbours, weight vox_x/|offset*vox|), same as
Speedy rdp.py / STIR RelativeDifferencePrior. Objective (maximised): L(x) - beta * R(x), x >= 0.
"""
import json
import os
import re

import numpy as np
import cupy as cp
import cupyx.scipy.ndimage as cnd
import parallelproj_core as ppc

PETRIC = 'D:/PET_DATA/petric2'
LMDIR = 'D:/PET_DATA/listmode'


def read_hv(path):
    h = open(path, encoding='latin-1').read()
    size = {int(i): int(float(v)) for i, v in re.findall(r'!matrix size \[(\d)\] := ([\d.]+)', h)}
    vox = {int(i): float(v) for i, v in re.findall(r'scaling factor \(mm/pixel\) \[(\d)\] := ([-\d.e+]+)', h)}
    shape = (size[3], size[2], size[1])
    img = np.fromfile(os.path.join(os.path.dirname(path), re.search(r'name of data file := (.+)', h).group(1).strip()), '<f4')
    return img.reshape(shape), np.array([vox[3], vox[2], vox[1]], np.float32)


_RDP_SRC = r'''
extern "C" __global__ void rdp(const float* x, const float* kap, float* g, float* h, const int nz, const int ny,
                               const int nx, const float eps, const float gamma, const float vz, const float vy,
                               const float vx, const int mode) {
  // mode 0: gradient of R; mode 1: diagonal of Hessian of R (Speedy rdp.py formulas, weight vx/|offset*vox|)
  long n = (long)nz * ny * nx;
  long i = (long)blockDim.x * blockIdx.x + threadIdx.x;
  if (i >= n) return;
  int ix = i % nx; int iy = (i / nx) % ny; int iz = i / ((long)nx * ny);
  float xj = x[i], kj = kap[i], acc = 0.0f;
  for (int dz = -1; dz <= 1; dz++) for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
    if (dz == 0 && dy == 0 && dx == 0) continue;
    int jz = iz + dz, jy = iy + dy, jx = ix + dx;
    if (jz < 0 || jz >= nz || jy < 0 || jy >= ny || jx < 0 || jx >= nx) continue;
    long k = ((long)jz * ny + jy) * nx + jx;
    float w = vx / sqrtf((dz * vz) * (dz * vz) + (dy * vy) * (dy * vy) + (dx * vx) * (dx * vx)) * kj * kap[k];
    float d = xj - x[k], s = xj + x[k];
    float phi = s + gamma * fabsf(d) + eps;
    if (mode == 0) acc += w * d * (2.0f * phi - (d + gamma * fabsf(d))) / (phi * phi);
    else { float t = s - d + eps; acc += w * 2.0f * t * t / (phi * phi * phi); }
  }
  if (mode == 0) g[i] = acc; else h[i] = acc;
}
'''
_rdp_k = cp.RawKernel(_RDP_SRC, 'rdp')


class LMProblem:
    def __init__(self, ds, order='time'):
        self.ds = ds
        src = os.path.join(PETRIC, ds); lm = os.path.join(LMDIR, ds)
        x0, vs = read_hv(os.path.join(src, 'OSEM_image.hv'))
        self.shape, self.vs = x0.shape, vs
        self.org = (-(np.array(self.shape) - 1) / 2 * vs).astype(np.float32)
        self.c = np.float32(1.0 / vs[2])
        self.osem = cp.asarray(x0)
        kap, _ = read_hv(os.path.join(src, 'kappa.hv'))
        self.kappa = cp.asarray(kap)
        self.beta = float(np.loadtxt(os.path.join(src, 'penalisation_factor.txt')))
        self.eps = float(x0.max()) * 1e-3
        self.gamma = 2.0
        ev = np.load(os.path.join(lm, 'events.npy'))
        nz = np.load(os.path.join(lm, 'bins_nz.npy'))
        pos = np.searchsorted(nz, ev['bin'])
        lor = np.load(os.path.join(lm, 'lor_nz.npy'), mmap_mode='r')
        L = np.asarray(lor[pos])                      # events in time order
        self.n_ev = ev.size
        self.t = ev['t']
        self.xs = cp.asarray(np.ascontiguousarray(L[:, 0])); self.xe = cp.asarray(np.ascontiguousarray(L[:, 1]))
        self.m = cp.asarray(ev['m']); self.a = cp.asarray(ev['a'])
        self.sens = cp.asarray(np.load(os.path.join(lm, 'sensitivity.npy')))
        self.fov = cp.asarray(np.load(os.path.join(lm, 'fov_mask.npy')))
        self.orgg, self.vsg = cp.asarray(self.org), cp.asarray(vs)
        ref, _ = read_hv(os.path.join(src, 'PETRIC', 'reference_image.hv'))
        self.ref = cp.asarray(ref)
        self.masks = {}
        for f in os.listdir(os.path.join(src, 'PETRIC')):
            if f.startswith('VOI_') and f.endswith('.hv'):
                v, _ = read_hv(os.path.join(src, 'PETRIC', f))
                self.masks[f[4:-3]] = cp.asarray(v > 0)
        self.norm = float(self.ref[self.masks['background']].mean())
        wo = self.masks['whole_object'].copy(); wo[-2:] = False   # EXP-S8: last 2 axial planes inconsistent locally
        self.masks['whole_object_minus2'] = wo
        self.n_proj = 0                                    # events projected (fwd+back pairs)

    # ---- projector on an event slice / index array
    def fwd(self, sl, x):
        xs, xe = self.xs[sl], self.xe[sl]
        out = cp.zeros(xs.shape[0], cp.float32)
        if x.dtype != cp.float32 or not x.flags.c_contiguous:
            raise TypeError(f'image must be C-contiguous float32, got {x.dtype}')
        ppc.joseph3d_fwd(xs, xe, x, self.orgg, self.vsg, out)
        return out

    def back(self, sl, val, acc):
        ppc.joseph3d_back(self.xs[sl], self.xe[sl], acc, self.orgg, self.vsg, val)

    def lik_grad(self, sl, x, frac):
        """c*A_E^T(m/yhat) - frac*s for event slice sl (frac = share of all events)."""
        m, a = self.m[sl], self.a[sl]
        yh = m * (self.c * self.fwd(sl, x) + a)
        w = (self.c * m / cp.maximum(yh, 1e-30)).astype(cp.float32)
        g = cp.zeros(self.shape, cp.float32)
        self.back(sl, w, g)
        self.n_proj += int(m.shape[0])
        g -= frac * self.sens
        return g

    def lik_grad_w(self, sl, w):
        """back-project given per-event weights (no forward), returns c*A^T w without sensitivity."""
        g = cp.zeros(self.shape, cp.float32)
        self.back(sl, w.astype(cp.float32), g)
        return g

    # ---- prior
    def _rdp(self, x, mode):
        out = cp.empty_like(x)
        n = x.size
        nz, ny, nx = self.shape
        _rdp_k(((n + 255) // 256,), (256,), (x, self.kappa, out, out, np.int32(nz), np.int32(ny), np.int32(nx),
                                              np.float32(self.eps), np.float32(self.gamma), np.float32(self.vs[0]),
                                              np.float32(self.vs[1]), np.float32(self.vs[2]), np.int32(mode)))
        return out

    def prior_grad(self, x):
        return self.beta * self._rdp(x, 0)

    def prior_diag_hess(self, x):
        return self.beta * self._rdp(x, 1)

    def gauss(self, x, fwhm_mm):
        sig = [fwhm_mm / (2 * np.sqrt(2 * np.log(2))) / v for v in self.vs]
        return cnd.gaussian_filter(x, sig, mode='constant')

    # ---- PETRIC metrics
    def metrics(self, x):
        r, M, n = self.ref, self.masks, self.norm
        out = {}
        for k in ('whole_object', 'whole_object_minus2', 'background'):
            out['RMSE_' + k] = float(cp.sqrt(cp.mean((r[M[k]] - x[M[k]]) ** 2))) / n
        for k in sorted(M):
            if k in ('whole_object', 'whole_object_minus2', 'background'):
                continue
            out['AEM_VOI_' + k] = float(abs(x[M[k]].mean() - r[M[k]].mean())) / n
        return out

    @staticmethod
    def passed(mt):
        return (mt['RMSE_whole_object_minus2'] <= 0.01 and mt['RMSE_background'] <= 0.01 and
                all(v <= 0.005 for k, v in mt.items() if k.startswith('AEM_VOI')))
