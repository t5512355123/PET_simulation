"""Where does the GPU time of one psv update go (DMI4 TOF list-mode)? cupy events around each part, 20 repeats."""
import os, time, json
os.environ.setdefault('TOF_NSIG', '5')
import numpy as np, cupy as cp
from tofcore import TOFProblem
P = TOFProblem()
M = 8
n = P.n_ev // M
sl = slice(0, n)
x = P.gauss(P.osem, 6.0)
def timeit(f, rep=20):
    f(); cp.cuda.Device().synchronize()
    t = time.perf_counter()
    for _ in range(rep): f()
    cp.cuda.Device().synchronize()
    return (time.perf_counter() - t) / rep * 1e3
g = cp.zeros(P.shape, cp.float32)
res = {}
res['fwd_subset_ms'] = timeit(lambda: P.fwd(sl, x))
w = cp.ones(n, cp.float32)
res['back_subset_ms'] = timeit(lambda: P.back(sl, w, g))
res['lik_grad_subset_ms'] = timeit(lambda: P.lik_grad(sl, x, 1.0 / M))
res['prior_grad_ms'] = timeit(lambda: P.prior_grad(x))
d = cp.zeros_like(x); prec = cp.ones_like(x)
def upd():
    dd = (g - g) * M + g
    y = x + 0.1 * prec * dd
    cp.maximum(y, 0, out=y)
res['update_arith_ms'] = timeit(upd)
res['precond_ms'] = timeit(lambda: P.fov * x / (P.sens + 2.0 * P.prior_diag_hess(P.gauss(x, 5.0)) * x), 5)
res['events_per_subset'] = n
print(json.dumps(res, indent=1))
