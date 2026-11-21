"""EXP-S18 full-data input for the FPGA run (GE_D690_NEMA_IQ2, all 3,070,938 events, time order):
hardware event parameters (as prep_tof.py, 5 sigma, x / y main axis, planes inside the image box and the TOF window)
and the additive term with the frozen outside-FOV image folded in:
    a' = a + c * A_tof (x0 * (1 - fov)),  x0 = 6 mm Gaussian of OSEM (psv start image; P = 0 outside the FOV).
Output (D:/PET/claude_house/work/r2_fpga/GE_D690_NEMA_IQ2): ev_hw_all.bin (prep_tof record, 48 B, with a' in 'a'),
keep_all.npy (event index of each record), subset_edges.npy (M = 8, event index), x0.npy, prep_full.json.
Usage (env pp): python prep_full.py [chunk]"""
import json, os, sys, time
import numpy as np
import cupy as cp
import cupyx.scipy.ndimage as cnd
from scipy.special import erf as _erf  # noqa: F401  (kept for parity with prep_tof)

DS = 'GE_D690_NEMA_IQ2'
os.environ['DS'] = DS
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'Users'))
LMP = 'C:/Users/t5512/AppData/Local/Temp/claude/9d475279f3617f93/5142366d-c9a0-40dd-a9b5-3424c81b8845/scratchpad/lmpsv'
sys.path.insert(0, LMP)
import tofcore                                   # noqa: E402
import parallelproj_core as ppc                  # noqa: E402

CH = int(sys.argv[1]) if len(sys.argv) > 1 else 100000
NSIG = 5.0
FRAC = 20
S = float(1 << FRAC)
LM = os.environ.get('LMSRC', f'D:/PET/data/list_mode/petric2/{DS}')     # LMSRC: e.g. the crystal-pair events from clm2ev.py
OUT = os.environ.get('PREPOUT', f'D:/PET/claude_house/work/r2_fpga/{DS}')
os.makedirs(OUT, exist_ok=True)
x, vs = tofcore.read_hv(f'D:/PET/data/sinogram/petric2/{DS}/OSEM_image.hv')
NZ, NY, NX = x.shape
org = -(np.array(x.shape) - 1) / 2 * vs
W, SIG, NT, SGN = tofcore.TOF_W, tofcore.TOF_SIGMA, tofcore.NTOF, tofcore.TOF_SIGN
HALF = NSIG * SIG
fov = np.load(f'{LM}/fov_mask.npy') > 0
# psv start image: 6 mm FWHM Gaussian of OSEM (lm_psv.LMPSV / LMProblem.gauss, mode constant)
sig = [6.0 / (2 * np.sqrt(2 * np.log(2))) / v for v in vs]
x0 = cnd.gaussian_filter(cp.asarray(x), sig, mode='constant').get().astype(np.float32)
np.save(f'{OUT}/x0.npy', x0)
xout = cp.asarray((x0 * (~fov)).astype(np.float32))
ev = np.load(f'{LM}/events.npy')
lors = np.load(f'{LM}/lors_all.npy', mmap_mode='r')
NE = len(ev)
edges = np.linspace(0, NE, 9).astype(np.int64)
np.save(f'{OUT}/subset_edges.npy', edges)
dt = np.dtype([('i0', '<i2'), ('na', '<i2'), ('u0', '<i4'), ('v0', '<i4'), ('du', '<i4'), ('dv', '<i4'),
               ('d0', '<f4'), ('dd', '<f4'), ('mw', '<f4'), ('y', '<f4'), ('a', '<f4'), ('pad', '<f4')])
c = np.float32(1.0 / vs[2])
sigc = cp.asarray(np.array([SIG], np.float32)); tco = cp.asarray(np.array([0.0], np.float32))
orgc = cp.asarray(org.astype(np.float32)); vsc = cp.asarray(vs.astype(np.float32))
fo = open(f'{OUT}/ev_hw_all.bin', 'wb')
keep_all = []
nsteps = 0; nkept = 0; zdom_tot = 0; fold_max = 0.0
t0 = time.time()
for e0 in range(0, NE, CH):
    e = ev[e0:e0 + CH]
    L = np.asarray(lors[e['lor']]).astype(np.float64)
    P1, P2 = L[:, 0], L[:, 1]
    p1, p2 = (P1 - org) / vs, (P2 - org) / vs
    d = p2 - p1
    ax = (np.abs(d[:, 1]) > np.abs(d[:, 2])).astype(np.int64)
    zdom = np.abs(d[:, 0]) * vs[0] > np.maximum(np.abs(d[:, 1]), np.abs(d[:, 2])) * vs[2]
    zdom_tot += int(zdom.sum())
    km = np.where(ax == 1, 1, 2); ku = np.where(ax == 1, 2, 1)
    idx = np.arange(len(e))
    dmain = d[idx, km]
    lenmm = np.linalg.norm(P2 - P1, axis=1)
    sc = lenmm / 2 + SGN * e['tof'].astype(np.float64) * W
    Pp = np.arange(NX)[None, :]
    t = (Pp - p1[idx, km][:, None]) / dmain[:, None]
    U = p1[idx, ku][:, None] + t * d[idx, ku][:, None]
    Vz = p1[:, 0:1] + t * d[:, 0:1]
    smm = t * lenmm[:, None]
    inside = (U > -0.5) & (U < NX - 0.5) & (Vz > -0.5) & (Vz < NZ - 0.5) & (t >= 0) & (t <= 1) & \
             (np.abs(smm - sc[:, None]) <= HALF) & ~zdom[:, None]
    del t, U, Vz, smm
    has = inside.any(1)
    a_p = np.where(has, inside.argmax(1), 0)
    b_p = np.where(has, NX - 1 - inside[:, ::-1].argmax(1), -1)
    n = np.where(has, b_p - a_p + 1, 0)
    assert np.all(inside.sum(1)[has] == n[has])
    del inside
    du = d[idx, ku] / dmain; dv = d[:, 0] / dmain
    u0 = p1[idx, ku] + (a_p - p1[idx, km]) * du
    v0 = p1[:, 0] + (a_p - p1[idx, km]) * dv
    s0 = (a_p - p1[idx, km]) / dmain * lenmm
    dd = lenmm / dmain
    mw = np.sqrt(1 + du ** 2 + (dv * vs[0] / vs[2]) ** 2)
    # outside-FOV fold (GPU, parallelproj TOF list-mode, 5 sigma)
    tb = cp.asarray((NT // 2 + SGN * e['tof'].astype(np.int32)).astype(np.int16))
    Fo = cp.zeros(len(e), cp.float32)
    ppc.joseph3d_tof_lm_fwd(cp.asarray(P1.astype(np.float32)), cp.asarray(P2.astype(np.float32)), xout, orgc, vsc, Fo, W,
                            sigc, tco, tb, NT, NSIG)
    fold = (c * Fo).get()
    fold_max = max(fold_max, float(fold.max()))
    keep = np.nonzero(has)[0]
    hw = np.zeros(keep.size, dt)
    hw['i0'] = a_p[keep]; hw['na'] = (n[keep] | (ax[keep] << 15)).astype(np.int32).astype(np.int16)
    hw['u0'] = np.round(u0[keep] * S); hw['v0'] = np.round(v0[keep] * S)
    hw['du'] = np.round(du[keep] * S); hw['dv'] = np.round(dv[keep] * S)
    hw['d0'] = (s0 - sc)[keep]; hw['dd'] = dd[keep]; hw['mw'] = mw[keep]; hw['y'] = 1.0
    hw['a'] = (e['a'].astype(np.float64) + fold)[keep]
    hw.tofile(fo)
    keep_all.append(keep + e0)
    nsteps += int(n[keep].sum()); nkept += keep.size
    print(f'{e0 + len(e)}/{NE} events, kept {nkept}, {time.time() - t0:.0f} s', flush=True)
fo.close()
keep_all = np.concatenate(keep_all)
np.save(f'{OUT}/keep_all.npy', keep_all)
info = dict(dataset=DS, events=int(NE), kept=int(nkept), dropped_no_plane=int(NE - nkept), z_dominant=zdom_tot,
            steps_mean=nsteps / nkept, fold_max=fold_max, subset_edges=edges.tolist(), nsig=NSIG)
json.dump(info, open(f'{OUT}/prep_full.json', 'w'), indent=1)
print(json.dumps(info, indent=1))
