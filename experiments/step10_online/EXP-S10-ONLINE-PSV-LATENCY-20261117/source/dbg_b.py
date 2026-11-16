import numpy as np, cupy as cp
from lmcore import LMProblem
from online import OnlineSAGA, OnlineEM
P = LMProblem('NeuroLF_Esser2')
o = OnlineSAGA(P, 32)
o.arrive()
print('after EM warm start on batch0: mean x in obj', float(o.x[P.masks['whole_object']].mean()), 'ref', float(P.ref[P.masks['whole_object']].mean()))
for b in range(31): o.arrive()
o.update()
print('frac', o.frac())
full = P.lik_grad(slice(0, P.n_ev), o.x, 1.0) if False else o.g_sum
print('g_sum vs full lik grad rel diff', float(cp.abs(o.g_sum - full).max() / cp.abs(full).max()))
print('precond mean', float(o.precond[P.masks['whole_object']].mean()))
for i in range(40):
    o.update()
    if i % 5 == 4:
        mt = P.metrics(o.x); print(i, round(mt['RMSE_whole_object_minus2'], 4), round(mt['RMSE_background'], 4), 'mean', float(o.x[P.masks['whole_object']].mean()))
