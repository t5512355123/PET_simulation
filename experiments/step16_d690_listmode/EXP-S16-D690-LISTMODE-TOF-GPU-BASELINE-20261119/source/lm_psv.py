"""List-mode psv (Speedy PETRIC2 winner, MaGeZ ALG1) on the GPU.

Same algorithm as PETRIC2-Speedy main.py (commit 3cb1173), except:
  - subsets are contiguous blocks of events in time order (not view subsets);
  - subset sensitivity s_k = s / M (one sensitivity image, computed once).
Schedule (unchanged): full gradient at the start of every even epoch; preconditioner at update 4 and at the start of
epoch 1; step 3.5/(1+0.01 u); 6 mm Gaussian pre-filter of OSEM; 5 mm filter before the RDP diagonal Hessian;
P = fov * x / (s + 2 * diagH(x_sm) * x); prior gradient per subset = beta/M * gradR.

Usage: python lm_psv.py <dataset> <M> <max_updates> <out.json> [x0.npy]
"""
import json
import sys
import time

import numpy as np
import cupy as cp

from lmcore import LMProblem


class LMPSV:
    def __init__(self, P, M, x0=None, s0=3.5, eta=0.01, seed=1, ev_range=None):
        self.P, self.M = P, M
        n0, n1 = ev_range if ev_range else (0, P.n_ev)
        edges = np.linspace(n0, n1, M + 1).astype(int)
        self.sub = [slice(edges[k], edges[k + 1]) for k in range(M)]
        self.frac = [(edges[k + 1] - edges[k]) / P.n_ev for k in range(M)]
        self.x = P.gauss(P.osem, 6.0) if x0 is None else x0.copy()
        self.s_all = cp.maximum(P.sens * ((n1 - n0) / P.n_ev), 1e-6)
        self.s0, self.eta = s0, eta
        self.u = 0
        self.rng = np.random.RandomState(seed)
        self.order = []
        self.g_tab = [None] * M
        self.g_sum = None
        self.precond = self.calc_precond(self.x)

    def calc_precond(self, x):
        xs = self.P.gauss(x, 5.0)
        return self.P.fov * x / (self.s_all + 2.0 * self.P.prior_diag_hess(xs) * x)

    def sub_grad(self, k, x, gp):
        return self.P.lik_grad(self.sub[k], x, self.frac[k]) - gp / self.M

    def full_grad(self):
        gp = self.P.prior_grad(self.x)
        self.g_sum = cp.zeros_like(self.x)
        for k in range(self.M):
            self.g_tab[k] = self.sub_grad(k, self.x, gp)
            self.g_sum += self.g_tab[k]

    def update(self):
        M, u = self.M, self.u
        epoch = u // M
        full = (u % M == 0) and (epoch % 2 == 0)
        step = self.s0 / (1 + self.eta * u)
        if (epoch == 1 and u % M == 0) or u == 4:
            self.precond = self.calc_precond(self.x)
        if full:
            self.full_grad()
            d = self.g_sum
        else:
            if not self.order:
                o = np.arange(M); self.rng.shuffle(o); self.order = o.tolist()
            k = self.order.pop()
            gp = self.P.prior_grad(self.x)
            d = (self.sub_grad(k, self.x, gp) - self.g_tab[k]) * M + self.g_sum
        self.x += step * self.precond * d
        cp.maximum(self.x, 0, out=self.x)
        self.u += 1
        return full


def run(P, alg, max_updates, log, label=''):
    hist, streak, first = [], 0, None
    t_alg = 0.0
    for i in range(max_updates):
        cp.cuda.Device().synchronize(); t = time.perf_counter()
        full = alg.update()
        cp.cuda.Device().synchronize(); t_alg += time.perf_counter() - t
        mt = P.metrics(alg.x)
        ok = P.passed(mt)
        streak = streak + 1 if ok else 0
        if streak == 10 and first is None:
            first = i + 1 - 9          # first update of the 10-in-a-row window
        hist.append(dict(update=alg.u, epoch=alg.u / alg.M, full=full, t_alg=round(t_alg, 4),
                         proj_epochs=P.n_proj / P.n_ev, passed=ok, **mt))
        if log and (i < 3 or full or i % 8 == 7 or (first and i + 1 == first + 9)):
            print(f'{label}upd {alg.u:4d} ep {alg.u/alg.M:5.2f} {"F" if full else " "} t={t_alg:7.2f}s proj_ep={P.n_proj/P.n_ev:5.2f} '
                  f'RMSEw2={mt["RMSE_whole_object_minus2"]:.4f} RMSEb={mt["RMSE_background"]:.4f} '
                  f'maxAEM={max(v for k, v in mt.items() if k.startswith("AEM")):.4f} {"PASS" if ok else ""}', flush=True)
        if first is not None and i + 1 >= first + 9 + 5:
            break
    return hist, first


if __name__ == '__main__':
    ds, M, nmax, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    P = LMProblem(ds)
    x0 = cp.asarray(np.load(sys.argv[5])) if len(sys.argv) > 5 else None
    cp.cuda.Device().synchronize(); t0 = time.perf_counter()
    alg = LMPSV(P, M, x0=x0)
    cp.cuda.Device().synchronize(); t_setup = time.perf_counter() - t0
    hist, first = run(P, alg, nmax, True)
    h = hist[first - 1] if first else None
    res = dict(dataset=ds, M=M, setup_s=t_setup, first_pass_update=first,
               first_pass_epoch=h['epoch'] if h else None, first_pass_t_alg_s=h['t_alg'] if h else None,
               first_pass_proj_epochs=h['proj_epochs'] if h else None, history=hist)
    json.dump(res, open(out, 'w'), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != 'history'}, indent=1))
