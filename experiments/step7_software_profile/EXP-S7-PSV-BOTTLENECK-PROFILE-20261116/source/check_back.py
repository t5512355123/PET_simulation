import time, numpy as np, cupy as cp, parallelproj_core as ppc, numba
lors = np.load('D:/PET_DATA/listmode/NeuroLF_Esser2/lors_all.npy', mmap_mode='r')
ymA = np.load('D:/PET_DATA/listmode/NeuroLF_Esser2/sino_y_m_a.npy', mmap_mode='r')
A_, V, T = lors.shape[:3]
views = np.arange(0, V, 8)
L = np.ascontiguousarray(lors[:, views].reshape(-1, 2, 3)); y = np.ascontiguousarray(ymA[0].reshape(A_, V, T)[:, views].reshape(-1))
shape = (95, 163, 163); vs = np.full(3, 1.6565, np.float32); org = (-(np.array(shape) - 1) / 2 * vs).astype(np.float32)
xs, xe = cp.asarray(np.ascontiguousarray(L[:, 0])), cp.asarray(np.ascontiguousarray(L[:, 1])); orgg, vsg = cp.asarray(org), cp.asarray(vs)
nz = np.nonzero(y > 0)[0]
def tb(val, xs_, xe_, n=10):
    acc = cp.zeros(shape, cp.float32); ppc.joseph3d_back(xs_, xe_, acc, orgg, vsg, val); cp.cuda.Device().synchronize()
    t = time.perf_counter()
    for _ in range(n): ppc.joseph3d_back(xs_, xe_, acc, orgg, vsg, val)
    cp.cuda.Device().synchronize(); return (time.perf_counter() - t) / n * 1e3
ones = cp.ones(y.size, cp.float32)
sparse_val = cp.asarray((y > 0).astype(np.float32))
print('dense LORs, all values 1      : %.1f ms' % tb(ones, xs, xe))
print('dense LORs, value 0 where y=0 : %.1f ms' % tb(sparse_val, xs, xe))
nzg = cp.asarray(nz)
print('only non-zero LORs (bin order): %.1f ms  (%d LORs)' % (tb(cp.ones(nz.size, cp.float32), xs[nzg], xe[nzg]), nz.size))
p = cp.asarray(np.random.default_rng(0).permutation(nz.size))
print('only non-zero LORs (random)   : %.1f ms' % tb(cp.ones(nz.size, cp.float32), xs[nzg][p], xe[nzg][p]))
@numba.njit(parallel=True, fastmath=True)
def upd(x, a, b, c, d, e, f, step, ns):
    xf = x.ravel(); af = a.ravel(); bf = b.ravel(); cf = c.ravel(); df = d.ravel(); ef = e.ravel(); ff = f.ravel()
    for i in numba.prange(xf.size):
        v = xf[i] + step * ff[i] * ((af[i] - bf[i] - cf[i] - df[i]) * ns + ef[i])
        xf[i] = v if v > 0 else 0.0
arr = [np.random.rand(*shape).astype(np.float32) for _ in range(7)]
upd(*arr, np.float32(1), np.float32(8)); t = time.perf_counter()
for _ in range(20): upd(*arr, np.float32(1), np.float32(8))
print('numba image update 7 arrays   : %.2f ms' % ((time.perf_counter() - t) / 20 * 1e3))
t = time.perf_counter()
for _ in range(5): np.maximum(arr[0] + 1.0 * (arr[6] * ((arr[1] - arr[2] - arr[3] - arr[4]) * 8 + arr[5])), 0)
print('numpy image update            : %.2f ms' % ((time.perf_counter() - t) / 5 * 1e3))
