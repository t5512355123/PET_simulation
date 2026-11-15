import sys, time, numpy as np, cupy as cp, parallelproj_core as ppc
d = np.load(sys.argv[1])
nz, ny, nx = [int(v) for v in d['img_shape']]; vox = d['vox'].astype(np.float32)
img = cp.asarray(d['img'].reshape(nz, ny, nx).astype(np.float32))
org = cp.asarray((-(np.array([nz, ny, nx]) - 1) / 2 * vox).astype(np.float32)); voxg = cp.asarray(vox)
xs = cp.asarray(np.ascontiguousarray(d['xs'])); xe = cp.asarray(np.ascontiguousarray(d['xe']))
f = cp.zeros(xs.shape[0], cp.float32); b = cp.zeros_like(img)
S = 358927391.0; R = int(sys.argv[2]) if len(sys.argv) > 2 else 50
for _ in range(3): ppc.joseph3d_fwd(xs, xe, img, org, voxg, f); ppc.joseph3d_back(xs, xe, b, org, voxg, f)
cp.cuda.Device().synchronize()
t = time.time()
for _ in range(R): ppc.joseph3d_fwd(xs, xe, img, org, voxg, f)
cp.cuda.Device().synchronize(); tf = (time.time() - t) / R
t = time.time()
for _ in range(R): ppc.joseph3d_back(xs, xe, b, org, voxg, f)
cp.cuda.Device().synchronize(); tb = (time.time() - t) / R
t0 = time.time()
while time.time() - t0 < float(sys.argv[3] if len(sys.argv) > 3 else 20):
    ppc.joseph3d_fwd(xs, xe, img, org, voxg, f); ppc.joseph3d_back(xs, xe, b, org, voxg, f)
cp.cuda.Device().synchronize()
print(f'events {xs.shape[0]} fwd {tf*1e3:.1f} ms back {tb*1e3:.1f} ms -> {S/tf/1e6:.0f} M/s fwd, {S/tb/1e6:.0f} M/s back, {S/(tf+tb)/1e6:.0f} M/s pair')
