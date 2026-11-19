"""Convert a PETRIC2 TOF prompts sinogram (GE DMI 4 rings) into list-mode events (EXP-S16).

Real list-mode (e.g. the GE DMI NEMA IQ list-mode on Zenodo 8404015) stores per event the crystal pair, the TOF bin and
per-event correction values (sensitivity, attenuation, additive randoms + scatter). PETRIC2 only gives the sinogram,
so each sinogram bin with y counts becomes y events (exact: re-histogramming gives the prompts back), with synthetic
time stamps (uniform over the frame, sorted: a homogeneous Poisson process, exact for a static scan).

Per event: t (float64, 0..1), lor (uint32, index into lors_all), tof (int16, STIR TOF position -14..14),
           m (float32 multiplicative factor of that TOF bin), a (float32 additive term of that TOF bin)
           -> model yhat = m * (c * A_tof x + a), as SIRF / EXP-S6.
lors_all.npy: float32 (N_lor, 2, 3) LOR end points (z, y, x) mm (STIR get_LOR, intersections with a 1 m cylinder),
              LOR order: segment (file order), axial, view, tangential.
Usage (env stir): python -I sino2lm_tof.py <dataset_dir> <out_dir> [nproc] [seed]"""
import hashlib
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

SRC, OUT = sys.argv[1], sys.argv[2]
NP = int(sys.argv[3]) if len(sys.argv) > 3 else 8
SEED = int(sys.argv[4]) if len(sys.argv) > 4 else 20261119
HS = os.path.join(SRC, 'prompts.hs')


def lor_work(args):
    seg, v0, v1 = args
    import stir
    pd = stir.ProjData.read_from_file(HS)
    pdi = pd.get_proj_data_info()
    lor = stir.LORInAxialAndNoArcCorrSinogramCoordinates()
    pts = stir.LORAs2Points()
    a0, a1 = pd.get_min_axial_pos_num(seg), pd.get_max_axial_pos_num(seg)
    t0, t1 = pd.get_min_tangential_pos_num(), pd.get_max_tangential_pos_num()
    out = np.empty((a1 - a0 + 1, v1 - v0, t1 - t0 + 1, 2, 3), np.float32)
    for ia, ax in enumerate(range(a0, a1 + 1)):
        for iv, v in enumerate(range(v0, v1)):
            for it, tg in enumerate(range(t0, t1 + 1)):
                b = stir.Bin(seg, v, ax, tg, 0)
                pdi.get_LOR(lor, b)
                lor.get_intersections_with_cylinder(pts, 1000.0)
                p1, p2 = pts.p1(), pts.p2()
                out[ia, iv, it, 0] = (p1.z(), p1.y(), p1.x())
                out[ia, iv, it, 1] = (p2.z(), p2.y(), p2.x())
    return seg, v0, out


def read_seg(path, seg, tof):
    """(axial, view, tangential) numpy array of one segment and TOF position, through STIR (no layout guessing)"""
    import stir
    pd = stir.ProjData.read_from_file(path)
    s = pd.get_segment_by_sinogram(seg, tof)
    import stirextra
    return stirextra.to_numpy(s).astype(np.float32)


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 24), b''):
            h.update(blk)
    return h.hexdigest()


if __name__ == '__main__':
    import stir
    import stirextra  # noqa: F401
    os.makedirs(OUT, exist_ok=True)
    t_start = time.time()
    pd = stir.ProjData.read_from_file(HS)
    segs = list(range(pd.get_min_segment_num(), pd.get_max_segment_num() + 1))
    tofs = list(range(pd.get_min_tof_pos_num(), pd.get_max_tof_pos_num() + 1))
    V = pd.get_num_views()
    T = pd.get_max_tangential_pos_num() - pd.get_min_tangential_pos_num() + 1
    nax = {s: pd.get_max_axial_pos_num(s) - pd.get_min_axial_pos_num(s) + 1 for s in segs}
    off, n = {}, 0
    for s in segs:
        off[s] = n
        n += nax[s] * V * T
    NLOR = n
    print(f'segments {segs}, TOF {tofs[0]}..{tofs[-1]}, views {V}, tangential {T}, axial {nax}, LORs {NLOR}', flush=True)
    # ---- LOR end points (STIR geometry), parallel over (segment, view block)
    jobs = [(s, v, min(V, v + 17)) for s in segs for v in range(0, V, 17)]
    lors = np.empty((NLOR, 2, 3), np.float32)
    with Pool(NP) as p:
        for s, v0, o in p.imap_unordered(lor_work, jobs):
            a = o.shape[0]
            full = lors[off[s]:off[s] + nax[s] * V * T].reshape(nax[s], V, T, 2, 3)
            full[:, v0:v0 + o.shape[1]] = o
    t_lor = time.time() - t_start
    np.save(os.path.join(OUT, 'lors_all.npy'), lors)
    print(f'LORs done in {t_lor:.1f} s', flush=True)
    # ---- events
    rng = np.random.default_rng(SEED)
    parts = []
    msum = np.zeros(NLOR, np.float64)        # sum over TOF of m (for the sensitivity image check)
    total = 0
    for s in segs:
        for k in tofs:
            y = read_seg(os.path.join(SRC, 'prompts.hs'), s, k)
            m = read_seg(os.path.join(SRC, 'mult_factors.hs'), s, k)
            a = read_seg(os.path.join(SRC, 'additive_term.hs'), s, k)
            assert y.shape == (nax[s], V, T), (y.shape, nax[s], V, T)
            msum[off[s]:off[s] + y.size] += m.ravel()
            yc = np.rint(y).astype(np.int64)
            assert np.all(np.abs(y - yc) < 1e-3) and yc.min() >= 0
            nzi = np.nonzero(yc.ravel())[0]
            cnt = yc.ravel()[nzi]
            idx = np.repeat(nzi, cnt)
            e = np.empty(idx.size, dtype=[('t', '<f8'), ('lor', '<u4'), ('tof', '<i2'), ('m', '<f4'), ('a', '<f4')])
            e['lor'] = off[s] + idx
            e['tof'] = k
            e['m'] = m.ravel()[idx]
            e['a'] = a.ravel()[idx]
            parts.append(e)
            total += int(cnt.sum())
    ev = np.concatenate(parts)
    ev['t'] = rng.random(ev.size)
    ev = ev[np.argsort(ev['t'], kind='stable')]
    np.save(os.path.join(OUT, 'events.npy'), ev)
    np.save(os.path.join(OUT, 'msum_lor.npy'), msum.astype(np.float32))
    # ---- check: re-histogram the events and compare with the prompts sinogram
    ok = True
    for s in segs:
        for k in tofs:
            y = np.rint(read_seg(os.path.join(SRC, 'prompts.hs'), s, k)).astype(np.int64).ravel()
            sel = (ev['tof'] == k) & (ev['lor'] >= off[s]) & (ev['lor'] < off[s] + y.size)
            h = np.bincount(ev['lor'][sel] - off[s], minlength=y.size)
            ok &= bool(np.array_equal(h, y))
    meta = dict(dataset=os.path.basename(SRC.rstrip('/\\')), seed=SEED, events=int(ev.size), lors=NLOR, segments=segs,
                tof_positions=[tofs[0], tofs[-1]], views=V, tangential=T, axial=nax, lor_seconds=round(t_lor, 1),
                total_seconds=round(time.time() - t_start, 1), rehistogram_equals_prompts=ok,
                time_stamps='synthetic: uniform in [0,1), sorted (sinogram has no time order)',
                source_sha256={f: sha(os.path.join(SRC, f)) for f in ('prompts.s', 'mult_factors.s', 'additive_term.s')})
    json.dump(meta, open(os.path.join(OUT, 'meta.json'), 'w'), indent=1)
    print(json.dumps({k: v for k, v in meta.items() if k != 'source_sha256'}, indent=1))
