"""Check that list-mode events give the same Poisson log-likelihood gradient as the PETRIC sinogram, and export
the FPGA event stream.

Model (SIRF / PETRIC): yhat_i = m_i * (c * (A x)_i + a_i), c = 1 / transaxial voxel size (STIR line integrals in voxel units).
  sinogram gradient : c * A^T( m * y / yhat ) - c * A^T m          (all bins, dense)
  list-mode gradient: c * sum_events A_e^T( m_e / yhat_e ) - s,  s = c * A^T m (sensitivity image, computed once)
Both are evaluated at the OSEM image with the same parallelproj Joseph projector (GPU).

Outputs in <lm_dir>: sensitivity.npy, fpga_events.bin (float32 x 8 per event: z1 y1 x1 z2 y2 x2 m a, time order), check.json
Usage: python -I lm_check.py <dataset_dir> <lm_dir>
"""
import json
import os
import re
import sys
import time

import numpy as np
import cupy as cp
import parallelproj_core as ppc

SRC, LM = sys.argv[1], sys.argv[2]


def read_hv(path):
    h = open(path, encoding='latin-1').read()
    g = lambda k: [float(v) for v in re.findall(re.escape(k) + r' \[(\d)\] := ([-\d.e+]+)', h)]
    size = {int(i): int(float(v)) for i, v in re.findall(r'!matrix size \[(\d)\] := ([\d.]+)', h)}
    vox = {int(i): float(v) for i, v in re.findall(r'scaling factor \(mm/pixel\) \[(\d)\] := ([-\d.e+]+)', h)}
    shape = (size[3], size[2], size[1])                      # z, y, x
    vs = np.array([vox[3], vox[2], vox[1]], np.float32)
    img = np.fromfile(os.path.join(os.path.dirname(path), re.search(r'name of data file := (.+)', h).group(1).strip()), '<f4')
    return img.reshape(shape), vs


def rd_sino(n):
    return np.fromfile(os.path.join(SRC, n), '<f4')


x, vs = read_hv(os.path.join(SRC, 'OSEM_image.hv'))
shape = x.shape
org = (-(np.array(shape) - 1) / 2 * vs).astype(np.float32)
c = np.float32(1.0 / vs[2])
y, m, a = np.load(os.path.join(LM, 'sino_y_m_a.npy'))  # written by sino2lm.py in STIR to_array order
lors = np.load(os.path.join(LM, 'lors_all.npy'), mmap_mode='r').reshape(-1, 2, 3)
ev = np.load(os.path.join(LM, 'events.npy'))
nz = np.load(os.path.join(LM, 'bins_nz.npy'))
lor_nz = np.load(os.path.join(LM, 'lor_nz.npy'))
assert lors.shape[0] == y.size

xg, orgg, vsg = cp.asarray(x), cp.asarray(org), cp.asarray(vs)


def fwd(L, img):
    xs, xe = cp.asarray(np.ascontiguousarray(L[:, 0])), cp.asarray(np.ascontiguousarray(L[:, 1]))
    out = cp.zeros(L.shape[0], cp.float32)
    ppc.joseph3d_fwd(xs, xe, img, orgg, vsg, out)
    return out


def back(L, val, acc):
    xs, xe = cp.asarray(np.ascontiguousarray(L[:, 0])), cp.asarray(np.ascontiguousarray(L[:, 1]))
    ppc.joseph3d_back(xs, xe, acc, orgg, vsg, cp.asarray(np.ascontiguousarray(val, np.float32)))


CH = 8_000_000
t0 = time.time()
sens = cp.zeros(shape, cp.float32)
g_sino = cp.zeros(shape, cp.float32)
for i in range(0, y.size, CH):
    L = np.asarray(lors[i:i + CH])
    mi, ai, yi = m[i:i + CH], a[i:i + CH], y[i:i + CH]
    back(L, c * mi, sens)
    yh = cp.asarray(mi) * (c * fwd(L, xg) + cp.asarray(ai))
    ratio = cp.where(yh > 0, cp.asarray(mi) * cp.asarray(yi) / cp.maximum(yh, 1e-30), 0)
    back(L, c * cp.asnumpy(ratio), g_sino)
g_sino -= sens
t_dense = time.time() - t0

# list-mode: one entry per event (duplicates for bins with y > 1)
t0 = time.time()
pos = np.searchsorted(nz, ev['bin'])
assert np.array_equal(nz[pos], ev['bin'])
g_lm = cp.zeros(shape, cp.float32)
for i in range(0, ev.size, CH):
    e = ev[i:i + CH]
    L = lor_nz[pos[i:i + CH]]
    yh = cp.asarray(e['m']) * (c * fwd(L, xg) + cp.asarray(e['a']))
    back(L, c * cp.asnumpy(cp.asarray(e['m']) / cp.maximum(yh, 1e-30)), g_lm)
g_lm -= sens
t_lm = time.time() - t0

d = cp.abs(g_lm - g_sino)
scale = float(cp.abs(g_sino).max())
res = dict(dataset=os.path.basename(os.path.normpath(SRC)), image_shape=list(shape), voxel_mm=vs.tolist(), c=float(c),
           events=int(ev.size), sinogram_bins=int(y.size),
           grad_max_abs_diff_over_max=float(d.max()) / scale,
           grad_rel_l2=float(cp.linalg.norm(g_lm - g_sino) / cp.linalg.norm(g_sino)),
           t_dense_gradient_s=round(t_dense, 2), t_listmode_gradient_s=round(t_lm, 2),
           note='times include host-device copies of this script; not a tuned benchmark')
np.save(os.path.join(LM, 'sensitivity.npy'), cp.asnumpy(sens))
f = np.empty((ev.size, 8), np.float32)
f[:, 0:3] = lor_nz[pos][:, 0]
f[:, 3:6] = lor_nz[pos][:, 1]
f[:, 6], f[:, 7] = ev['m'], ev['a']
f.tofile(os.path.join(LM, 'fpga_events.bin'))
res['fpga_events_bytes'] = int(f.nbytes)
json.dump(res, open(os.path.join(LM, 'check.json'), 'w'), indent=1)
print(json.dumps(res, indent=1))
