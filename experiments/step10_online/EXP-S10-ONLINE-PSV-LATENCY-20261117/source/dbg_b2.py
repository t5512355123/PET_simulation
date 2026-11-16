import cupy as cp
from lmcore import LMProblem
from online import OnlineSAGA
P = LMProblem('NeuroLF_Esser2')
o = OnlineSAGA(P, 32)
wo = P.masks['whole_object']
for b in range(4):
    o.arrive()
    for _ in range(8): o.update()
    print('batch', b + 1, 'zeros in object', float((o.x[wo] <= 0).mean()), 'ref zeros', float((P.ref[wo] <= 0).mean()), 'RMSE', round(P.metrics(o.x)['RMSE_whole_object_minus2'], 3))
