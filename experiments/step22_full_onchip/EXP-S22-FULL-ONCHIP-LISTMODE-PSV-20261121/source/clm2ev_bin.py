"""Crystal-pair + TOF list-mode (.clm) -> events for the GPU list-mode psv and the FPGA preparation, with STIR's
LOR geometry: each event (crystal A, ring A, crystal B, ring B, unmashed TOF) is mapped by STIR's get_bin_for_det_pair rules
(as D:/PET/tools/clm_format.crystals_to_bins) to (segment, view, axial, tangential, mashed TOF k), and its LOR is the STIR
LOR of that bin (geometry table lors_all.npy, ordered per segment as (axial, view, tangential)). This is how STIR itself
reconstructs GE list-mode; the crystal-centre LORs of clm2ev.py differ from it by up to half a ring / crystal and do not
reach the PETRIC thresholds (RMSE ~0.09, reference made with the STIR bin model).
Output (<out dir>): events.npy (t, lor, tof = STIR k, m, a), lors_all.npy (copy of the geometry table), fov_mask.npy,
sensitivity_sign-1.npy, msum_lor.npy; check: (lor, k) histogram equal to the bin-derived events.
Usage (env pp, CPU only): python clm2ev_bin.py <out dir>"""
import json, os, shutil, sys
import numpy as np
sys.path.insert(0, 'D:/PET/tools')
import clm_format as C            # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
DS = 'GE_D690_NEMA_IQ2'
LM = f'D:/PET/data/list_mode/petric2/{DS}'
SN = f'D:/PET/data/sinogram/petric2/{DS}'
g = C.read_geometry(f'{SN}/prompts.hs')
w = np.fromfile(f'{LM}/{DS}.clm', '<u8')
tag = (w & C.TAG) != 0
ms = np.cumsum(tag) - 1
tms = np.where(tag, (w & np.uint64(0xFFFFFFFF)).astype(np.int64), 0)
tval = tms[np.flatnonzero(tag)]
evw = w[~tag]
t_ev = tval[ms[~tag]].astype(np.float64) * 1e-3
dA, rA, dB, rB, tof, prompt = C.unpack(evw)
dA, rA, dB, rB, tof = (np.asarray(v).astype(np.int64) for v in (dA, rA, dB, rB, tof))
assert prompt.all()

# ---- same steps as clm_format.crystals_to_bins, keeping the bin coordinates
N, V, T = g['num_det'], g['views'], g['tang']
tang = (dA - dB + 3 * N // 2) % N
view = (dA - (tang >> 1) + N) % N
in_first = view < V
big = tang >= V
t1 = np.where(in_first & big, N - tang, tang)
swap_local = in_first & big
view = np.where(in_first, view, view - V)
t2 = np.where(~in_first & big, tang - N, np.where(~in_first, -tang, t1))
swap_local |= (~in_first) & (~big)
tang = t2
keep = ~swap_local
r1, r2 = np.where(keep, rA, rB), np.where(keep, rB, rA)
k = np.rint(np.where(keep, tof, -tof) / g['tof_mash']).astype(np.int64)
R = g['num_rings']
seg = g['diff2seg'][r2 - r1 + R - 1]
assert (seg >= 0).all()
ax = (r1 + r2) - g['seg_minsum'][seg]
ti = tang + T // 2
flat = ((k - g['tof_min']) * g['bins_per_tof'] + g['seg_offset'][seg] + view * (g['nax'][seg] * T) + ax * T + ti)
assert np.array_equal(flat, C.crystals_to_bins(*(np.asarray(v) for v in C.unpack(evw)[:5]), g))
lor = g['seg_offset'][seg] + ax * (V * T) + view * T + ti          # lors_all order: per segment (axial, view, tangential)

mult = np.memmap(f'{SN}/mult_factors.s', '<f4', 'r')
add = np.memmap(f'{SN}/additive_term.s', '<f4', 'r')
ev = np.empty(evw.size, dtype=[('t', '<f8'), ('lor', '<u4'), ('tof', '<i2'), ('m', '<f4'), ('a', '<f4')])
ev['t'] = t_ev; ev['lor'] = lor.astype(np.uint32); ev['tof'] = k.astype(np.int16)
ev['m'] = mult[flat]; ev['a'] = add[flat]

# ---- check against the bin-derived events (same events as a histogram over (lor, k), same m / a per bin)
old = np.load(f'{LM}/events.npy')
key = lambda e: np.sort(e['lor'].astype(np.int64) * 64 + (e['tof'].astype(np.int64) + 32))
same = old.size == ev.size and np.array_equal(key(old), key(ev))
o = np.lexsort((old['tof'], old['lor'])); n = np.lexsort((ev['tof'], ev['lor']))
same_m = same and np.array_equal(old['m'][o], ev['m'][n]) and np.array_equal(old['a'][o], ev['a'][n])
print('events', ev.size, 'histogram equal to bin-derived events:', same, '; m / a equal:', same_m)
np.save(f'{OUT}/events.npy', ev)
for f in ('lors_all.npy', 'fov_mask.npy', 'sensitivity_sign-1.npy', 'msum_lor.npy'):
    if not os.path.exists(f'{OUT}/{f}'):
        shutil.copy(f'{LM}/{f}', f'{OUT}/{f}')
json.dump(dict(source=f'{LM}/{DS}.clm', events=int(ev.size), hist_equal_bin_events=bool(same), m_a_equal=bool(same_m),
               tof_k_range=[int(k.min()), int(k.max())]), open(f'{OUT}/clm2ev_bin.json', 'w'), indent=1)
