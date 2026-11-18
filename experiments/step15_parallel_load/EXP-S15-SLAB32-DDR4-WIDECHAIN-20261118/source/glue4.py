"""Host glue between passes (runs on snoopy, numpy).
  glue4.py finit <hw dir> <p0> <p1> : start values for forward pass p1 = raw sums of pass p0 (same global event), else 0
  glue4.py sback <hw dir> <p1> <p0> : s of forward pass p1 (per global event) -> s_in for back passes p1 and p0
  glue4.py compare <hw dir> <batch dir> : board vs software model, and board vs GPU parallelproj reference"""
import sys
import numpy as np

EV = np.dtype([('i0', '<i2'), ('na', '<i2'), ('u0', '<i4'), ('v0', '<i4'), ('du', '<i4'), ('dv', '<i4'),
               ('mw', '<f4'), ('y', '<f4'), ('a', '<f4')])
NPL, NU, NZ, NPP = 163, 163, 95, 82
cmd, hw = sys.argv[1], sys.argv[2]
f32 = lambda n: np.fromfile(f'{hw}/{n}', '<f4')
i32 = lambda n: np.fromfile(f'{hw}/{n}', '<i4')

if cmd == 'finit':
    p0, p1 = sys.argv[3], sys.argv[4]
    g0, F0 = i32(f'fwd_map_p{p0}.bin'), f32(f'board_fwd_p{p0}.bin')[:len(i32(f'fwd_map_p{p0}.bin'))]
    lut = {int(g): float(f) for g, f in zip(g0, F0)}
    g1 = i32(f'fwd_map_p{p1}.bin')
    np.array([lut.get(int(g), 0.0) for g in g1], '<f4').tofile(f'{hw}/finit_p{p1}.bin')
elif cmd == 'sback':
    p1, p0 = sys.argv[3], sys.argv[4]
    g1 = i32(f'fwd_map_p{p1}.bin')
    s1 = f32(f'board_fwd_p{p1}.bin')[:len(g1)]
    lut = {int(g): float(s) for g, s in zip(g1, s1)}
    for p in (p1, p0):
        gb = i32(f'back_map_p{p}.bin')
        np.array([lut.get(int(g), 0.0) if g >= 0 else 0.0 for g in gb], '<f4').tofile(f'{hw}/s_back_p{p}.bin')
elif cmd == 'compare':
    bd = sys.argv[3]
    ev = np.fromfile(f'{bd}/ev_global.bin', EV)
    s_ref = np.fromfile(f'{bd}/s_ref.bin', '<f8')
    back_ref = np.fromfile(f'{bd}/back_ref.bin', '<f4').astype(np.float64)
    rows = []
    s_board = np.zeros(len(ev))
    back = np.zeros((NZ, NPL, NPL))
    for p in range(4):
        ax, h = p // 2, p % 2
        n = len(i32(f'fwd_map_p{p}.bin'))
        bf, ef = f32(f'board_fwd_p{p}.bin')[:n], f32(f'expect_fwd_p{p}.bin')
        rel = np.abs(bf - ef) / np.maximum(np.abs(ef), 1e-30)
        ba, ea = f32(f'board_acc_p{p}.bin'), f32(f'expect_acc_p{p}.bin')
        rows.append(f'pass {p}: forward {"raw sum" if h == 0 else "ratio s"} max rel diff vs model {rel.max():.3e} '
                    f'(bit-identical {np.sum(bf == ef)}/{n}); back acc max abs diff / max {np.abs(ba - ea).max() / np.abs(ea).max():.3e} '
                    f'(bit-identical {np.sum(ba == ea)}/{ea.size})')
        if h == 1:
            s_board[i32(f'fwd_map_p{p}.bin')] = bf
        acc = ba.reshape(NPP, NU, NZ)
        planes = min(NPP, NPL - h * NPP)
        for pl in range(planes):
            P = h * NPP + pl
            if ax == 0:
                back[:, :, P] += acc[pl].T          # (u = y, z) -> back[z, y, x = P]
            else:
                back[:, P, :] += acc[pl].T          # (u = x, z) -> back[z, y = P, x]
    es = np.abs(s_board / ev['mw'] - s_ref) / s_ref
    eb = np.abs(back.ravel() - back_ref).max() / np.abs(back_ref).max()
    em = np.abs(back.ravel() - np.fromfile(f'{hw}/expect_back.bin', '<f4')).max() / np.abs(back_ref).max()
    rows.append(f'all passes: s vs GPU parallelproj max rel {es.max():.3e} (median {np.median(es):.3e}); '
                f'back vs GPU max abs / max {eb:.3e}; back vs model {em:.3e}')
    print('\n'.join(rows))
