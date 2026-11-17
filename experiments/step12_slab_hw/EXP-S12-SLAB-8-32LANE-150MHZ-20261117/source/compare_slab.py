"""Compare the slab projector board results with the software model, and turn the timing into samples/s.
Usage: python3 compare_slab.py <dir> <f_mhz> <rep_a> <wall_a_ms> <rep_b> <wall_b_ms>
samples = forward + back Joseph steps of real events (same definition as EXP-S4 compare_board.py)."""
import sys
from array import array

d, fmhz = sys.argv[1], float(sys.argv[2])
ra, wa, rb, wb = int(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5]), float(sys.argv[6])


def load(n):
    a = array('f')
    with open(f'{d}/{n}', 'rb') as f:
        a.frombytes(f.read())
    return a


meta = dict(l.split() for l in open(f'{d}/meta.txt'))
nev, real, lanes, mli = int(meta['nev']), int(meta['real_steps']), int(meta['lanes']), int(meta['max_lane_iters'])
es, bs = load('expect_s.bin'), load('board_s.bin')
ea, ba = load('expect_acc.bin'), load('board_acc.bin')
mx = max(abs(v) for v in ea)
err_s = max(abs(a - b) / max(abs(a), 1e-30) for a, b in zip(es, bs) if a != 0.0)
err_a = max(abs(a - b) for a, b in zip(ea, ba)) / mx
print(f'tokens {nev}, lanes {lanes}, real steps {real}, busiest lane {mli} iterations per pass')
print(f'forward ratio s: max rel diff {err_s:.3e}; bit-identical {sum(a == b for a, b in zip(es, bs))}/{len(es)}')
print(f'back projection: max abs diff / max {err_a:.3e}; bit-identical {sum(a == b for a, b in zip(ea, ba))}/{len(ea)}')
# marginal time per forward+back pass from two repeat counts (removes JTAG start/poll overhead)
t_pass = (wb - wa) * 1e-3 / (rb - ra)
cyc = t_pass * fmhz * 1e6
sps = 2 * real / t_pass
print(f'timing: {t_pass * 1e3:.3f} ms per forward+back pass at {fmhz} MHz = {cyc:.0f} cycles '
      f'(busiest lane 2 x {mli} = {2 * mli} iterations -> {cyc / (2 * mli):.3f} cycles/iteration)')
print(f'throughput: {sps / 1e6:.1f} M samples/s ({sps / lanes / (fmhz * 1e6):.3f} samples per lane per cycle)')
