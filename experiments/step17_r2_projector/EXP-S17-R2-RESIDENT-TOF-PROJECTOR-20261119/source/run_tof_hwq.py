"""Hardware storage check for the R2 voxel unit: psv with the SVRG tables g_tab[k] and the preconditioner stored in
fp16 (DDR traffic of the voxel update 22 -> 14 B/voxel), image / g_sum / RDP gradient fp32. Does it still pass at
update 40 like the fp32 GPU run? Usage: python run_tof_hwq.py <max_updates> <what: tab|pre|both>"""
import os, sys, json
os.environ.setdefault('DS', 'GE_D690_NEMA_IQ2'); os.environ.setdefault('TOF_NSIG', '5')
import cupy as cp
import tofcore
from lm_psv import LMPSV, run

WHAT = sys.argv[2] if len(sys.argv) > 2 else 'both'


def q16(a):
    return a.astype(cp.float16).astype(cp.float32)


class HWQ(LMPSV):
    def calc_precond(self, x):
        p = super().calc_precond(x)
        return q16(p) if WHAT in ('pre', 'both') else p

    def full_grad(self):
        super().full_grad()
        if WHAT in ('tab', 'both'):
            mx = max(float(cp.abs(g).max()) for g in self.g_tab)
            print('max |g_tab|', mx, 'fp16 overflow' if mx > 6e4 else '')
            self.g_tab = [q16(g) for g in self.g_tab]


P = tofcore.TOFProblem()
alg = HWQ(P, 8)
hist, first = run(P, alg, int(sys.argv[1]), True)
h = hist[first - 1] if first else hist[-1]
print(json.dumps(dict(what=WHAT, first_pass_update=first), indent=1))
json.dump(dict(what=WHAT, first_pass_update=first, history=hist), open(f'd690_psv_hwq_{WHAT}.json', 'w'), indent=1)
