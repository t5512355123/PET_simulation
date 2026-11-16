"""Convert a PETRIC (non-TOF) prompts sinogram into list-mode events.

Each bin with y counts becomes y events. Time stamps are synthetic: the sinogram keeps no time order, so the
events are spread uniformly over the frame and sorted (a homogeneous Poisson process, exact for a static scan).
Re-histogramming the events gives the prompts sinogram back exactly.

Per event we store:
  t        float64  time in the frame, 0..1 (the PETRIC headers have no frame duration)
  bin      uint32   flat index in ProjData.to_array() order (segments 0,1,-1,2,-2,...; axial, view, tangential)
  (crystal IDs are not stored: STIR's Python interface does not expose bin -> detector pair for BlocksOnCylindrical;
   the exact LOR end points of each bin are stored instead, which is what the projector needs)
  m, a     float32  multiplicative factor and additive term of that LOR (the SIRF model: yhat = m * (c*A x + a))

Outputs in <out_dir>:
  events.npy        structured array, sorted by t
  lor_nz.npy        float32 (N_nonzero_bins, 2, 3) LOR end points (z, y, x) mm for the non-zero bins, aligned with bins_nz.npy
  bins_nz.npy       uint32 non-zero bin indices
  lors_all.npy      float32 (S, V, T, 2, 3) end points for every bin (needed for the sensitivity image)
  meta.json

Usage: python -I sino2lm.py <dataset_dir> <out_dir> [nproc] [seed]
"""
import json
import os
import sys
import time
import hashlib
from multiprocessing import Pool

import numpy as np

SRC, OUT = sys.argv[1], sys.argv[2]
NP = int(sys.argv[3]) if len(sys.argv) > 3 else 8
SEED = int(sys.argv[4]) if len(sys.argv) > 4 else 20261116
HS = os.path.join(SRC, 'prompts.hs')


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
    for ia, ax in enumerate(range(a0, a1 + 1)):
        for v in range(V):
            for it, tg in enumerate(range(t0, t1 + 1)):
                b = stir.Bin(seg, v, ax, tg)
                pdi.get_LOR(lor, b)
                lor.get_intersections_with_cylinder(pts, 1000.0)
                p1, p2 = pts.p1(), pts.p2()
                out[ia, v, it, 0] = (p1.z(), p1.y(), p1.x())
                out[ia, v, it, 1] = (p2.z(), p2.y(), p2.x())
    return seg, out


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 24), b''):
            h.update(blk)
    return h.hexdigest()


if __name__ == '__main__':
    import stir
    os.makedirs(OUT, exist_ok=True)
    t_start = time.time()
    rd = lambda n: np.asarray(stir.ProjData.read_from_file(os.path.join(SRC, n)).to_array().as_array()).reshape(-1)
    y, m, a = rd('prompts.hs'), rd('mult_factors.hs'), rd('additive_term.hs')
    assert y.shape == m.shape == a.shape
    yi = np.rint(y).astype(np.int64)
    assert np.all(np.abs(y - yi) == 0) and yi.min() >= 0, 'prompts are not non-negative integers'
    pd = stir.ProjData.read_from_file(HS)
    assert 'TOF' not in open(HS, encoding='latin-1').read().upper().replace('TOF MIXING', ''), 'TOF data: not handled by this script'
    order = seg_order(pd.get_min_segment_num(), pd.get_max_segment_num())

    t0 = time.time()
    with Pool(NP) as p:
        res = dict(p.map(work, order, chunksize=1))
    lors = np.concatenate([res[s] for s in order], axis=0)
    t_lor = time.time() - t0
    assert lors.reshape(-1, 2, 3).shape[0] == y.size

    nz = np.nonzero(yi > 0)[0].astype(np.uint32)
    counts = yi[nz]
    n_ev = int(counts.sum())
    rng = np.random.default_rng(SEED)
    ev_bin = np.repeat(nz, counts)
    t = rng.random(n_ev)
    o = np.argsort(t, kind='stable')
    ev = np.empty(n_ev, dtype=[('t', 'f8'), ('bin', 'u4'), ('m', 'f4'), ('a', 'f4')])
    ev['t'] = t[o]
    ev['bin'] = ev_bin[o]
    ev['m'] = m[ev['bin']]
    ev['a'] = a[ev['bin']]

    np.save(os.path.join(OUT, 'events.npy'), ev)
    np.save(os.path.join(OUT, 'bins_nz.npy'), nz)
    np.save(os.path.join(OUT, 'lor_nz.npy'), lors.reshape(-1, 2, 3)[nz])
    np.save(os.path.join(OUT, 'lors_all.npy'), lors)
    np.save(os.path.join(OUT, 'sino_y_m_a.npy'), np.stack([y, m, a]).astype(np.float32))  # to_array order, for the checks

    # check 1: re-histogram gives the prompts back exactly
    h = np.bincount(ev['bin'], minlength=y.size)
    rehist_ok = bool(np.array_equal(h, yi))
    meta = dict(dataset=os.path.basename(os.path.normpath(SRC)), seed=SEED, events=n_ev, nonzero_bins=int(nz.size),
                sinogram_bins=int(y.size), events_per_nonzero_bin=n_ev / nz.size, max_count=int(yi.max()),
                rehistogram_equals_prompts=rehist_ok,
                bytes_events=int(ev.nbytes), bytes_prompts_mult_additive_fp32=int(3 * 4 * y.size),
                lor_seconds=round(t_lor, 1), total_seconds=round(time.time() - t_start, 1),
                time_stamps='synthetic: uniform in [0,1), sorted (sinogram has no time order)',
                source_sha256={n: sha(os.path.join(SRC, n)) for n in ('prompts.s', 'mult_factors.s', 'additive_term.s')})
    json.dump(meta, open(os.path.join(OUT, 'meta.json'), 'w'), indent=1)
    print(json.dumps(meta, indent=1))
