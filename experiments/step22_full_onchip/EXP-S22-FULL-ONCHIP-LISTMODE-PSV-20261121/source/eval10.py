"""EXP-S19: PETRIC metrics of the FPGA iterates x_1..x_50 (read back from the board) and the first pass update with the
same rule as the GPU run (10 consecutive passing updates); comparison with the GPU psv iterates in the same storage
formats (run_tof_hw8gp.py) and with the fp32 GPU run (2.39 s, first pass at update 40).
Usage (env pp): python eval10.py <run dir> [board time us for 40 updates]"""
import json, os, sys
import numpy as np
import cupy as cp
LMP = 'C:/Users/t5512/AppData/Local/Temp/claude/9d475279f3617f93/5142366d-c9a0-40dd-a9b5-3424c81b8845/scratchpad/lmpsv'
sys.path.insert(0, LMP)
os.environ['DS'] = 'GE_D690_NEMA_IQ2'
import tofcore                         # noqa: E402
RD = sys.argv[1]
T40 = float(sys.argv[2]) * 1e-6 if len(sys.argv) > 2 else None
W = os.environ.get('PREPW', 'D:/PET/claude_house/work/r2_fpga/GE_D690_NEMA_IQ2')
NZ, NP, L, NT = 47, 201, 40, 5
NSL = NZ * 40000
n = np.arange(NSL)
si = n % L; sk = (n // L) % L; sT = (n // (L * L)) % (NT * NT); sz = n // (L * L * NT * NT)
sy = L * (sT // NT) + si; sx = L * (sT % NT) + (si + sk) % L
x0 = np.load(f'{W}/x0.npy').astype(np.float32)
P = tofcore.TOFProblem(sens=False) if 'sens' in tofcore.TOFProblem.__init__.__code__.co_varnames else tofcore.TOFProblem()
hist, streak, first = [], 0, None
for u in range(1, 51):
    fn = os.path.join(RD, f'board_x{u}.bin')
    if not os.path.exists(fn):
        break
    s = np.fromfile(fn, '<f4')[:NSL]
    x = x0.copy()
    x[sz, sy, sx] = s
    mt = P.metrics(cp.asarray(x))
    ok = P.passed(mt)
    streak = streak + 1 if ok else 0
    if streak == 10 and first is None:
        first = u - 9
    hist.append(dict(update=u, passed=bool(ok), **mt))
    print(u, 'PASS' if ok else '    ', ' '.join(f'{k}={v:.4f}' for k, v in mt.items() if k.startswith('RMSE')),
          f"maxAEM={max(v for k, v in mt.items() if k.startswith('AEM')):.4f}")
res = dict(first_pass_update=first, updates_read=len(hist), history=hist)
if T40 is not None:
    res['fpga_time_40_updates_s'] = T40
    GT = float(os.environ.get('GPU_T', '2.39'))   # GPU fp32 list-mode psv to its first pass (same events)
    res['gpu_time_s'] = GT
    res['speedup'] = GT / T40
# GPU iterates in the hardware storage formats (same schedule) for comparison, if available
ref = os.environ.get('GPUREF', os.path.join(LMP, 'd690_psv_hw8gp_bf16.json'))
if os.path.exists(ref):
    g = json.load(open(ref))
    res['gpu_hwformat_first_pass'] = g.get('first_pass_update')
    gh = {h['update']: h for h in g['history']}
    dif = []
    for h in hist:
        if h['update'] in gh:
            dif.append(max(abs(h[k] - gh[h['update']][k]) for k in h if k.startswith(('RMSE', 'AEM'))))
    res['max_metric_diff_vs_gpu_hwformat'] = float(max(dif)) if dif else None
json.dump(res, open(os.path.join(RD, 'eval10.json'), 'w'), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != 'history'}, indent=1))
