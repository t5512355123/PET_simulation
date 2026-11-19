"""Choose the TOF bin direction: list-mode log-likelihood sum_e log(yhat_e) at the OSEM and reference images for
STIR position k -> parallelproj index 14 + k and 14 - k (the sum_bins yhat term does not depend on the direction)."""
import os, sys, json
import numpy as np, cupy as cp
res = {}
for sign in (1, -1):
    os.environ['TOF_SIGN'] = str(sign)
    import importlib, tofcore
    importlib.reload(tofcore)
    P = tofcore.TOFProblem(sens=False)
    for name, x in (('osem', P.osem), ('ref', P.ref)):
        yh = P.m * (P.c * P.fwd(slice(0, P.n_ev), x) + P.a)
        res[f'sign{sign}_{name}'] = float(cp.sum(cp.log(cp.maximum(yh, 1e-30))))
    nt = P.fwd(slice(0, 20000), P.osem)
    res[f'sign{sign}_fwd_mean'] = float(nt.mean())
print(json.dumps(res, indent=1))
