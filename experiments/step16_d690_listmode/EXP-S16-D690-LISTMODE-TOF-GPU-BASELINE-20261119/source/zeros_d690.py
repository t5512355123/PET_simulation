"""How many voxels are exactly 0 (frozen: P ~ x, so they never change) during GPU psv on D690?"""
import os, json
os.environ.setdefault('DS', 'GE_D690_NEMA_IQ2'); os.environ.setdefault('TOF_NSIG', '5')
import numpy as np, cupy as cp
from tofcore import TOFProblem
from lm_psv import LMPSV
P = TOFProblem()
alg = LMPSV(P, 8)
fov = P.fov > 0
out = []
for u in range(1, 41):
    alg.update()
    if u in (1, 2, 4, 5, 8, 16, 24, 32, 40):
        x = alg.x
        out.append(dict(update=u, zero_in_fov=float(((x == 0) & fov).sum() / fov.sum()),
                        tiny_in_fov=float(((x < 1e-6 * float(x.max())) & fov).sum() / fov.sum()),
                        precond_zero=float(((alg.precond == 0) & fov).sum() / fov.sum())))
        print(out[-1], flush=True)
x0 = P.gauss(P.osem, 6.0)
print('start image zero fraction in FOV', float(((x0 == 0) & fov).sum() / fov.sum()), 'OSEM zero fraction', float(((P.osem == 0) & fov).sum() / fov.sum()))
json.dump(out, open('zeros_d690.json', 'w'), indent=1)
