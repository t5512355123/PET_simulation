"""TOF list-mode PETRIC2 problem for GE DMI 4 rings (EXP-S16): parallelproj TOF Joseph (cupy).
Same model as lmcore.LMProblem (yhat_e = m_e (c (A x)_e + a_e), c = 1 / transaxial voxel size, RDP prior), with the
TOF kernel of the event's TOF bin. STIR TOF bins: width 25.332 mm, bin 0 centred at the LOR midpoint,
FWHM 375.4 ps -> sigma = 0.5 * 375.4 ps * 0.299792 mm/ps / 2.3548.  TOF_SIGN chooses the bin direction
(STIR position k -> parallelproj index 14 + TOF_SIGN * k); it is set from the log-likelihood check (tof_sign.py)."""
import os

import numpy as np
import cupy as cp
import parallelproj_core as ppc

from lmcore import LMProblem, read_hv, PETRIC, LMDIR

TOF_W = 25.332462
TOF_SIGMA = 0.5 * 375.4 * 0.299792458 / 2.354820045
NTOF = 29
TOF_SIGN = int(os.environ.get('TOF_SIGN', '-1'))   # tof_sign.py: -1 gives the larger log-likelihood
NSIG = float(os.environ.get('TOF_NSIG', '3.0'))


class TOFProblem(LMProblem):
    def __init__(self, ds='GE_DMI4_NEMA_IQ2', sens=True):
        self.ds = ds
        src = os.path.join(PETRIC, ds); lm = os.path.join(LMDIR, ds)
        x0, vs = read_hv(os.path.join(src, 'OSEM_image.hv'))
        self.shape, self.vs = x0.shape, vs
        self.org = (-(np.array(self.shape) - 1) / 2 * vs).astype(np.float32)
        # STIR image origin: z starts at plane 0 (first pixel offset z = 0), x/y centred -> use the header offsets
        h = open(os.path.join(src, 'OSEM_image.hv'), encoding='latin-1').read()
        import re
        offs = {int(i): float(v) for i, v in re.findall(r'first pixel offset \(mm\) \[(\d)\] := ([-\d.e+]+)', h)}
        self.org_hdr = np.array([offs.get(3, 0.0), offs.get(2, 0.0), offs.get(1, 0.0)], np.float32)
        self.c = np.float32(1.0 / vs[2])
        self.osem = cp.asarray(x0)
        kap, _ = read_hv(os.path.join(src, 'kappa.hv'))
        self.kappa = cp.asarray(kap)
        self.beta = float(np.loadtxt(os.path.join(src, 'penalisation_factor.txt')))
        self.eps = float(x0.max()) * 1e-3
        self.gamma = 2.0
        ev = np.load(os.path.join(lm, 'events.npy'))
        lors = np.load(os.path.join(lm, 'lors_all.npy'), mmap_mode='r')
        L = np.asarray(lors[ev['lor']])
        self.n_ev = ev.size
        self.t = ev['t']
        self.xs = cp.asarray(np.ascontiguousarray(L[:, 0])); self.xe = cp.asarray(np.ascontiguousarray(L[:, 1]))
        self.tofbin = cp.asarray((NTOF // 2 + TOF_SIGN * ev['tof'].astype(np.int32)).astype(np.int16))
        self.m = cp.asarray(ev['m']); self.a = cp.asarray(ev['a'])
        self.fov = cp.asarray(np.load(os.path.join(lm, 'fov_mask.npy')))
        self.orgg, self.vsg = cp.asarray(self.org), cp.asarray(vs)
        self.sig = cp.asarray(np.array([TOF_SIGMA], np.float32))
        self.tco = cp.asarray(np.array([0.0], np.float32))
        sp = os.path.join(lm, f'sensitivity_sign{TOF_SIGN}.npy')
        if sens:
            if not os.path.exists(sp):
                np.save(sp, self.sensitivity(lors, os.path.join(lm, 'msum_lor.npy')))
            self.sens = cp.asarray(np.load(sp))
        ref, _ = read_hv(os.path.join(src, 'PETRIC', 'reference_image.hv'))
        self.ref = cp.asarray(ref)
        self.masks = {}
        for f in os.listdir(os.path.join(src, 'PETRIC')):
            if f.startswith('VOI_') and f.endswith('.hv'):
                v, _ = read_hv(os.path.join(src, 'PETRIC', f))
                self.masks[f[4:-3]] = cp.asarray(v > 0)
        self.norm = float(self.ref[self.masks['background']].mean())
        self.masks['whole_object_minus2'] = self.masks['whole_object']     # no plane exclusion for this dataset
        self.n_proj = 0

    def sensitivity(self, lors, msum_path):
        """s = c A^T m over all bins and TOF bins. m does not depend on the TOF bin (checked: identical for all TOF
        positions), and the TOF kernels of one LOR sum to 1 over the TOF bins, so s = c * (non-TOF A)^T m with
        m = (sum over TOF of m) / NTOF."""
        msum = np.load(msum_path) / NTOF
        out = cp.zeros(self.shape, cp.float32)
        B = 1 << 22
        for i in range(0, msum.size, B):
            L = np.asarray(lors[i:i + B])
            ppc.joseph3d_back(cp.asarray(np.ascontiguousarray(L[:, 0])), cp.asarray(np.ascontiguousarray(L[:, 1])), out,
                              self.orgg, self.vsg, cp.asarray(msum[i:i + B].astype(np.float32)))
        return (self.c * out).get()

    def fwd(self, sl, x):
        out = cp.zeros(self.xs[sl].shape[0], cp.float32)
        ppc.joseph3d_tof_lm_fwd(self.xs[sl], self.xe[sl], x, self.orgg, self.vsg, out, TOF_W, self.sig, self.tco,
                                self.tofbin[sl], NTOF, NSIG)
        return out

    def back(self, sl, val, acc):
        ppc.joseph3d_tof_lm_back(self.xs[sl], self.xe[sl], acc, self.orgg, self.vsg, val, TOF_W, self.sig, self.tco,
                                 self.tofbin[sl], NTOF, NSIG)
