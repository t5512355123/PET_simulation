"""KKT residual of the TOF list-mode objective at the PETRIC2 reference image (GE DMI4), as kkt.py for Esser2."""
import json, time
import numpy as np, cupy as cp
from tofcore import TOFProblem

P = TOFProblem()
out = {}
for name, x in (('ref', P.ref), ('osem', P.osem)):
    g = P.lik_grad(slice(0, P.n_ev), x, 1.0) - P.prior_grad(x)
    res = cp.where(x > 0, cp.abs(g), cp.maximum(g, 0)) / cp.maximum(P.sens, 1e-6)
    inside = P.masks['whole_object']
    out[f'{name}_median_rel_residual_whole_object'] = float(cp.median(res[inside]))
    pp = [float(cp.median(res[z][inside[z]])) if bool(inside[z].any()) else None for z in range(P.shape[0])]
    out[f'{name}_per_plane_first_mid_last'] = [pp[i] for i in (0, 1, 2, len(pp) // 2, -3, -2, -1)]
out['ref_metrics_self'] = P.metrics(P.ref); out['osem_metrics'] = P.metrics(P.osem)
out['events'] = P.n_ev; out['sens_max'] = float(P.sens.max())
print(json.dumps(out, indent=1))
json.dump(out, open(f'kkt_{P.ds}.json', 'w'), indent=1)
