"""Timing model of the lane chain: token j enters lane k at
   t[k][j] = max(t[k][j-1] + w[k][j-1], t[k-1][j] + LAT, t[k+1][j-W] (space in lane k+1 input FIFO of depth W))
w[k][j] = 1 + local steps of token j in lane k. Throughput per pass = t[N-1][last] + w."""
import numpy as np, sys
NX = 128
def works(path, L):
    dt = np.dtype([('i0','<i2'),('na','<i2'),('u0','<i4'),('v0','<i4'),('du','<i4'),('dv','<i4'),('mw','<f4'),('y','<f4'),('a','<f4')])
    e = np.fromfile(path, dt)
    SP = NX // L
    n = (e['na'].astype(np.int32) & 0x7fff); i0 = e['i0'].astype(np.int32)
    w = np.ones((L, len(e)), np.int64)
    for k in range(L):
        lo = k*SP
        ks = np.maximum(0, lo - i0); ke = np.minimum(n, lo + SP - i0)
        loc = np.where(i0 == -1000, np.where(e['u0'] == k, n, 0), np.maximum(0, ke - ks))
        w[k] += loc
    return w
def run(w, W, LAT=60):
    L, J = w.shape
    t = np.zeros((L, J), np.int64)
    for j in range(J):
        for k in range(L):
            a = t[k][j-1] + w[k][j-1] if j else 0
            b = t[k-1][j] + LAT if k else 0
            c = t[k+1][j-W] if (k+1 < L and j >= W) else 0
            t[k][j] = max(a, b, c)
    return t[L-1][J-1] + w[L-1][J-1]
for L, p in ((8, 'd8/ev.bin'), (32, 'd32/ev.bin')):
    w = works(p, L)
    J = 2000
    ww = w[:, :J]
    print(f'lanes {L}: max lane work {ww.sum(1).max()}', end='')
    for W in (4, 16, 64, 256, 1024):
        T = run(ww, W)
        print(f' | W={W}: {T} ({ww.sum(1).max()/T:.2f})', end='')
    print()
