"""EXP-S17: board vs software model (s, read-back accumulators), and the timing.
Usage: python3 compare7.py <hw7 dir> <f_MHz> <rep>"""
import re, sys
import numpy as np
hw, F, REP = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
meta = dict(l.split() for l in open(f'{hw}/meta.txt'))
nev = int(meta['nev'])
bs, es = np.fromfile(f'{hw}/board_s.bin', '<f4')[:nev], np.fromfile(f'{hw}/expect_s.bin', '<f4')
nz = es != 0
print(f'forward ratio s: max rel diff {np.max(np.abs(bs[nz] - es[nz]) / np.abs(es[nz])):.3e}; bit-identical {np.sum(bs == es)}/{nev}')
br, er = np.fromfile(f'{hw}/board_read.bin', '<f4'), np.fromfile(f'{hw}/expect_read.bin', '<f4')
print(f'back projection (both copies, {er.size} voxels): max abs diff / max {np.abs(br - er).max() / np.abs(er).max():.3e}; '
      f'bit-identical {np.sum(br == er)}/{er.size}')
log = open(f'{hw}/board7.log').read()
for name, n, a, b in re.findall(r'TIMING (\w+) tokens (\d+) rep1 (\d+) ms rep\d+ (\d+) ms', log):
    t = (int(b) - int(a)) * 1e-3 / (REP - 1)
    print(f'{name}: {t * 1e3:.4f} ms per pass = {t * F * 1e6:.0f} cycles for {n} tokens -> {t * F * 1e6 / int(n):.3f} cycles/token '
          f'(busiest lane items {meta["max_lane_items"]})')
