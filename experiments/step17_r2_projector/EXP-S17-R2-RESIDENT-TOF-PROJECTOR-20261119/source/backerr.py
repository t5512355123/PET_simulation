"""Where does the R2 model back projection differ from parallelproj? Usage: python backerr.py <dir>"""
import sys
import numpy as np
D = sys.argv[1]
b = np.fromfile(f'{D}/sw_back.bin', '<f4').reshape(47, 201, 201)
r = np.fromfile(f'{D}/back_ref.bin', '<f4').reshape(47, 201, 201)
pos = np.fromfile(f'{D}/sweep_pos.bin', '<i4')
m = np.load('D:/PET/data/list_mode/petric2/GE_D690_NEMA_IQ2/fov_mask.npy') > 0   # true FOV (P = 0 outside)
d = np.abs(b - r) * m
i = np.unravel_index(d.argmax(), d.shape)
print('max at (z, y, x)', i, 'model', b[i], 'ref', r[i], 'ref max', r[m].max())
print('rel L2 in FOV', np.sqrt(np.sum((b - r)[m].astype(np.float64) ** 2) / np.sum(r[m].astype(np.float64) ** 2)))
big = m & (r > 0.1 * r.max())
q = b[big] / r[big]
print('model/ref on voxels > 10% max: median', np.median(q), 'p1/p99', np.percentile(q, [1, 99]))
bad = d > 1e-2 * r[m].max()
zz = np.nonzero(bad)
print('voxels with error > 1% of max:', int(bad.sum()), 'of', int(m.sum()))
if zz[0].size:
    print('z values', np.unique(zz[0])[:20], 'y', zz[1].min(), zz[1].max(), 'x', zz[2].min(), zz[2].max())
    print('x mod 40 hist', np.bincount(zz[2] % 40, minlength=40))
    print('y mod 40 hist', np.bincount(zz[1] % 40, minlength=40))
