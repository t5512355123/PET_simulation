"""Online list-mode reconstruction while events arrive (time order), then latency after the last event.

Events arrive in NB equal time batches. Between two arrivals the computer has time for U subset updates
(U models scan length vs compute speed). After the last batch arrives we count the work until the PETRIC
threshold is first reached (and then held for 10 updates), in projection-epochs (1 = every event projected once,
forward + back). Seconds = projection-epochs x (s per projection-epoch of the device).

Methods
  A    : online LM-OSEM on the arrived data (no prior); after the last event run LM-psv (original schedule) from it.
  A6   : same, but the LM-psv start image is the OSEM image after the 6 mm filter (exactly like psv on OSEM).
  B    : online SAGA-psv on growing data: a per-batch likelihood-gradient table; a new batch adds its gradient;
         an update visits subset k (batches b % 8 == k), refreshes their table entries (SAGA), uses the psv
         preconditioner (recomputed at each arrival) and prior f*beta (f = arrived fraction).
  C    : LM-SPDDY is not run here (see report).
Usage: python online.py <dataset> <method> <NB> <U> <out.json>
"""
import json
import sys
import time

import numpy as np
import cupy as cp

from lmcore import LMProblem
import os
os.environ.setdefault("DS", "GE_D690_NEMA_IQ2"); os.environ.setdefault("TOF_NSIG", "5")
from tofcore import TOFProblem
from lm_psv import LMPSV, run

NSUB = 8


class Online:
    def __init__(self, P, NB, seed=1):
        self.P, self.NB = P, NB
        e = np.linspace(0, P.n_ev, NB + 1).astype(int)
        self.batches = [slice(e[b], e[b + 1]) for b in range(NB)]
        self.nb = [int(e[b + 1] - e[b]) for b in range(NB)]
        self.arrived = 0
        self.rng = np.random.RandomState(seed)
        self.order = []

    def frac(self):
        return sum(self.nb[:self.arrived]) / self.P.n_ev

    def subset_batches(self, k):
        return [b for b in range(self.arrived) if b % NSUB == k]

    def next_subset(self):
        ks = [k for k in range(NSUB) if self.subset_batches(k)]
        if not self.order:
            o = np.array(ks); self.rng.shuffle(o); self.order = o.tolist()
        return self.order.pop()


class OnlineEM(Online):
    """LM-OSEM over the arrived data: x <- x / s_k * A_k^T(m/yhat) with s_k = share of sensitivity."""
    def __init__(self, P, NB):
        super().__init__(P, NB)
        self.x = None

    def arrive(self):
        self.arrived += 1
        if self.x is None:
            tot = self.nb[0]                                        # flat start with the right total counts
            s = self.P.sens * (self.nb[0] / self.P.n_ev)
            self.x = (self.P.fov * float(tot / float(cp.sum(s * self.P.fov)))).astype(cp.float32)

    def update(self):
        P = self.P
        k = self.next_subset()
        bs = self.subset_batches(k)
        n = sum(self.nb[b] for b in bs)
        back = cp.zeros_like(self.x)
        for b in bs:
            back += P.lik_grad(self.batches[b], self.x, 0.0)        # c*A^T(m/yhat), no sensitivity
        s = cp.maximum(P.sens * (n / P.n_ev), 1e-6)
        self.x = P.fov * self.x * back / s


class OnlineSAGA(Online):
    def __init__(self, P, NB, s0=3.5, eta=0.01, smin=1.0, delta_rel=1e-3):
        super().__init__(P, NB)
        self.delta_rel = delta_rel
        self.G = [None] * NB
        self.g_sum = None
        self.x = None
        self.u = 0
        self.s0, self.eta, self.smin = s0, eta, smin
        self.precond = None

    def calc_precond(self):
        P = self.P
        xs = P.gauss(self.x, 5.0)
        s_all = cp.maximum(P.sens * self.frac(), 1e-6)
        # psv main.py option _precond_delta_rel (0 there): keeps voxels that hit 0 from freezing (P ~ x)
        xd = self.x + self.delta_rel * float(xs.max())
        return P.fov * xd / (s_all + 2.0 * self.frac() * P.prior_diag_hess(xs) * xd)

    def arrive(self):
        P = self.P
        b = self.arrived
        self.arrived += 1
        if self.x is None:                                          # flat start, 2 LM-EM passes on batch 0
            em = OnlineEM(P, self.NB); em.arrive()
            for _ in range(2 * NSUB):
                em.update()
            self.x = P.gauss(em.x, 6.0)                            # psv: 6 mm pre-filter of the start image
        self.since_full = None                                      # snapshot refresh on the next update
        self.order = []

    def refresh_all(self):
        """SVRG snapshot over the arrived data + preconditioner (psv full-gradient update)."""
        P = self.P
        self.precond = self.calc_precond()
        self.g_sum = cp.zeros_like(self.x)
        for b in range(self.arrived):
            self.G[b] = P.lik_grad(self.batches[b], self.x, self.nb[b] / P.n_ev)
            self.g_sum += self.G[b]
        self.since_full = 0
        return self.g_sum - self.frac() * P.prior_grad(self.x)

    def update(self):
        P = self.P
        step = max(self.s0 / (1 + self.eta * self.u), self.smin)
        if self.since_full is None or self.since_full >= 2 * NSUB:
            d = self.refresh_all()
        else:
            if self.since_full == 4:
                self.precond = self.calc_precond()                  # psv also refreshes P at update 4
            k = self.next_subset()
            bs = self.subset_batches(k)
            n_k = sum(self.nb[b] for b in bs); n_arr = sum(self.nb[:self.arrived])
            corr = sum(P.lik_grad(self.batches[b], self.x, self.nb[b] / P.n_ev) - self.G[b] for b in bs)
            d = corr * (n_arr / n_k) + self.g_sum - self.frac() * P.prior_grad(self.x)
            self.since_full += 1
        self.x += step * self.precond * d
        cp.maximum(self.x, 0, out=self.x)
        self.u += 1


def latency_run(P, obj, max_updates):
    """after the last arrival: updates until PETRIC threshold (first update of a 10-in-a-row window)."""
    streak, first, hist = 0, None, []
    p0 = P.n_proj
    for i in range(max_updates):
        mt = P.metrics(obj.x)
        ok = P.passed(mt)
        streak = streak + 1 if ok else 0
        hist.append(dict(i=i, proj_epochs=(P.n_proj - p0) / P.n_ev, passed=ok, **mt))
        if streak == 10:
            first = i - 9
            break
        obj.update()
    return first, hist


if __name__ == '__main__':
    ds, method, NB, U, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    P = TOFProblem(ds)
    t0 = time.perf_counter()
    res = dict(dataset=ds, method=method, NB=NB, U=U)
    if method in ('A', 'A6'):
        obj = OnlineEM(P, NB)
        for b in range(NB):
            obj.arrive()
            for _ in range(U):
                obj.update()
        p_acq = P.n_proj / P.n_ev
        res['metrics_at_last_event'] = P.metrics(obj.x)
        P.n_proj = 0
        x0 = P.gauss(obj.x, 6.0) if method == 'A6' else obj.x
        alg = LMPSV(P, NSUB, x0=x0)
        hist, first = run(P, alg, 400, True, label=method + ' ')
        res.update(acq_proj_epochs=p_acq, post_first_pass_update=first,
                   post_proj_epochs=hist[first - 1]['proj_epochs'] if first else None, post_history=hist)
    else:
        obj = OnlineSAGA(P, NB)
        traj = []
        for b in range(NB):
            obj.arrive()
            for _ in range(U if b < NB - 1 else 0):
                obj.update()
            if b < NB - 1:
                mt = P.metrics(obj.x)
                traj.append(dict(batch=b + 1, frac=obj.frac(), proj_epochs=P.n_proj / P.n_ev,
                                 RMSEw2=mt['RMSE_whole_object_minus2'], RMSEb=mt['RMSE_background'],
                                 maxAEM=max(v for k, v in mt.items() if k.startswith('AEM'))))
                print(f'B batch {b+1:3d}/{NB} f={obj.frac():.3f} proj_ep={P.n_proj/P.n_ev:7.2f} RMSEw2={traj[-1]["RMSEw2"]:.4f} '
                      f'RMSEb={traj[-1]["RMSEb"]:.4f} maxAEM={traj[-1]["maxAEM"]:.4f}', flush=True)
        p_acq_before_last = traj[-1]['proj_epochs'] if traj else 0.0
        last_batch_epochs = P.n_proj / P.n_ev - p_acq_before_last
        res['metrics_at_last_event'] = P.metrics(obj.x)
        if method == 'Br':
            obj.u = 0                                               # restart the psv step schedule after the last event
        first, hist = latency_run(P, obj, 400)
        post = last_batch_epochs + (hist[first]['proj_epochs'] if first is not None else float('nan'))
        print(f'B after last event: first pass after {first} updates, {post:.3f} projection-epochs (incl. last batch gradient)')
        res.update(acq_proj_epochs=p_acq_before_last, post_first_pass_update=first, post_proj_epochs=post,
                   trajectory=traj, post_history=hist)
    res['wall_s'] = time.perf_counter() - t0
    json.dump(res, open(out, 'w'), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k not in ('post_history', 'trajectory')}, indent=1))
