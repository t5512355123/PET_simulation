"""EXP-S15 host layout for the wide chain (same order as slab_ld / slab_st in slab5.cpp).
  pack5.py pack <hw dir> <p>    : img_p<p>.bin (flat (pl, u, z)) -> ddr_img_p<p>.bin (512-bit words in loader order)
  pack5.py unpack <hw dir> <p>  : board_accw_p<p>.bin (words) -> board_acc_p<p>.bin (flat (pl, u, z))
  pack5.py nwords               : number of words per pass"""
import sys
import numpy as np

NPP, NU, NZ, LANES = 82, 163, 95, 32
HU, HZ = (NU + 1) // 2, (NZ + 1) // 2
lo = lambda L: (L * NPP) >> 5
np_ = [lo(L + 1) - lo(L) for L in range(LANES)]
SLOTS = lambda n: n * HU * HZ // 4
SA = SLOTS(2)
l3 = [L for L in range(LANES) if np_[L] == 3]
order = [(L, s) for s in range(SA) for L in range(LANES)] + [(L, s) for s in range(SA, SLOTS(3)) for L in l3]
NW = len(order)


def index_maps():
    """for every word w, group g, bank b: flat voxel index into (NPP, NU, NZ) or -1"""
    idx = np.full((NW, 4, 4), -1, np.int64)
    Ls = np.array([o[0] for o in order]); Ss = np.array([o[1] for o in order])
    for g in range(4):
        a = Ss * 4 + g
        pll = a // (HU * HZ); r = a % (HU * HZ); uh = r // HZ; zh = r % HZ
        pl = np.array([lo(L) for L in Ls]) + pll
        ok_pl = pll < np.array([np_[L] for L in Ls])
        for b in range(4):
            u = 2 * uh + (b & 1); z = 2 * zh + (b >> 1)
            ok = ok_pl & (u < NU) & (z < NZ)
            idx[:, g, b] = np.where(ok, (pl * NU + u) * NZ + z, -1)
    return idx


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'nwords':
        print(NW)
        sys.exit()
    hw, p = sys.argv[2], sys.argv[3]
    idx = index_maps()
    if cmd == 'pack':
        img = np.fromfile(f'{hw}/img_p{p}.bin', '<f4')
        w = np.where(idx >= 0, img[np.clip(idx, 0, None)], 0.0).astype('<f4')
        w.tofile(f'{hw}/ddr_img_p{p}.bin')
    elif cmd == 'unpack':
        w = np.fromfile(f'{hw}/board_accw_p{p}.bin', '<f4').reshape(NW, 4, 4)
        acc = np.zeros(NPP * NU * NZ, '<f4')
        m = idx >= 0
        acc[idx[m]] = w[m]
        acc.tofile(f'{hw}/board_acc_p{p}.bin')
