"""Exact LOR endpoints for every bin of a non-TOF PETRIC dataset, from STIR (same geometry the PETRIC parallelproj projector uses).
Order = ProjData.to_array(): segments 0, 1, -1, 2, -2, ...; inside a segment: axial, view, tangential.
Output: <out>.npy float32 (S, V, T, 2, 3) in (z, y, x) mm, z relative to the scanner centre.
Usage: STIR_CONFIG_DIR=... python -I make_lors_stir.py <prompts.hs> <out_prefix> [nproc]"""
import sys
import time
from multiprocessing import Pool

import numpy as np

HS, OUT = sys.argv[1], sys.argv[2]
NP = int(sys.argv[3]) if len(sys.argv) > 3 else 32


def seg_order(lo, hi):
    out = [0]
    for k in range(1, max(-lo, hi) + 1):
        if k <= hi:
            out.append(k)
        if -k >= lo:
            out.append(-k)
    return out


def work(seg):
    import stir
    pd = stir.ProjData.read_from_file(HS)
    pdi = pd.get_proj_data_info()
    lor = stir.LORInAxialAndNoArcCorrSinogramCoordinates()
    pts = stir.LORAs2Points()
    a0, a1 = pd.get_min_axial_pos_num(seg), pd.get_max_axial_pos_num(seg)
    t0, t1 = pd.get_min_tangential_pos_num(), pd.get_max_tangential_pos_num()
    V = pd.get_num_views()
    out = np.empty((a1 - a0 + 1, V, t1 - t0 + 1, 2, 3), np.float32)
    R = 1000.0  # any radius outside the image; parallelproj clips the ray to the image box
    for ia, ax in enumerate(range(a0, a1 + 1)):
        for v in range(V):
            for it, tg in enumerate(range(t0, t1 + 1)):
                pdi.get_LOR(lor, stir.Bin(seg, v, ax, tg))
                lor.get_intersections_with_cylinder(pts, R)
                p1, p2 = pts.p1(), pts.p2()
                out[ia, v, it, 0] = (p1.z(), p1.y(), p1.x())
                out[ia, v, it, 1] = (p2.z(), p2.y(), p2.x())
    return seg, out


if __name__ == '__main__':
    import stir
    pd = stir.ProjData.read_from_file(HS)
    order = seg_order(pd.get_min_segment_num(), pd.get_max_segment_num())
    t = time.time()
    with Pool(NP) as p:
        res = dict(p.map(work, order, chunksize=1))
    allv = np.concatenate([res[s] for s in order], axis=0)
    np.save(OUT + '.npy', allv)
    print('saved', allv.shape, 'in %.0f s' % (time.time() - t))
