"""Compare on-board results with the HLS emulation and turn the repeat timing into cycles per sample.
Usage: python3 compare_board.py <dir> <rep> <wall_ms> <f_mhz>"""
import sys
from array import array

d, rep, wall_ms, fmhz = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])


def load(n):
    a = array('f')
    with open(f'{d}/{n}', 'rb') as f:
        a.frombytes(f.read())
    return a


meta = dict(l.split() for l in open(f'{d}/meta.txt'))
nev, steps = int(meta['nev']), int(meta['steps'])
es, bs = load('expect_s.bin'), load('board_s.bin')
ea, ba = load('expect_acc.bin'), load('board_acc.bin')
mx = max(abs(v) for v in ea)
err_s = max(abs(a - b) / max(abs(a), 1e-30) for a, b in zip(es, bs))
err_a = max(abs(a - b) for a, b in zip(ea, ba)) / mx
exact_s = sum(a == b for a, b in zip(es, bs))
exact_a = sum(a == b for a, b in zip(ea, ba))
print(f'events {nev}, Joseph steps {steps}')
print(f'forward ratio s: max rel diff {err_s:.3e}, bit-identical {exact_s}/{len(es)}')
print(f'back projection: max abs diff / max {err_a:.3e}, bit-identical {exact_a}/{len(ea)}')
try:
    ra = load('board_acc_rep.bin')
    err_r = max(abs(r - rep * a) for a, r in zip(ea, ra)) / (rep * mx)
    print(f'repeat run ({rep}x): max |acc - rep*expected| / (rep*max) = {err_r:.3e}')
except FileNotFoundError:
    pass
cycles = wall_ms * 1e-3 * fmhz * 1e6
samples = 2 * steps * rep  # forward + back
print(f'timing: {rep} batches in {wall_ms:.0f} ms at {fmhz} MHz -> {cycles / samples:.3f} cycles per sample (fwd+back), '
      f'{samples / (wall_ms * 1e-3) / 1e6:.1f} M samples/s, {cycles / (rep * nev):.1f} cycles per event (2 passes)')
