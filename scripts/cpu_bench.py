import stir, numpy as np, parallelproj_core as ppc, json, time, sys
ds = 'NeuroLF_Esser2'
r = {x['dataset']: x for x in json.load(open('headers_p2_new.json'))}[ds]
nz, ny, nx = r['img_shape']; vox = np.array(r['voxel_mm'], np.float32)
L = np.load(f'study/{ds}_lors.npy', mmap_mode='r')
y = np.asarray(stir.ProjData.read_from_file(f'p2/{ds}/prompts.hs').to_array().as_array())[0].reshape(-1)
nzi = np.nonzero(y > 0)[0]
P = np.asarray(L.reshape(-1, 2, 3)[nzi]); xs = np.ascontiguousarray(P[:, 0]); xe = np.ascontiguousarray(P[:, 1])
img = np.fromfile(f'p2/{ds}/PETRIC/reference_image.v', dtype='<f4').reshape(nz, ny, nx)
org = (-(np.array([nz, ny, nx]) - 1) / 2 * vox).astype(np.float32)
f = np.zeros(len(xs), np.float32); b = np.zeros_like(img)
t = time.time(); ppc.joseph3d_fwd(xs, xe, img, org, vox, f); tf = time.time() - t
t = time.time(); ppc.joseph3d_back(xs, xe, b, org, vox, f); tb = time.time() - t
S = 358927391.0
print(f'threads {sys.argv[1]:>3s}: events {len(xs)}  fwd {tf:.3f}s  back {tb:.3f}s  -> {S/tf/1e6:.0f} M samples/s fwd, {S/tb/1e6:.0f} M back, {S/(tf+tb)/1e6:.0f} M per fwd+back pair')
