"""EXP-S13 input: Esser2 list-mode events -> slab hardware event format (Ev, 32 B) + GPU parallelproj reference.
Usage (env pp): python prep_esser2.py <out dir> <first event> <n events>
Ev: i0 (first plane, global index), n_axis (steps | axis<<15), u0 v0 du dv (fixed point, FRAC bits), mw, y = 1, a.
Hardware ratio s = mw*y/(mw*F + a) with y = 1 gives s = mw/(c*A_e x + a_e), so the hardware back projection
sum_e sum_steps w * s = c * A^T (1 / (c A x + a)) = the list-mode gradient term (m cancels: m/yhat = 1/(cAx + a)).
Reference: parallelproj Joseph on the GPU with the same events and the PETRIC OSEM image."""
import json, os, re, sys, hashlib
import numpy as np
import cupy as cp
import parallelproj_core as ppc

FRAC = 20
out, e0, NE = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
os.makedirs(out, exist_ok=True)
SRC = 'D:/PET_DATA/petric2/NeuroLF_Esser2'
LM = 'D:/PET_DATA/listmode/NeuroLF_Esser2'


def read_hv(path):
    h = open(path).read()
    size = {int(i): int(v) for i, v in re.findall(r'matrix size \[(\d)\] := (\d+)', h)}
    vox = {int(i): float(v) for i, v in re.findall(r'scaling factor \(mm/pixel\) \[(\d)\] := ([-\d.e+]+)', h)}
    shape = (size[3], size[2], size[1])
    img = np.fromfile(os.path.join(os.path.dirname(path), re.search(r'name of data file := (.+)', h).group(1).strip()), '<f4')
    return img.reshape(shape), np.array([vox[3], vox[2], vox[1]], np.float32)


x, vs = read_hv(os.path.join(SRC, 'OSEM_image.hv'))
shape = np.array(x.shape)                     # (z, y, x) = (95, 163, 163)
NZ, NY, NX = shape
assert NX == NY and abs(vs[0] - vs[2]) < 1e-6, 'hardware needs NX == NY and isotropic voxels'
org = -(shape - 1) / 2 * vs
c = 1.0 / vs[2]
raw = np.fromfile(os.path.join(LM, 'fpga_events.bin'), '<f4').reshape(-1, 8)[e0:e0 + NE].astype(np.float64)
p1 = (raw[:, 0:3] - org) / vs                 # index coordinates (z, y, x)
p2 = (raw[:, 3:6] - org) / vs
m_e, a_e = raw[:, 6], raw[:, 7]
d = p2 - p1
adz, ady, adx = np.abs(d[:, 0]), np.abs(d[:, 1]), np.abs(d[:, 2])
zdom = adz > np.maximum(adx, ady)
axis = (ady > adx).astype(np.int64)           # 0: principal x (planes = x, u = y), 1: principal y (planes = y, u = x)
# orient so the principal component is positive
dd = np.where(axis == 1, d[:, 1], d[:, 2])
flip = dd < 0
A_ = np.where(flip[:, None], p2, p1)
D_ = np.where(flip[:, None], -d, d)
dd = np.abs(dd)
d0 = np.where(axis == 1, A_[:, 1], A_[:, 2])
u1 = np.where(axis == 1, A_[:, 2], A_[:, 1])
z1 = A_[:, 0]
du = np.where(axis == 1, D_[:, 2], D_[:, 1]) / dd
dv = D_[:, 0] / dd
# planes whose bilinear support overlaps the image: u in (-1, NU), v in (-1, NZ)
P = np.arange(NX)[None, :]
U = u1[:, None] + (P - d0[:, None]) * du[:, None]
V = z1[:, None] + (P - d0[:, None]) * dv[:, None]
CLIP = os.environ.get('CLIP', 'halfvox')
if CLIP == 'center':     # parallelproj-like: interpolation point between the first and last voxel centres
    box = (U >= 0) & (U <= NX - 1) & (V >= 0) & (V <= NZ - 1)
elif CLIP == 'halfvox':  # image box = voxel edges (half a voxel beyond the first and last centres)
    box = (U > -0.5) & (U < NX - 0.5) & (V > -0.5) & (V < NZ - 0.5)
elif CLIP == 'zcenter':
    box = (U > -1) & (U < NX) & (V >= 0) & (V <= NZ - 1)
else:                    # 'support': any overlap of the bilinear support with the image
    box = (U > -1) & (U < NX) & (V > -1) & (V < NZ)
inside = box & (P >= np.ceil(d0)[:, None]) & (P <= np.floor(d0 + dd)[:, None])
has = inside.any(1) & ~zdom
a_p = np.where(has, inside.argmax(1), 0)
b_p = np.where(has, NX - 1 - inside[:, ::-1].argmax(1), -1)
n = np.where(has, b_p - a_p + 1, 0)
assert np.all(inside.sum(1)[has] == n[has]), 'support must be contiguous'
u0 = u1 + (a_p - d0) * du
v0 = z1 + (a_p - d0) * dv
dt = np.dtype([('i0', '<i2'), ('na', '<i2'), ('u0', '<i4'), ('v0', '<i4'), ('du', '<i4'), ('dv', '<i4'),
               ('mw', '<f4'), ('y', '<f4'), ('a', '<f4')])
keep = np.nonzero(has)[0]
ev = np.zeros(keep.size, dt)
S = float(1 << FRAC)
ev['i0'] = a_p[keep]
ev['na'] = (n[keep] | (axis[keep] << 15)).astype(np.int32).astype(np.int16)
ev['u0'] = np.round(u0[keep] * S); ev['v0'] = np.round(v0[keep] * S)
ev['du'] = np.round(du[keep] * S); ev['dv'] = np.round(dv[keep] * S)
ev['mw'] = np.sqrt(1 + du[keep] ** 2 + dv[keep] ** 2)
ev['y'] = 1.0
ev['a'] = a_e[keep]
ev.tofile(os.path.join(out, 'ev_global.bin'))
x.astype('<f4').tofile(os.path.join(out, 'img.bin'))

# ---- check the conversion: same Joseph steps in double precision on the CPU, from the fixed-point parameters
def joseph_hw(evs, img):
    F = np.zeros(evs.size)
    for i, e in enumerate(evs):
        ax_, nn = (int(e['na']) >> 15) & 1, int(e['na']) & 0x7fff
        k = np.arange(nn)
        u = (e['u0'] + k * np.int64(e['du'])) / S
        v = (e['v0'] + k * np.int64(e['dv'])) / S
        p = e['i0'] + k
        iu, iv = np.floor(u).astype(int), np.floor(v).astype(int)
        fu, fv = u - iu, v - iv
        for du_, wu in ((0, 1 - fu), (1, fu)):
            for dz_, wz in ((0, 1 - fv), (1, fv)):
                cu, cz = iu + du_, iv + dz_
                ok = (cu >= 0) & (cu < NX) & (cz >= 0) & (cz < NZ)
                xx = np.where(ax_ == 1, cu, p); yy = np.where(ax_ == 1, p, cu)
                val = np.where(ok, img[np.clip(cz, 0, NZ - 1), np.clip(yy, 0, NY - 1), np.clip(xx, 0, NX - 1)], 0.0)
                F[i] += np.sum(wu * wz * val)
    return F * evs['mw']


# ---- GPU reference (parallelproj, same as EXP-S9 lmcore)
xs = cp.asarray(raw[keep, 0:3].astype(np.float32)); xe = cp.asarray(raw[keep, 3:6].astype(np.float32))
xg = cp.asarray(x)
orgg, vsg = cp.asarray(org.astype(np.float32)), cp.asarray(vs)
Fpp = cp.zeros(keep.size, cp.float32)
ppc.joseph3d_fwd(xs, xe, xg, orgg, vsg, Fpp)
Fpp = c * Fpp.get().astype(np.float64)
s_ref = 1.0 / (Fpp + a_e[keep])
back = cp.zeros(x.shape, cp.float32)
ppc.joseph3d_back(xs, xe, back, orgg, vsg, cp.asarray(s_ref.astype(np.float32)))
back_ref = c * back.get()
s_ref.astype('<f8').tofile(os.path.join(out, 's_ref.bin'))
back_ref.astype('<f4').tofile(os.path.join(out, 'back_ref.bin'))
Fhw = joseph_hw(ev[:2000], x.astype(np.float64))
rel = np.abs(Fhw - Fpp[:2000]) / np.maximum(np.abs(Fpp[:2000]), 1e-12)
steps = n[keep]
info = dict(first_event=e0, n_events=NE, kept=int(keep.size), z_dominant=int(zdom.sum()), miss_image=int((~has & ~zdom).sum()),
            axis1_fraction=float(axis[keep].mean()), mean_steps=float(steps.mean()), total_steps=int(steps.sum()), frac=FRAC,
            conversion_check_events=2000, F_rel_diff_max=float(rel.max()), F_rel_diff_median=float(np.median(rel)),
            image_shape=[int(v) for v in shape], voxel_mm=[float(v) for v in vs],
            fpga_events_sha256=hashlib.sha256(open(os.path.join(LM, 'fpga_events.bin'), 'rb').read()).hexdigest())
json.dump(info, open(os.path.join(out, 'prep.json'), 'w'), indent=1)
np.save(os.path.join(out, 'keep_index.npy'), keep + e0)
print(json.dumps(info, indent=1))
