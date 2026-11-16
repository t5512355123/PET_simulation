"""Run the unmodified PETRIC2 Speedy psv main.py on one PETRIC2 dataset, step by step, with timing.

usage: python run_psv_local.py <dataset_dir> <out_dir> [max_seconds] [max_epochs]
Timing follows petric.py: clock starts after get_data(); metric evaluation is excluded.
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / 'shim'), str(HERE / 'team_code')]

import numpy as np  # noqa: E402
import prof  # noqa: E402

D = Path(sys.argv[1])
OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
MAX_S = float(sys.argv[3]) if len(sys.argv) > 3 else 900
MAX_EP = float(sys.argv[4]) if len(sys.argv) > 4 else 40
EXTRA = 24  # keep running a few more updates after the alternative criterion is met

log = open(OUT / 'run_log.txt', 'w', buffering=1, encoding='utf-8')
def say(*a):
    s = ' '.join(str(x) for x in a); print(s, flush=True); log.write(s + '\n')

def delta(a, b):
    return {k: b.get(k, 0) - a.get(k, 0) for k in set(a) | set(b) if abs(b.get(k, 0) - a.get(k, 0)) > 0}

# ---------------- phase 0: imports (sirf shim = STIR, cupy) ----------------
t = time.perf_counter()
import sirf.STIR as STIR  # noqa: E402
from petric import get_data, QualityMetrics  # noqa: E402
t_import = time.perf_counter() - t

# ---------------- phase 1: read data (not timed by PETRIC) ----------------
p0 = prof.snapshot(); t = time.perf_counter()
data = get_data(D)
t_read = time.perf_counter() - t
read_breakdown = delta(p0, prof.snapshot())
say(f'[read] {t_read:.2f} s  {read_breakdown}')
qm = QualityMetrics(data.reference_image, data.whole_object_mask, data.background_mask, data.voi_masks)
m0 = qm.evaluate(data.OSEM_image)
say('[metrics OSEM]', {k: round(v, 4) for k, v in m0.items()})

# ---------------- phase 2: competition clock starts: Submission() setup ----------------
p0 = prof.snapshot(); t0 = time.perf_counter()
import main  # noqa: E402  (team code, unmodified)
import rdp as _rdp  # noqa: E402  time the python RDP diagonal Hessian (used only for the preconditioner)
_orig_dh = _rdp.RDP.diag_hessian
def _timed_dh(self, x):
    with prof.sec('precond_rdp_diag_hessian(GPU cupy)'):
        r = _orig_dh(self, x)
        if hasattr(r, 'device') and 'cupy' in type(r).__module__:
            import cupy; cupy.cuda.Device().synchronize()
        return r
_rdp.RDP.diag_hessian = _timed_dh
algo = main.Submission(data, update_objective_interval=np.iinfo(np.int32).max)
t_setup = time.perf_counter() - t0
setup_breakdown = delta(p0, prof.snapshot())
say(f'[setup] {t_setup:.2f} s  num_subsets={algo._num_subsets}  {setup_breakdown}')

# sanity check: STIR sensitivity vs our parallelproj model (EXP-S6 sensitivity.npy, c*A^T m)
sens_ref = Path('D:/PET_DATA/listmode') / D.name / 'sensitivity.npy'
sanity = {}
if sens_ref.is_file():
    s_stir = algo._adjoint_ones.as_array()
    s_pp = np.load(sens_ref)
    if s_pp.shape == s_stir.shape:
        msk = s_pp > 0.05 * s_pp.max()
        ratio = s_stir[msk] / s_pp[msk]
        sanity = {'sens_ratio_median': float(np.median(ratio)), 'sens_ratio_p1': float(np.percentile(ratio, 1)),
                  'sens_ratio_p99': float(np.percentile(ratio, 99))}
        say('[sanity sensitivity STIR / parallelproj model]', sanity)

# STIR projector timers (if they count parallelproj work)
obj = sys.modules['sirf.contrib.partitioner.partitioner'].data_partition.obj
try:
    fp = obj.get_projector_pair().get_forward_projector(); bp = obj.get_projector_pair().get_back_projector()
    def proj_timers():
        return fp.get_wall_clock_timer_value(), bp.get_wall_clock_timer_value()
    proj_timers()
except Exception as e:  # pragma: no cover
    say('no projector timers', e); proj_timers = lambda: (0.0, 0.0)

# ---------------- phase 3: iterations ----------------
records = []
t_comp = t_setup
consec = 0
pass_update = None
consec2 = 0
pass2_update = None
wz, wy, wx = qm.whole_object_indices
keep = wz < algo.x.shape[0] - 2
W2 = (wz[keep], wy[keep], wx[keep])
x_init = algo.x.as_array()
while True:
    M = algo._num_subsets
    upd = algo._update
    full = (upd % M == 0) and (upd // M) in algo._complete_gradient_epochs
    precond = ((upd // M) in algo._precond_update_epochs and upd % M == 0) or upd == 4
    p0 = prof.snapshot(); f0, b0 = proj_timers(); t = time.perf_counter()
    algo.update(); algo.iteration += 1
    dt = time.perf_counter() - t
    f1, b1 = proj_timers()
    br = delta(p0, prof.snapshot())
    t_comp += dt
    with prof.sec('metrics_excluded'):
        met = qm.evaluate(algo.x)
        xa = algo.x.as_array()
        met_x2 = float(np.sqrt(np.mean((qm.ref_im_arr[W2] - xa[W2]) ** 2)) / qm.norm)
    ok = qm.passed(met)
    ok2 = qm.passed({**met, 'RMSE_whole_object': met_x2})
    consec2 = consec2 + 1 if ok2 else 0
    if consec2 >= 10 and pass2_update is None:
        pass2_update = algo.iteration
    consec = consec + 1 if ok else 0
    if consec >= 10 and pass_update is None:
        pass_update = algo.iteration
    rec = dict(update=algo.iteration, epoch=algo.iteration / M, full_gradient=bool(full), precond=bool(precond),
               dt=dt, t_comp=t_comp, step=algo._step_size, breakdown=br, fp_timer=f1 - f0, bp_timer=b1 - b0,
               metrics=met, RMSE_whole_excl_last2=met_x2, passed=ok, passed_excl_last2=ok2)
    records.append(rec)
    say(f'[upd {algo.iteration:4d} ep {algo.iteration / M:5.2f}] {"FULL " if full else "     "}{"P " if precond else "  "}'
        f'dt={dt:6.3f}s t={t_comp:7.2f}s RMSEw={met["RMSE_whole_object"]:.4f} RMSEb={met["RMSE_background"]:.4f} '
        f'maxAEM={max(v for k, v in met.items() if k.startswith("AEM")):.4f} RMSEw-2={met_x2:.4f} pass={ok} consec={consec} pass-2={ok2} consec2={consec2}')
    if algo.iteration in (1, 8, 16, 40, 80) or algo.iteration in (pass_update, pass2_update, (pass2_update or 0) - 9):
        np.save(OUT / f'x_upd{algo.iteration:04d}.npy', algo.x.as_array())
    if pass_update is not None or (pass2_update is not None and algo.iteration >= pass2_update + EXTRA):
        break
    if t_comp > MAX_S or algo.iteration / M >= MAX_EP:
        say('[stop] limit reached without passing'); break

np.save(OUT / 'x_final.npy', algo.x.as_array())
np.save(OUT / 'x_init.npy', x_init)
np.save(OUT / 'x_ref.npy', data.reference_image.as_array())
np.save(OUT / 'x_osem.npy', data.OSEM_image.as_array())

summary = dict(dataset=D.name, num_subsets=algo._num_subsets, t_import=t_import, t_read=t_read,
               read_breakdown=read_breakdown, t_setup=t_setup, setup_breakdown=setup_breakdown,
               sanity=sanity, pass_update=pass_update, pass2_update=pass2_update,
               pass2_time_competition=(records[pass2_update - 10]['t_comp'] if pass2_update else None),
               pass_time_competition=(records[pass_update - 1]['t_comp'] if pass_update else None),
               threshold_first_reached=(pass_update - 9 if pass_update else None),
               total_updates=len(records), totals=prof.snapshot(), counts=dict(prof.cnt),
               metrics_osem=m0, image_shape=list(x_init.shape), spacing=list(data.OSEM_image.spacing),
               stir_threads=8, records=records)
json.dump(summary, open(OUT / 'summary.json', 'w'), indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
say('[done]', {k: summary[k] for k in ('pass_update', 'pass_time_competition', 'total_updates', 't_setup')})
