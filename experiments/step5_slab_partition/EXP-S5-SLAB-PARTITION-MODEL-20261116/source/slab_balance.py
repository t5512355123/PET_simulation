import sys, numpy as np
d = np.load(sys.argv[1])
nz, ny, nx = [int(v) for v in d['img_shape']]; vox = d['vox'].astype(np.float64)  # vox order z,y,x
xs, xe = d['xs'].astype(np.float64), d['xe'].astype(np.float64)   # (N,3) in z,y,x mm
print('image', nz, ny, nx, 'voxels', nz*ny*nx, 'vox mm', vox, 'events', len(xs))
dd = np.abs(xe - xs) / vox
ax = np.argmax(dd[:, 1:], 1) + 1        # principal transaxial axis (1=y, 2=x); PET rays are transaxial-dominant
print('axial-dominant fraction', np.mean(np.argmax(dd, 1) == 0))
org = -(np.array([nz, ny, nx]) - 1) / 2 * vox
n = np.array([ny, nx])
tot = 0; hist = {}
for N in (4, 8, 16, 32):
    loads = np.zeros(N); steps_all = 0; maxev = []
    for a in (1, 2):
        m = ax == a
        p0 = (xs[m, a] - org[a]) / vox[a]; p1 = (xe[m, a] - org[a]) / vox[a]
        lo = np.clip(np.ceil(np.minimum(p0, p1)), 0, n[a-1]-1); hi = np.clip(np.floor(np.maximum(p0, p1)), 0, n[a-1]-1)
        L = n[a-1]; edges = np.linspace(0, L, N+1)
        for k in range(N):
            s = np.clip(np.minimum(hi+1, edges[k+1]) - np.maximum(lo, edges[k]), 0, None)
            loads[k] += s.sum()
        steps_all += (hi - lo + 1).sum()
    print(f'N={N:2d} slabs: total steps {steps_all:.3e}, max/mean lane load {loads.max()/loads.mean():.3f}, efficiency {loads.mean()/loads.max():.3f}')
for prec, b in (('fp32', 4), ('fp16', 2)):
    print(f'{prec}: one image copy {nz*ny*nx*b*8/1e6:.1f} Mb; two copies (x-slab + y-slab) {2*nz*ny*nx*b*8/1e6:.1f} Mb; S10 2800 M20K total 234 Mb')
