"""EXP-S19 full on-chip run of list-mode psv (GE_D690_NEMA_IQ2) on the DE10-Pro: DDR images (4 channels) and the
sequencer program for the 40 updates of the GPU run (same schedule: M = 8, full gradient at updates 0, 16, 32,
preconditioner at 4 and 8, subset order from RandomState(1), step 3.5 / (1 + 0.01 u)).
Setup (excluded from the timed run, as the GPU's setup): lane tables, DDR images, P0 = preconditioner of x0 (GPU,
hardware formats), lanes loaded through the voxel unit (mode 4).
Usage (env pp): python prog10.py <csr10.json> <out dir>
Outputs in <out dir>: ch{1..4}_*.bin (file, byte address) list in ddr.txt, prog.bin (sequencer: updates 0..39 from
pc 0, timed; updates 40..49 from pc = prog_split, untimed, for the 10-in-a-row check), run10.json."""
import json, os, sys
import numpy as np
import cupy as cp
import cupyx.scipy.ndimage as cnd
LMP = 'C:/Users/t5512/AppData/Local/Temp/claude/9d475279f3617f93/5142366d-c9a0-40dd-a9b5-3424c81b8845/scratchpad/lmpsv'
sys.path.insert(0, LMP)
os.environ['DS'] = 'GE_D690_NEMA_IQ2'
import tofcore                         # noqa: E402

CSR = json.load(open(sys.argv[1]))
OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)
DS = 'GE_D690_NEMA_IQ2'
W = os.environ.get('PREPW', f'D:/PET/claude_house/work/r2_fpga/{DS}')      # prep_full + sched_full outputs
LMD = os.environ.get('LMSRC', f'D:/PET/data/list_mode/petric2/{DS}')     # events dir (fov_mask); LMDIR for tofcore
NZ, NP, L, NT = 47, 201, 40, 5
NSL = NZ * 40000
ND = NSL // L
RS, PSZ, RBW = 208, 201 * 208, 51
M, UPD = 8, 50                     # 50 updates (x_1 .. x_50: the 10-in-a-row check after the first pass)
UPD_T = int(os.environ.get('UPD_T', '40'))   # timed updates 0 .. UPD_T - 1 (= first pass update of the GPU run in the same formats)


def q16(a):
    u = np.asarray(a, np.float32).view(np.uint32)
    return ((u + np.uint32(0x7fff) + ((u >> 16) & np.uint32(1))) >> 16).astype(np.uint16)


def bf(a):
    return (q16(a).astype(np.uint32) << 16).view(np.float32)


# ---------------- slot order and raster helpers
n = np.arange(NSL)
si = n % L; sk = (n // L) % L; sT = (n // (L * L)) % (NT * NT); sz = n // (L * L * NT * NT)
sy = L * (sT // NT) + si; sx = L * (sT % NT) + (si + sk) % L
def to_slot(v): return np.ascontiguousarray(v[sz, sy, sx]).astype(np.float32)
def to_raster(v, full=False):
    r = np.zeros((NZ, 201, RS), np.float32)
    if full: r[:, :, :201] = v
    else: r[:, :200, :200] = v[:, :200, :200]
    return r
def boundary_words(v):
    b = np.zeros((NZ, RBW * 16), np.float32)
    q = np.arange(402)
    yy = np.where(q <= 200, 200, np.where(q <= 400, q - 201, 200)); xx = np.where(q <= 200, q, 200)
    b[:, 2 * q] = v[:, yy, xx]
    return b
def pad16(a):
    a = np.asarray(a); r = (-a.size) % 16
    return np.concatenate([a.ravel(), np.zeros(r, a.dtype)]) if r else a.ravel()


# ---------------- problem data (same objects as the GPU run)
P = tofcore.TOFProblem()
P.kappa = cp.asarray(bf(P.kappa.get()))                 # kappa bf16 (GPU-checked)
x0 = np.load(f'{W}/x0.npy').astype(np.float32)
fov = (np.load(f'{LMD}/fov_mask.npy') > 0)
sens = P.sens.get().astype(np.float32)                   # s_all (whole list)
# P0 = preconditioner of x0 in the hardware formats (run_tof_hw8g2: Gaussian of bf16 x with bf16 intermediates)
sig = [5.0 / (2 * np.sqrt(2 * np.log(2))) / v for v in P.vs]
xg = cp.asarray(bf(x0))
t = cp.asarray(bf(cnd.gaussian_filter1d(xg, sig[2], axis=2, mode='constant').get()))
t = cp.asarray(bf(cnd.gaussian_filter1d(t, sig[1], axis=1, mode='constant').get()))
xs = cnd.gaussian_filter1d(t, sig[0], axis=0, mode='constant')
H = P.prior_diag_hess(xs)
P0 = bf((P.fov * cp.asarray(x0) / (cp.asarray(sens) + 2.0 * H * cp.asarray(x0))).get())
# Gaussian / RDP constants
def kern(s):
    R = int(4 * s + 0.5); w = np.exp(-0.5 * (np.arange(-R, R + 1) / s) ** 2); w /= w.sum(); return w[R:]
gxy, gz = kern(sig[2]), kern(sig[0])
assert gxy.size == 5 and gz.size == 4
vz, vx = float(P.vs[0]), float(P.vs[2])
def rw(dz, nxy): return P.beta * vx / np.sqrt(dz * dz * vz * vz + nxy * vx * vx)
RDPW = [rw(0, 1), rw(0, 2), rw(1, 0), rw(1, 1), rw(1, 2)]

# ---------------- tokens (schedule from sched_full.cpp)
sub = np.loadtxt(f'{W}/subsets.txt', dtype=np.int64)
TOK = int(sub[:, 2].sum())
evw = np.fromfile(f'{W}/tok_evw.bin', np.uint8).reshape(-1, 32)
ta = np.fromfile(f'{W}/tok_a.bin', '<f4')
rec = np.fromfile(f'{W}/tok_rec.bin', '<i4')
assert evw.shape[0] == TOK
nw = (TOK + 1) // 2; nw += nw & 1
words = np.zeros((nw, 64), np.uint8)
words.reshape(-1)[:TOK * 32] = evw.reshape(-1)
E1, E2 = words[0::2], words[1::2]
nev_k = [int((rec[s0:s0 + c] >= 0).sum()) for s0, c in zip(sub[:, 1], sub[:, 2])]

# ---------------- DDR layout (byte addresses per channel)
MB8 = 0x800000
A_ = dict(E1=(1, 0x00000000), X=(1, 0x10000000),                     # X archive: x_u at X + u * 8 MB
          E2=(2, 0x00000000), P=(2, 0x10000000), PFOV=(2, 0x10400000),
          T=(2, 0x12000000),                                         # T_k at T + k * 4 MB
          # EXP-S22: GS moved from 0x01000000 (overlapped SENS 0x00C00000 + 7.52 MB)
          A=(3, 0x00000000), SENS=(3, 0x00C00000), GS=(3, 0x01400000), XR=(3, 0x02000000), KR=(3, 0x03000000),
          MB=(3, 0x03800000), XS=(3, 0x04000000),
          S=(4, 0x00000000), GP=(4, 0x01000000), H=(4, 0x02000000))
files = []
def put(name, arr, ch, addr):
    fn = f'ch{ch}_{name}.bin'
    a = np.ascontiguousarray(arr)
    b = a.tobytes(); r = (-len(b)) % 64
    open(os.path.join(OUT, fn), 'wb').write(b + bytes(r))
    files.append((fn, ch, addr))
put('E1', E1, *A_['E1']); put('E2', E2, *A_['E2'])
put('A', pad16(ta.astype(np.float32)), *A_['A'])
put('X0', to_slot(x0), A_['X'][0], A_['X'][1])
put('P0', q16(to_slot(P0)), *A_['P'])
put('PFOV', q16(to_slot(fov.astype(np.float32))), *A_['PFOV'])
put('SENS', to_slot(sens), *A_['SENS'])
put('XR0', to_raster(x0), *A_['XR'])
kr = np.zeros((NZ, 201, RS), np.uint16); kr[:, :, :201] = q16(P.kappa.get())
put('KR', kr, *A_['KR'])
put('MB', boundary_words(x0), *A_['MB'])
# EXP-S22: no two DDR regions (loaded images and kernel outputs) may overlap
_reg = [(ch, ad, os.path.getsize(os.path.join(OUT, fn)), fn) for fn, ch, ad in files]
_reg += [(*A_['GS'], NSL * 4, 'GS'), (*A_['GP'], NSL * 4, 'GP'), (*A_['H'], NSL * 4, 'H'), (*A_['S'], (TOK + 16) * 4, 'S'),
         (*A_['XS'], NZ * PSZ * 4, 'XS'), (A_['T'][0], A_['T'][1], 8 * 0x400000, 'T'), (A_['X'][0], A_['X'][1] + MB8, (UPD + 1) * MB8, 'X1..')]
for i, (c1, a1, n1, f1) in enumerate(_reg):
    for c2, a2, n2, f2 in _reg[i + 1:]:
        assert c1 != c2 or a1 + n1 <= a2 or a2 + n2 <= a1, f'DDR overlap {f1} / {f2}'

# ---------------- sequencer program
C = CSR      # {component: {'base': int, 'args': {name: offset}}}
prog = []
last_w = {}
def W32(addr, val, force=False):
    v = int(val) & 0xffffffff
    if not force and last_w.get(addr) == v:       # CSR arguments keep their values between kernel runs
        return
    last_w[addr] = v
    prog.append((1, addr, v))
def wr(comp, arg, val):
    W32(C[comp]['base'] + C[comp]['args'][arg], val)
def wr64(comp, arg, val):
    o = C[comp]['base'] + C[comp]['args'][arg]; W32(o, val & 0xffffffff); W32(o + 4, val >> 32)
def wrf(comp, arg, f): wr(comp, arg, int(np.float32(f).view(np.uint32)))
def start(comp): W32(C[comp]['base'] + 0x08, 1, force=True)
def wait(comp): prog.append((2, C[comp]['base'] + 0x18, 2))
def mark(i): prog.append((3, 0, i))
def src_ptrs():
    wr64('src', 'me1', A_['E1'][1]); wr64('src', 'me2', A_['E2'][1]); wr64('src', 'ma', A_['A'][1]); wr64('src', 'ms', A_['S'][1])
def run_src(mode, nev, off, nm, nq, raw, rep=1):
    wr64('sink', 'mss', A_['S'][1]); wr('sink', 'nm', nm); wr('sink', 'nq', nq); wr('sink', 'raw', raw); start('sink')
    src_ptrs(); wr('src', 'mode', mode); wr('src', 'nev', nev); wr('src', 'off', off); wr('src', 'cnt', 0); wr('src', 'rep', rep)
    wr('src', 'finit', 0); start('src'); wait('sink'); wait('src')
def vox(mode, xu, xn, t_k, step, mg='GS', mp='P', mtw='T', mgp='GP', tk_w=None):
    wr64('vox', 'mx', xu); wr64('vox', 'mxn', xn); wr64('vox', 'mp', A_[mp][1]); wr64('vox', 'mt', t_k)
    wr64('vox', 'mtw', tk_w if tk_w is not None else t_k); wr64('vox', 'mg', A_[mg][1]); wr64('vox', 'mgw', A_['GS'][1])
    wr64('vox', 'mgp', A_[mgp][1]); wr64('vox', 'mxr', A_['XR'][1])
    wr('vox', 'mode', mode); wr('vox', 'nd', ND); wr('vox', 'rep', 1); wrf('vox', 'step', step); wrf('vox', 'mf', float(M))
    wrf('vox', 'invm', 1.0 / M)
    if mode != 5:
        wr('sink', 'nm', 4); wr('sink', 'nq', 0); wr('sink', 'raw', 0); start('sink')
    start('vox')
    if mode != 5:
        wr('src', 'mode', 11); wr('src', 'rep', 1); start('src')
    wait('vox')
    if mode != 5:
        wait('sink'); wait('src')
def rdp_start(mode, xin, braster, out):
    wr64('rdp', 'xin', xin); wr64('rdp', 'kin', A_['KR'][1]); wr64('rdp', 'mb', A_['MB'][1]); wr64('rdp', 'mo', out)
    wr('rdp', 'mode', mode); wr('rdp', 'braster', braster); wr('rdp', 'nz', NZ); wrf('rdp', 'eps2', P.eps)
    for i, w in enumerate(RDPW): wrf('rdp', f'w{i + 1}', w)
    start('rdp')
def gs_start():
    wr64('gs', 'xin', A_['XR'][1]); wr64('gs', 'mb', A_['MB'][1]); wr64('gs', 'mo', A_['XS'][1]); wr('gs', 'nz', NZ)
    for i in range(5): wrf('gs', f'gx{i}', gxy[i]); wrf('gs', f'gy{i}', gxy[i])
    for i in range(4): wrf('gs', f'gz{i}', gz[i])
    start('gs')
Xa = lambda u: A_['X'][1] + u * MB8
Ta = lambda k: A_['T'][1] + k * 0x400000
rng = np.random.RandomState(1)
order = []
sched = []
split = None
for u in range(UPD):
    if u == UPD_T:
        mark(UPD_T); prog.append((0, 0, 0)); split = len(prog)
    epoch = u // M
    full = (u % M == 0) and (epoch % 2 == 0)
    step = 3.5 / (1 + 0.01 * u)
    pre = (epoch == 1 and u % M == 0) or u == 4
    mark(u)
    rdp_start(0, A_['XR'][1], 0, A_['GP'][1])
    if pre: gs_start()
    if full:
        run_src(12, TOK, 0, TOK, sum(nev_k), 3)
        for k in range(M):
            run_src(10, 0, 0, 1, 0, 0)
            run_src(13, int(sub[k, 2]), int(sub[k, 1]), int(sub[k, 2]), 0, 0)
            if k == 0:
                wait('rdp')
            vox(2 if k == 0 else 3, Xa(u), Xa(u), Ta(k), 0.0, mg='SENS' if k == 0 else 'GS', tk_w=Ta(k))
        if pre:
            raise SystemExit('preconditioner on a full update not expected')
        vox(1, Xa(u), Xa(u + 1), Ta(0), step)
        sched.append(dict(u=u, full=True, step=step))
    else:
        if not order:
            o = np.arange(M); rng.shuffle(o); order = o.tolist()
        k = order.pop()
        run_src(12, int(sub[k, 2]), int(sub[k, 1]), int(sub[k, 2]), nev_k[k], 3)
        run_src(10, 0, 0, 1, 0, 0)
        run_src(13, int(sub[k, 2]), int(sub[k, 1]), int(sub[k, 2]), 0, 0)
        wait('rdp')
        if pre:
            wait('gs')
            rdp_start(1, A_['XS'][1], 1, A_['H'][1]); wait('rdp')
            vox(5, Xa(u), Xa(u), A_['PFOV'][1], 0.0, mg='SENS', mgp='H', tk_w=A_['P'][1])
        vox(0, Xa(u), Xa(u + 1), Ta(k), step)
        sched.append(dict(u=u, full=False, subset=k, pre=pre, step=step))
mark(UPD)
prog.append((0, 0, 0))
assert split is not None
pa = np.zeros((len(prog), 4), np.uint32)
for i, (op, ad, v) in enumerate(prog): pa[i] = (op, ad, v, 0)
pa.tofile(os.path.join(OUT, 'prog.bin'))
with open(os.path.join(OUT, 'ddr.txt'), 'w') as f:
    for fn, ch, ad in files: f.write(f'{fn} {ch} {ad}\n')
info = dict(updates=UPD, timed_updates=UPD_T, prog_split=split, tokens=TOK, nev_k=nev_k, prog_len=len(prog), schedule=sched, ddr=A_, rdp_w=RDPW,
            gxy=gxy.tolist(), gz=gz.tolist(), eps=P.eps, beta=P.beta, x_archive=[Xa(u) for u in range(UPD + 1)])
json.dump(info, open(os.path.join(OUT, 'run10.json'), 'w'), indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))
print('program', len(prog), 'commands; files', len(files))
