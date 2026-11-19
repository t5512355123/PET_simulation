"""GPU baseline (EXP-S16): TOF list-mode psv on GE DMI4 (PETRIC2), time subsets, run to the PETRIC thresholds.
Usage: python run_dmi4.py <M> <max_updates> <out.json>"""
import sys, json, time
import cupy as cp
from dmi4core import TOFProblem
from lm_psv import LMPSV, run

M, nmax, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
P = TOFProblem()
cp.cuda.Device().synchronize(); t0 = time.perf_counter()
alg = LMPSV(P, M)
cp.cuda.Device().synchronize(); t_setup = time.perf_counter() - t0
hist, first = run(P, alg, nmax, True)
h = hist[first - 1] if first else None
res = dict(dataset=P.ds, M=M, setup_s=t_setup, first_pass_update=first, first_pass_epoch=h['epoch'] if h else None,
           first_pass_t_alg_s=h['t_alg'] if h else None, first_pass_proj_epochs=h['proj_epochs'] if h else None, history=hist)
json.dump(res, open(out, 'w'), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != 'history'}, indent=1))
