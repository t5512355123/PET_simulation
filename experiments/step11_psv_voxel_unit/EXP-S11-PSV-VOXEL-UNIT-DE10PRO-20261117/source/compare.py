"""compare board output with the emulator and convert the repeat timing to cycles per voxel.
usage: python3 compare.py <dir> <nz> <rep> <wall_ms> <f_mhz>"""
import sys
from array import array
d, nz, rep, wall, f = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
def load(n):
    a = array('f'); a.frombytes(open(d + '/' + n, 'rb').read()); return a
e, b = load('expect_out.bin'), load('board_out.bin')
n = nz * 163 * 163
mx = max(abs(e[2 * i]) for i in range(n))
err = max(abs(e[2 * i] - b[2 * i]) for i in range(n)) / mx
exact = sum(e[2 * i] == b[2 * i] for i in range(n))
print(f'voxels {n}: x_new max abs diff / max {err:.3e}, bit-identical {exact}/{n}')
cyc = wall * 1e-3 * f * 1e6 / (rep * n)
print(f'timing: {rep} passes in {wall:.0f} ms at {f} MHz -> {cyc:.3f} cycles per voxel, {n*rep/(wall*1e-3)/1e6:.1f} M voxels/s')
