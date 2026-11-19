"""EXP-S17 inputs for the R2 model: FOV row table per (copy, plane), test image (FOV only), and the GPU reference
(parallelproj TOF list-mode, 5 sigma) for the hardware events of prep_tof.py.
copy 0: planes = x, u = y ; copy 1: planes = y, u = x.  rows of plane p in copy c: u in [ulo, uhi] where the FOV
mask is set (cylinder: same for every z).
Usage (env pp): python prep_r2.py <dataset> <dir with ev_hw.bin / keep_index.npy from prep_tof.py> [use_gpu 0/1]"""
import json, os, sys
import numpy as np

DS, D = sys.argv[1], sys.argv[2]
USE_GPU = len(sys.argv) <= 3 or sys.argv[3] == '1'
os.environ['DS'] = DS
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lmpsv'))
import tofcore                                                  # noqa: E402
LM = f'D:/PET/data/list_mode/petric2/{DS}'
fov = np.load(f'{LM}/fov_mask.npy') > 0                         # (z, y, x)
NZ, NY, NX = fov.shape
f2 = fov.any(0)                                                 # (y, x)
tab = np.full((2, NX, 2), -1, np.int32)
for p in range(NX):
    ys = np.nonzero(f2[:, p])[0]                                # copy 0: plane x = p, u = y
    if ys.size: tab[0, p] = (ys[0], ys[-1])
    xs = np.nonzero(f2[p, :])[0]                                # copy 1: plane y = p, u = x
    if xs.size: tab[1, p] = (xs[0], xs[-1])
tab.tofile(f'{D}/fov_rows.bin')
x, vs = tofcore.read_hv(f'D:/PET/data/sinogram/petric2/{DS}/OSEM_image.hv')
img = (x * fov).astype('<f4')
img.tofile(f'{D}/img_fov.bin')
info = dict(fov_voxels=int(fov.sum()), planes=NX, nz=NZ)
if USE_GPU:
    import cupy as cp
    import parallelproj_core as ppc
    keep = np.load(f'{D}/keep_index.npy')
    ev = np.load(f'{LM}/events.npy')[keep]
    lors = np.load(f'{LM}/lors_all.npy', mmap_mode='r')
    L = np.asarray(lors[ev['lor']])
    org = (-(np.array(x.shape) - 1) / 2 * vs).astype(np.float32)
    xs_, xe_ = cp.asarray(np.ascontiguousarray(L[:, 0])), cp.asarray(np.ascontiguousarray(L[:, 1]))
    tb = cp.asarray((tofcore.NTOF // 2 + tofcore.TOF_SIGN * ev['tof'].astype(np.int32)).astype(np.int16))
    sig = cp.asarray(np.array([tofcore.TOF_SIGMA], np.float32)); tco = cp.asarray(np.array([0.0], np.float32))
    c = np.float32(1.0 / vs[2])
    F = cp.zeros(len(ev), cp.float32)
    ppc.joseph3d_tof_lm_fwd(xs_, xe_, cp.asarray(img), cp.asarray(org), cp.asarray(vs), F, tofcore.TOF_W, sig, tco, tb,
                            tofcore.NTOF, 5.0)
    F = c * F
    s = 1.0 / (F + cp.asarray(ev['a']))
    back = cp.zeros(img.shape, cp.float32)
    ppc.joseph3d_tof_lm_back(xs_, xe_, back, cp.asarray(org), cp.asarray(vs), s.astype(cp.float32), tofcore.TOF_W, sig, tco,
                             tb, tofcore.NTOF, 5.0)
    (c * back).get().astype('<f4').tofile(f'{D}/back_ref.bin')
    s.get().astype('<f8').tofile(f'{D}/s_ref.bin')
    F.get().astype('<f8').tofile(f'{D}/F_ref.bin')
    info['gpu_reference'] = True
json.dump(info, open(f'{D}/prep_r2.json', 'w'), indent=1)
print(info)
