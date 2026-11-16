"""Model check: KKT residual of the list-mode objective at the official reference image.
Interior planes near 0 means projector, c, sensitivity, RDP and beta match the reference reconstruction.
Usage: python -I kkt.py <dataset>"""
import sys, json, time
import numpy as np, cupy as cp
from lmcore import LMProblem

P = LMProblem(sys.argv[1])
x = P.ref.copy()
t = time.time()
g = P.lik_grad(slice(0, P.n_ev), x, 1.0) - P.prior_grad(x)
cp.cuda.Device().synchronize()
# projected-gradient KKT residual: x>0 -> |g|, x==0 -> max(g,0); scale by the sensitivity (EM step size x/s)
res = cp.where(x > 0, cp.abs(g), cp.maximum(g, 0)) / cp.maximum(P.sens, 1e-6)
inside = P.masks['whole_object']
per_plane = [float(cp.median(res[z][inside[z]])) if bool(inside[z].any()) else None for z in range(P.shape[0])]
out = dict(dataset=P.ds, seconds=round(time.time() - t, 2), events=P.n_ev,
           median_rel_residual_whole_object=float(cp.median(res[inside])),
           per_plane_median=per_plane,
           osem_metrics=P.metrics(P.osem), ref_metrics_self=P.metrics(P.ref))
print(json.dumps({k: v for k, v in out.items() if k != 'per_plane_median'}, indent=1))
print('per-plane median residual (first 3, middle, last 3):', per_plane[:3], per_plane[len(per_plane)//2], per_plane[-3:])
json.dump(out, open(f'kkt_{P.ds}.json', 'w'), indent=1)
