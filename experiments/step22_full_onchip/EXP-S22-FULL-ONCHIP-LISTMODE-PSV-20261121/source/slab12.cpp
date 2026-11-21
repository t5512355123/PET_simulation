// EXP-S17 R2 lane: TOF list-mode Joseph projector, both main-axis copies resident on chip (FOV rows only),
// planes interleaved over lanes (plane p -> lane p % LANES, local index t = p / LANES), SETS = 4 bank sets per lane
// (set = t % SETS) so up to 4 consecutive local steps of one event run in one cycle.
// One fp32 word per voxel and copy: the image during the forward pass, the accumulator during the back pass
// (K_CLEAR in between; the voxel update writes the new image).
//   chain 1 (Tok): src -> LANES x (exp -> eng) -> sink ; chain 2 (PTok): src -> LANES x padd -> sink
// Plane table per lane (K_SETUP tokens): for (copy, t): base address in the set memory, first row (u / 2), rows;
// voxel (u, z) of plane (copy, t) -> address base + (u/2 - ulo) * HZ + z/2, bank (u & 1) | (z & 1) << 1.
// TOF weight: table over |d| in [0, 5 sigma) (TOFN entries + next value, linear interpolation), d = d0 + k * dd (mm).
// Single-voxel tokens (K_LOAD / K_READ): du = lane, dv = t, u0 = u, v0 = z, na bit 15 = copy (no division in hardware).
#ifndef SWSIM
#include "HLS/hls.h"
#include "HLS/math.h"
#include "HLS/lsu.h"
#endif
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vector>
#include <deque>
#include <algorithm>

#define NPL 201
#define NU 201
#define NZ 47
#define HZ ((NZ + 1) / 2)
#ifndef LANES
#define LANES 40
#endif
#define SETS 4
#define TMAX ((NPL + LANES - 1) / LANES)
#ifndef DEPTH
#define DEPTH 5120
#endif
#define FRAC 20
#define TOFN 1024
#define TOFHALF 175.0478f                    // 5 sigma (mm), D690: sigma = 0.5 * 550 ps * c / 2.3548
#ifndef MAXEV
#define MAXEV 2048
#endif
#ifndef TOKBUF
#define TOKBUF 256
#endif
#ifndef IOCHUNK
#define IOCHUNK 16384
#endif
#ifndef RAWMAX
#define RAWMAX 4096
#endif

enum { K_FWD = 0, K_BACK = 1, K_LOAD = 2, K_READ = 3, K_SETID = 4, K_NOP = 5, K_SETUP = 6, K_CLEAR = 7, K_TOFTAB = 8, K_SWEEP = 9 };
// voxel sweep: slots n = ((z * 25 + ty * 5 + tx) * 40 + k) * 40 + i, voxel (z, y = 40 ty + i, x = 40 tx + (i + k) % 40);
// lane l per diagonal (z, ty, tx, k): item h = 0 copy 1 (plane y = 40 ty + l, voxel i = l),
//                                     item h = 1 copy 0 (plane x = 40 tx + l, voxel i = (l - k) % 40).
// item j reads (ACC -> vout) for j < NSW and writes (vin -> MEM) the voxel of item j - SLAG for j >= SLAG.
#define NTILE 5
#define RS 208
#define PS (201 * RS)
#define RB_WORDS 51
#define SWCH 24000
#define NSWTOK ((NSW + SLAG + SWCH - 1) / SWCH)
#define NSW (2 * NZ * NTILE * NTILE * LANES)
#ifndef SLAG
#define SLAG 16
#endif

struct Ev {               // 48 B host format (i0 == -1000: NOP for lane u0, n = bubbles)
  short i0, na;
  int u0, v0, du, dv;
  float d0, dd;
  float mw, y, a;
  short p0, t0;           // lane 0 annotation: first plane >= i0 with p % LANES == 0, and p / LANES
  short c0, g0;           // lane 0: local steps, items (ceil(c0 / SETS))
};
struct Tok {              // chain 1
  short i0, na;
  int u0, v0, du, dv;
  int d0, dd;             // EXP-S21: events -> TOF distance d in fixed point (dfix); SETUP -> ulo, nrow; TOFTAB -> float bits
  float s;
  unsigned char kind;
  short pl, tl;           // annotation for the receiving lane: first plane, its local index
  short cl, gl;           // local steps and items in the receiving lane
};
struct PTok { float F, mw, y, a; int idx; };
struct Step { int u, v; int d; short t; short ok; };
#define F_TOK 1
#define F_SF 2
#define F_SB 4
#define F_LAST 8
#define F_EMIT0 16
#define F_CLR 32
#define F_SRD 64
#define F_SWR 128
struct Item {
  Tok t;                  // token (forwarded with the next lane's annotation)
  short jb;               // item index within the token (steps jb*SETS .. jb*SETS+SETS-1 of this lane; CLEAR address)
  short pl, tl, cl;       // this lane's first plane, its local index, local steps
  unsigned char fl;
  unsigned char rc, rt, rz, wc, wt, wz;   // sweep read / write voxel: copy, local plane, z
  short ru, wu;                           // u
  float wv;                               // sweep write value (read from vin by exp: keeps eng one cluster)
};


struct D512 { float v[16]; };
struct D512U { unsigned v[16]; };
struct EvW { short i0, na; int u0, v0, du, dv; float d0, dd, mw; };   // 32 B DDR event (i0 == -1000: NOP)
struct D512E { EvW e[2]; };
union FU { float f; unsigned u; };
static inline float bf2f(unsigned h) { FU x; x.u = h << 16; return x.f; }
static inline unsigned f2bf(float f) { FU x; x.f = f; return (x.u + 0x7fffu + ((x.u >> 16) & 1u)) >> 16; }
// EXP-S21: the lanes get the TOF distance d in fixed point (units of TOF table steps, DFRAC fraction bits), converted once
// in src: no float <-> int converters in the 40 lanes (fit failed at 110 % ALM with 23 converters per lane).
#define DFRAC 16
#define DSCL ((float)TOFN / TOFHALF * (float)(1 << DFRAC))
static inline int dfix(float d) { float x = d * DSCL; return (int)(x >= 0.0f ? x + 0.5f : x - 0.5f); }
static inline int f2i_bits(float f) { FU x; x.f = f; return (int)x.u; }
static inline float i2f_bits(int i) { FU x; x.u = (unsigned)i; return x.f; }
#include "vox8.inc"

static inline short local_cnt(short p, short i0, short n) {   // steps of an event on planes p, p + LANES, ...
  int k = p - i0;
  if (k >= n || p >= NPL || k < 0) return 0;
  int a = (n - 1 - k) / LANES + 1, b = (NPL - 1 - p) / LANES + 1;
  return (short)(a < b ? a : b);
}
static inline void annot_next(Tok &t, short pl, short tl) {
  short pn = pl + 1, tn = tl;
  if (pn - LANES >= t.i0) { pn = pn - LANES; tn = tl - 1; }
  t.pl = pn; t.tl = tn;
  short c = local_cnt(pn, t.i0, t.na & 0x7fff);
  t.cl = c; t.gl = (short)((c + SETS - 1) / SETS);
}
static inline Tok evw2tok(const EvW &e, int ph, float s) {
  Tok t;
  t.i0 = e.i0; t.na = e.na; t.u0 = e.u0; t.v0 = e.v0; t.du = e.du; t.dv = e.dv; t.d0 = dfix(e.d0); t.dd = dfix(e.dd); t.s = s;
  bool nop = e.i0 == -1000;
  t.kind = nop ? K_NOP : (ph ? K_BACK : K_FWD);
  int i0 = nop ? 0 : e.i0;
  int t0 = (i0 + LANES - 1) / LANES;
  short p0 = (short)(t0 * LANES);
  short c0 = local_cnt(p0, (short)i0, (short)(e.na & 0x7fff));
  t.pl = p0; t.tl = (short)t0; t.cl = nop ? 0 : c0; t.gl = nop ? 0 : (short)((c0 + SETS - 1) / SETS);
  return t;
}

// ---------------------------------------------------------------- exp (state: c, jb, more, id)
// exp state: c (current token), jb (item index within the token), rem (items left after this one), id
// items per token: events -> gl (from the annotation), CLEAR -> DEPTH, own NOP -> n, other tokens -> 1
// exp state: c (current token), jb (item index within the token), rem (items left after this one), id
// items per token: events -> gl (from the annotation), CLEAR -> DEPTH, own NOP -> n, other tokens -> 1.
// exp only counts; the engine computes the steps (k, u, v, d) of the item from (token, jb, this lane's pl / tl / cl).
#define SWADV(h, k, tx, ty, z)                                                                                \
  {                                                                                                          \
    bool kw = h == 1 && k == LANES - 1, xw = kw && tx == NTILE - 1, yw = xw && ty == NTILE - 1;              \
    z = yw ? z + 1 : z; ty = xw ? (yw ? 0 : ty + 1) : ty; tx = kw ? (xw ? 0 : tx + 1) : tx;                  \
    k = h == 1 ? (kw ? 0 : k + 1) : k; h = h ^ 1;                                                            \
  }
#define EXP_BODY                                                                                             \
  {                                                                                                          \
    bool tokit = rem == 0;                                                                                   \
    Tok t;                                                                                                   \
    if (tokit) t = in.read(); else t = c;                                                                    \
    int kind = t.kind;                                                                                       \
    bool isev = kind == K_FWD || kind == K_BACK;                                                             \
    bool isclr = kind == K_CLEAR;                                                                            \
    bool isnop = kind == K_NOP && t.u0 == id;                                                                \
    bool isswp = kind == K_SWEEP;                                                                            \
    int ng = (isev || isswp) ? (int)t.gl : (isclr ? DEPTH : (isnop ? (int)(t.na & 0x7fff) : 0));             \
    int jbase = tokit ? 0 : jb;                                                                              \
    int remn = tokit ? (ng > 0 ? ng - 1 : 0) : rem - 1;                                                      \
    bool any = isev && jbase * SETS < t.cl;                                                                  \
    Item it;                                                                                                 \
    it.t = t;                                                                                                \
    it.jb = jbase;                                                                                           \
    it.pl = t.pl; it.tl = t.tl; it.cl = t.cl;                                                                \
    unsigned char f = 0;                                                                                     \
    if (tokit) f |= F_TOK;                                                                                   \
    if (kind == K_FWD && any) f |= F_SF;                                                                     \
    if (kind == K_BACK && any) f |= F_SB;                                                                    \
    if (kind == K_FWD && any && remn == 0) f |= F_LAST;                                                      \
    if (tokit && kind == K_FWD && !any) f |= F_EMIT0;                                                        \
    if (isclr) f |= F_CLR;                                                                                   \
    bool sfirst = tokit && isswp && t.v0 == 1;                                                               \
    if (sfirst) { rh = 0; rk = 0; rtx = 0; rty = 0; rz = 0; wh = 0; wk = 0; wtx = 0; wty = 0; wz = 0; }      \
    int jsw_ = sfirst ? 0 : jsw;                                                                             \
    bool srd = isswp && jsw_ < NSW, swr = isswp && jsw_ >= SLAG;                                             \
    if (isswp) jsw = jsw_ + 1;                                                                               \
    if (srd) f |= F_SRD;                                                                                     \
    if (swr) f |= F_SWR;                                                                                     \
    it.wv = swr ? vin.read() : 0.0f;                                                                         \
    {                                                                                                        \
      int ra = id + rk, rb = id - rk;                                                                        \
      ra = ra >= LANES ? ra - LANES : ra; rb = rb < 0 ? rb + LANES : rb;                                     \
      it.rc = rh ? 0 : 1; it.rt = rh ? rtx : rty; it.rz = rz;                                                \
      it.ru = (short)(rh ? LANES * rty + rb : LANES * rtx + ra);                                             \
      int wa = id + wk, wb = id - wk;                                                                        \
      wa = wa >= LANES ? wa - LANES : wa; wb = wb < 0 ? wb + LANES : wb;                                     \
      it.wc = wh ? 0 : 1; it.wt = wh ? wtx : wty; it.wz = wz;                                                \
      it.wu = (short)(wh ? LANES * wty + wb : LANES * wtx + wa);                                             \
    }                                                                                                        \
    if (srd) SWADV(rh, rk, rtx, rty, rz);                                                                    \
    if (swr) SWADV(wh, wk, wtx, wty, wz);                                                                    \
    it.fl = f;                                                                                               \
    if (tokit) {                                                                                             \
      if (kind == K_SETID) id = t.u0;                                                                        \
      if (isev) annot_next(it.t, t.pl, t.tl);                                                                \
    }                                                                                                        \
    wq.write(it);                                                                                            \
    c = t;                                                                                                   \
    rem = remn;                                                                                              \
    jb = jbase + 1;                                                                                          \
  }

// ---------------------------------------------------------------- eng (state: F, rst, myid, plane table, TOF table)
// EXP-S20 bank-set balance: local plane t of copy c lives in set SETP(c, t) = PP[c] (2-bit permutation of t % 4, per lane
// and copy, sent in the K_SETUP token's s field; copy 0 identity); the step of an item handled by set s is the one with
// t % 4 = INVS(c, s). Consecutive t still map to distinct sets. Balanced sets need DEPTH 5112 (5120) instead of 5808.
#define PERM_ID 0xE4
#define SETP(c, t) ((PP[(c) & 1] >> (2 * ((t) & 3))) & 3)
#define INVS(c, s) ((IP[(c) & 1] >> (2 * (s))) & 3)
#define ENG_BODY                                                                                           \
  {                                                                                                          \
    Item it = wq.read();                                                                                     \
    unsigned f = it.fl;                                                                                      \
    int kind = it.t.kind;                                                                                    \
    bool sf = f & F_SF, sb = f & F_SB, tokf = f & F_TOK, clr = f & F_CLR;                                    \
    int cp = (it.t.na >> 15) & 1;                                                                            \
    bool vtok = tokf && (kind == K_LOAD || kind == K_READ);                                                  \
    bool vmine = vtok && it.t.du == myid;                                                                    \
    int vt = (vtok && it.t.dv >= 0 && it.t.dv < TMAX) ? it.t.dv : 0, vu = vtok ? it.t.u0 : 0, vz = vtok ? it.t.v0 : 0;                                    \
    int vset = SETP(cp, vt), vb = (vu & 1) | ((vz & 1) << 1);                                                \
    int va = TB_BASE[cp][vt] + ((vu >> 1) - TB_ULO[cp][vt]) * HZ + (vz >> 1);                                \
    float val = 0.0f, rv = 0.0f, srv = 0.0f;                                                                 \
    bool srd = (f & F_SRD) != 0, swr = (f & F_SWR) != 0;                                                     \
    float wv = it.wv;                                                                                        \
    int rc_ = it.rc & 1, rt_ = it.rt < TMAX ? it.rt : 0, wc_ = it.wc & 1, wt_ = it.wt < TMAX ? it.wt : 0;    \
    int rrow = (it.ru >> 1) - TB_ULO[rc_][rt_], wrow = (it.wu >> 1) - TB_ULO[wc_][wt_];                      \
    bool rok = srd && rrow >= 0 && rrow < TB_NROW[rc_][rt_];                                                 \
    bool wok = swr && wrow >= 0 && wrow < TB_NROW[wc_][wt_];                                                 \
    int raddr = TB_BASE[rc_][rt_] + rrow * HZ + (it.rz >> 1);                                                \
    int waddr = TB_BASE[wc_][wt_] + wrow * HZ + (it.wz >> 1);                                                \
    int rset = SETP(rc_, rt_), wset = SETP(wc_, wt_);                                                        \
    int rbk = (it.ru & 1) | ((it.rz & 1) << 1), wbk = (it.wu & 1) | ((it.wz & 1) << 1);                      \
    _Pragma("unroll") for (int s = 0; s < SETS; s++) {                                                       \
      int o_ = (INVS(cp, s) - (it.tl + it.jb * SETS)) & (SETS - 1);                                          \
      int j_ = it.jb * SETS + o_;                                                                            \
      int k_ = (it.pl - it.t.i0) + LANES * j_;                                                               \
      Step st;                                                                                               \
      st.u = it.t.u0 + k_ * it.t.du; st.v = it.t.v0 + k_ * it.t.dv;                                          \
      st.d = it.t.d0 + k_ * it.t.dd; st.t = (short)(it.tl + j_); st.ok = j_ < it.cl;                         \
      bool sok = (sf || sb) && st.ok;                                                                        \
      int tl_ = (st.t >= 0 && st.t < TMAX) ? st.t : 0;                                                       \
      int iu = st.u >> FRAC, iv = st.v >> FRAC;                                                              \
      FU pu_, pv_, pt_;   /* 1 + fraction as float bits (exact): no int -> float converters */               \
      pu_.u = 0x3F800000u | ((unsigned)(st.u & ((1 << FRAC) - 1)) << (23 - FRAC));                          \
      pv_.u = 0x3F800000u | ((unsigned)(st.v & ((1 << FRAC) - 1)) << (23 - FRAC));                          \
      float fu1 = pu_.f - 1.0f, fu0 = 2.0f - pu_.f, fv1 = pv_.f - 1.0f, fv0 = 2.0f - pv_.f;                  \
      int ad = st.d < 0 ? -st.d : st.d;                                                                      \
      int ti = ad >> DFRAC;                                                                                  \
      pt_.u = 0x3F800000u | ((unsigned)(ad & ((1 << DFRAC) - 1)) << (23 - DFRAC));                          \
      bool tin = ti < TOFN;                                                                                  \
      int ti0 = tin ? ti : 0;                                                                                \
      float t0v = TT0[ti0][s], t1v = TT1[ti0][s];                                                            \
      if (tokf && kind == K_TOFTAB) { TT0[it.t.u0 & (TOFN - 1)][s] = i2f_bits(it.t.d0); TT1[it.t.u0 & (TOFN - 1)][s] = i2f_bits(it.t.dd); } \
      float tw = tin ? (t0v + pt_.f * t1v) : 0.0f;   /* A + (1 + f) B = k0 + f (k1 - k0) */                  \
      int base = TB_BASE[cp][tl_], ulo = TB_ULO[cp][tl_], nrw = TB_NROW[cp][tl_];                            \
      _Pragma("unroll") for (int b = 0; b < 4; b++) {                                                        \
        int bu = b & 1, bz = b >> 1;                                                                         \
        int cu = ((iu & 1) == bu) ? iu : iu + 1;                                                             \
        float wu = (cu == iu) ? fu0 : fu1;                                                                   \
        int cz = ((iv & 1) == bz) ? iv : iv + 1;                                                             \
        float wz = (cz == iv) ? fv0 : fv1;                                                                   \
        int row = (cu >> 1) - ulo;                                                                           \
        bool o = sok && cu >= 0 && cu < NU && cz >= 0 && cz < NZ && row >= 0 && row < nrw;                   \
        int sa = base + row * HZ + (cz >> 1);                                                                \
        bool vhere = vmine && vset == s && vb == b;                                                          \
        bool rhere = rok && rset == s && rbk == b, whr = wok && wset == s && wbk == b;                       \
        int a = clr ? it.jb : (vhere ? va : (rhere ? raddr : (o ? sa : 0)));                                 \
        int aw = whr ? waddr : a;                                                                            \
        float m = MEM[a][s * 4 + b];                                                                         \
        float w = o ? wu * wz * tw : 0.0f;                                                                   \
        val += (sf ? w : 0.0f) * m;                                                                          \
        rv = (vhere && kind == K_READ) ? m : rv;   /* at most one (s, b) hits: select, no adders */           \
        srv = rhere ? m : srv;                                                                               \
        bool wr = (sb && o) || clr || vhere || whr;                                                          \
        float nv = whr ? wv : (sb ? m + it.t.s * w : ((vhere && kind == K_LOAD) ? it.t.s : 0.0f));           \
        if (wr) MEM[aw][s * 4 + b] = nv;                                                                     \
      }                                                                                                      \
    }                                                                                                        \
    F = (rst ? 0.0f : F) + val;                                                                              \
    bool emitF = (f & F_LAST) != 0, emit0 = (f & F_EMIT0) != 0;                                              \
    if (tokf) {                                                                                              \
      Tok fw = it.t;                                                                                         \
      if (kind == K_SETID) { myid = fw.u0; fw.u0 = fw.u0 + 1; }                                              \
      if (kind == K_SETUP && fw.u0 == myid) {                                                                \
        int sc = fw.v0 & 1, st_ = (fw.du >= 0 && fw.du < TMAX) ? fw.du : 0;                                  \
        TB_BASE[sc][st_] = fw.dv; TB_ULO[sc][st_] = fw.d0; TB_NROW[sc][st_] = fw.dd;                         \
        int pk = fw.i0 & 255;                                                                                \
        PP[sc] = pk;                                                                                         \
        IP[sc] = (0 << (2 * (pk & 3))) | (1 << (2 * ((pk >> 2) & 3))) | (2 << (2 * ((pk >> 4) & 3))) |      \
                 (3 << (2 * ((pk >> 6) & 3)));                                                               \
      }                                                                                                      \
      out.write(fw);                                                                                         \
    }                                                                                                        \
    if (srd) vout.write(srv);                                                                                \
    bool emitR = tokf && kind == K_READ;                                                                     \
    if (emitF || emit0 || emitR) fl.write(emitF ? F : (emitR ? rv : 0.0f));                                  \
    rst = emitF;                                                                                             \
  }

static inline Tok ev2tok(const Ev &e, int ph, float s) {
  Tok t;
  t.i0 = e.i0; t.na = e.na; t.u0 = e.u0; t.v0 = e.v0; t.du = e.du; t.dv = e.dv; t.d0 = dfix(e.d0); t.dd = dfix(e.dd); t.s = s;
  t.kind = (e.i0 == -1000) ? K_NOP : (ph ? K_BACK : K_FWD);
  t.pl = e.p0; t.tl = e.t0; t.cl = e.c0; t.gl = e.g0;
  return t;
}
static inline Tok ctok(int kind, int u0, int v0, int du, int dv, int d0, int dd, float s, int copy) {
  Tok t;
  t.i0 = 0; t.na = (short)(copy << 15); t.u0 = u0; t.v0 = v0; t.du = du; t.dv = dv; t.d0 = d0; t.dd = dd; t.s = s;
  t.kind = kind; t.pl = 0; t.tl = 0; t.cl = 0; t.gl = 0;
  return t;
}
// SETUP (lane L, copy c, local plane t): base, ulo, nrow, set permutation in i0. TOFTAB entry i from k(i), k(i+1):
// the lane stores A = 2 k0 - k1, B = k1 - k0 and computes w = A + (1 + f) B with (1 + f) built from the fraction bits.
static inline Tok setup_tok(int L, int c, int t, int b, int u, int nr, int pm) {
  Tok r = ctok(K_SETUP, L, c, t, b, u, nr, 0.0f, 0);
  r.i0 = (short)pm;
  return r;
}
static inline Tok toftab_tok(int i, float k0, float k1) {
  float B = k1 - k0;
  return ctok(K_TOFTAB, i, 0, 0, 0, f2i_bits(k0 - B), f2i_bits(B), 0.0f, 0);
}
static inline Tok swtok(int q) {   // sweep token q of a pass: u0 = gl = items, v0 = 1 on the first
  int n = q < NSWTOK - 1 ? SWCH : NSW + SLAG - (NSWTOK - 1) * SWCH;
  Tok t = ctok(K_SWEEP, n, q == 0 ? 1 : 0, 0, 0, 0.0f, 0.0f, 0.0f, 0);
  t.gl = (short)n;
  return t;
}
static inline PTok ev2ptok(const Ev &e, int idx, float f0) { PTok q; q.F = f0; q.mw = e.mw; q.y = e.y; q.a = e.a; q.idx = idx; return q; }
static inline float ratio(const PTok &r) { float yh = r.mw * r.F + r.a; return (yh > 0.0f) ? r.mw * r.y / yh : 0.0f; }

#ifndef SWSIM

#ifndef ASP_E1
#define ASP_E1 1     // events EvW, even 64-byte words (src me1)
#define ASP_E2 2     // events EvW, odd words (src me2)
#define ASP_A 3      // a' (src ma)
#define ASP_S 4      // s (src ms, sink mss)
#define ASP_X 1      // x slot order (vox mx)
#define ASP_XN 1     // x' slot order (vox mxn): same space as x (next update reads it)
#define ASP_P 2      // P bf16, T bf16, T / P write (vox mp, mt, mtw)
#define ASP_G 3      // g_sum / sensitivity read, g_sum write (vox mg, mgw)
#define ASP_XR 3     // x' raster (vox mxr), kappa raster, boundary words, xs raster: RDP / Gaussian inputs
#define ASP_GP 4     // RDP output gp / H (vox mgp)
#endif
#define HOSTA(T, AS)                                                                                         \
  ihc::mm_master<T, ihc::aspace<AS>, ihc::awidth<34>, ihc::dwidth<512>, ihc::latency<0>, ihc::maxburst<64>,   \
                 ihc::waitrequest<true>>
#define VHOST(T)                                                                                             \
  ihc::mm_master<T, ihc::aspace<1>, ihc::awidth<34>, ihc::dwidth<512>, ihc::latency<0>, ihc::maxburst<64>,    \
                 ihc::waitrequest<true>>
// ================================================================= hardware components
hls_always_run_component component void slab_exp(ihc::stream_in<Tok, ihc::buffer<TOKBUF>> &in, ihc::stream_out<Item> &wq,
                                                  ihc::stream_in<float, ihc::buffer<64>> &vin) {
  Tok c;
  c.i0 = 0; c.na = 0; c.u0 = 0; c.v0 = 0; c.du = 0; c.dv = 0; c.d0 = 0.0f; c.dd = 0.0f; c.s = 0.0f; c.kind = K_NOP; c.pl = 0; c.tl = 0;
  c.cl = 0; c.gl = 0;
  int jb = 0, id = 0, rem = 0;
  int rh = 0, rk = 0, rtx = 0, rty = 0, rz = 0, wh = 0, wk = 0, wtx = 0, wty = 0, wz = 0, jsw = 0;
  while (1) EXP_BODY
}

hls_always_run_component component void slab_eng(ihc::stream_in<Item, ihc::buffer<64>> &wq, ihc::stream_out<Tok> &out,
                                                  ihc::stream_out<float> &fl, ihc::stream_out<float> &vout) {
  hls_numbanks(SETS * 4) hls_bankwidth(4) hls_singlepump hls_force_pow2_depth(0) static float MEM[DEPTH][SETS * 4];
  hls_numbanks(SETS) hls_bankwidth(4) hls_singlepump static float TT0[TOFN][SETS];
  hls_numbanks(SETS) hls_bankwidth(4) hls_singlepump static float TT1[TOFN][SETS];
  hls_register short TB_BASE[2][TMAX];
  hls_register unsigned char TB_ULO[2][TMAX], TB_NROW[2][TMAX];
#pragma unroll
  for (int c = 0; c < 2; c++)
#pragma unroll
    for (int t = 0; t < TMAX; t++) { TB_BASE[c][t] = 0; TB_ULO[c][t] = 0; TB_NROW[c][t] = 0; }
  hls_register int PP[2] = {PERM_ID, PERM_ID}, IP[2] = {PERM_ID, PERM_ID};
  float F = 0.0f;
  bool rst = true;
  int myid = 0;
#pragma ivdep
  while (1) ENG_BODY
}

#ifndef ENG_ONLY
hls_always_run_component component void padd(ihc::stream_in<PTok, ihc::buffer<TOKBUF>> &pin,
                                              ihc::stream_in<float, ihc::buffer<1024>> &fl, ihc::stream_out<PTok> &pout) {
  PTok p = pin.read();
  float f = fl.read();
  p.F += f;
  pout.write(p);
}

#define NROWTAB (2 * NPL)
struct RowEnt { short copy, plane, lane, t; short ulo2, nrow; int pad; };   // u from 2*ulo2 .. pad-1 (pad = min(2*(ulo2+nrow), NU))
// mode 7: raw tokens raw[0..cnt); mode 0: LOAD voxels from io (values in sweep order, chunk off..off+cnt of the sweep);
// mode 3: READ voxels (same sweep); mode 5: rep x forward (PTok start = finit ? s_in : 0); mode 6: rep x back (s_in)
// sweep order: rows table entries, u, z (all FOV voxels of both copies)
hls_avalon_slave_component component void slab_src(
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    hls_avalon_slave_memory_argument(NROWTAB * sizeof(RowEnt)) RowEnt *rowt,
    hls_avalon_slave_register_argument HOSTA(D512E, ASP_E1) &me1, hls_avalon_slave_register_argument HOSTA(D512E, ASP_E2) &me2,
    hls_avalon_slave_register_argument HOSTA(D512, ASP_A) &ma,
    hls_avalon_slave_register_argument HOSTA(D512, ASP_S) &ms,
    ihc::stream_out<Tok> &tout, ihc::stream_out<PTok> &pout,
    hls_avalon_slave_register_argument int mode, hls_avalon_slave_register_argument int nev,
    hls_avalon_slave_register_argument int off, hls_avalon_slave_register_argument int cnt,
    hls_avalon_slave_register_argument int rep, hls_avalon_slave_register_argument int finit,
    hls_avalon_slave_register_argument int rstart, hls_avalon_slave_register_argument int ustart,
    hls_avalon_slave_register_argument int zstart) {
  if (mode == 12 || mode == 13) {      // tokens off .. off + nev from DDR (rep times)
    bool bk = mode == 13;
    for (int r = 0; r < rep; r++) {
      D512E we; D512 wa, ws;
      for (int i = 0; i < nev; i++) {
        int gi = off + i;
        if ((gi & 1) == 0 || i == 0) { int w = gi >> 1; if (w & 1) we = me2[w >> 1]; else we = me1[w >> 1]; }
        if ((gi & 15) == 0 || i == 0) { if (bk) ws = ms[gi >> 4]; else wa = ma[gi >> 4]; }
        EvW e = (gi & 1) ? we.e[1] : we.e[0];
        float s = bk ? ws.v[gi & 15] : 0.0f;
        tout.write(evw2tok(e, bk ? 1 : 0, s));
        if (!bk && e.i0 != -1000) { PTok q; q.F = 0.0f; q.mw = e.mw; q.y = 1.0f; q.a = wa.v[gi & 15]; q.idx = gi; pout.write(q); }
      }
    }
    return;
  }
  if (mode == 11) {   // voxel sweep: NSWTOK tokens per pass (u0 = items, v0 = 1 on the first)
    for (int r = 0; r < rep; r++)
      for (int q = 0; q < NSWTOK; q++)
        tout.write(swtok(q));
    return;
  }
  if (mode == 4 || mode == 10) {
    tout.write(ctok(mode == 4 ? K_SETID : K_CLEAR, 0, 0, 0, 0, 0.0f, 0.0f, 0.0f, 0));
    return;
  }
  if (mode == 7) {      // SETUP: io = [lane, copy, t, base, ulo, nrow, set permutation] per entry
    for (int i = 0; i < cnt; i++)
      tout.write(setup_tok((int)io[7 * i], (int)io[7 * i + 1], (int)io[7 * i + 2], (int)io[7 * i + 3], (int)io[7 * i + 4],
                           (int)io[7 * i + 5], (int)io[7 * i + 6]));
    return;
  }
  if (mode == 9) {      // TOFTAB: io = [k(i), k(i+1)] per entry, entries off .. off + cnt
    for (int i = 0; i < cnt; i++) tout.write(toftab_tok(off + i, io[2 * i], io[2 * i + 1]));
    return;
  }
  if (mode == 0 || mode == 3) {
    // sweep position (row entry r, u, z) given by the host for the start of this chunk
    int r = rstart, u = ustart, z = zstart;
    RowEnt e = rowt[r];
    for (int i = 0; i < cnt; i++) {
      float v = io[i];
      Tok t;
      t.i0 = 0; t.na = (short)(e.copy << 15); t.u0 = u; t.v0 = z; t.du = e.lane; t.dv = e.t; t.d0 = 0.0f; t.dd = 0.0f;
      t.s = mode == 0 ? v : 0.0f; t.kind = mode == 0 ? K_LOAD : K_READ; t.pl = 0; t.tl = 0; t.cl = 0; t.gl = 0;
      tout.write(t);
      if (mode == 3) { PTok q; q.F = 0.0f; q.mw = 0.0f; q.y = 0.0f; q.a = 0.0f; q.idx = i; pout.write(q); }
      bool zw = z == NZ - 1;
      bool uw = u == e.pad - 1;
      z = zw ? 0 : z + 1;
      u = zw ? (uw ? 0 : u + 1) : u;
      if (zw && uw) { r = r + 1; e = rowt[r]; u = 2 * e.ulo2; }
    }
    return;
  }
  // (modes 5 / 6, on-chip event buffers, removed in EXP-S20: events come from DDR, modes 12 / 13)
}

hls_avalon_slave_component component void slab_sink(
    hls_avalon_slave_memory_argument(MAXEV * sizeof(float)) float *s_out,
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    hls_avalon_slave_register_argument HOSTA(D512, ASP_S) &mss,
    ihc::stream_in<Tok> &tin, ihc::stream_in<PTok> &pin,
    hls_avalon_slave_register_argument int nm, hls_avalon_slave_register_argument int nq,
    hls_avalon_slave_register_argument int raw) {
  int mi = 0, qi = 0;
  D512 sw;
#pragma unroll
  for (int e = 0; e < 16; e++) sw.v[e] = 0.0f;
  int cw = -1;
#pragma ivdep
  while (mi < nm || qi < nq) {
    if (mi < nm) {
      bool ok = false;
      Tok r = tin.tryRead(ok);
      if (ok) { io[mi & (IOCHUNK - 1)] = r.s; mi++; }
    }
    if (qi < nq) {
      bool ok = false;
      PTok p = pin.tryRead(ok);
      if (ok) {
        if (raw == 3) {
          int w = p.idx >> 4;
          if (w != cw && cw >= 0) {
            mss[cw] = sw;
#pragma unroll
            for (int e = 0; e < 16; e++) sw.v[e] = 0.0f;
          }
          cw = w;
          float rr = ratio(p);
#pragma unroll
          for (int e = 0; e < 16; e++) sw.v[e] = (e == (p.idx & 15)) ? rr : sw.v[e];
        } else if (raw == 2) io[p.idx & (IOCHUNK - 1)] = p.F; else s_out[p.idx & (MAXEV - 1)] = raw ? p.F : ratio(p);
        qi++;
      }
    }
  }
  if (raw == 3 && cw >= 0) mss[cw] = sw;
}

hls_avalon_slave_component component int slab_vox(
    hls_avalon_slave_register_argument HOSTA(D512, ASP_X) &mx, hls_avalon_slave_register_argument HOSTA(D512, ASP_XN) &mxn,
    hls_avalon_slave_register_argument HOSTA(D512U, ASP_P) &mp, hls_avalon_slave_register_argument HOSTA(D512U, ASP_P) &mt,
    hls_avalon_slave_register_argument HOSTA(D512U, ASP_P) &mtw, hls_avalon_slave_register_argument HOSTA(D512, ASP_G) &mg,
    hls_avalon_slave_register_argument HOSTA(D512, ASP_G) &mgw, hls_avalon_slave_register_argument HOSTA(D512, ASP_GP) &mgp,
    hls_avalon_slave_register_argument HOSTA(D512, ASP_XR) &mxr,
    VOX_STREAM_ARGS,
    hls_avalon_slave_register_argument int mode, hls_avalon_slave_register_argument int nd,
    hls_avalon_slave_register_argument int rep, hls_avalon_slave_register_argument float step,
    hls_avalon_slave_register_argument float Mf, hls_avalon_slave_register_argument float invM) {
#define MEMATTRV hls_numbanks(16) hls_bankwidth(4) hls_singlepump hls_force_pow2_depth(0)
#include "vox10_body.inc"
  return nd;
}

// pipelined (non-bursting, uncached) load / store sites: rare or untimed accesses (no burst buffers, no cache)
typedef ihc::lsu<ihc::style<ihc::PIPELINED>> PLSU;
#define LDP(m, i) PLSU::load(&(m)[i])
// host access to DDR: on-chip io buffer <-> DDR words base .. base + n (dir 0: io -> DDR, 1: DDR -> io)
#define IOW 1024
hls_avalon_slave_component component void slab_dma(hls_avalon_slave_register_argument HOSTA(D512, 1) &m1,
                                                    hls_avalon_slave_register_argument HOSTA(D512, 2) &m2,
                                                    hls_avalon_slave_register_argument HOSTA(D512, 3) &m3,
                                                    hls_avalon_slave_register_argument HOSTA(D512, 4) &m4,
                                                    hls_avalon_slave_register_argument int ch,
                                                    hls_avalon_slave_memory_argument(IOW * sizeof(D512)) D512 *io,
                                                    hls_avalon_slave_register_argument int dir,
                                                    hls_avalon_slave_register_argument int base,
                                                    hls_avalon_slave_register_argument int n) {
  if (dir == 0) {
    for (int i = 0; i < n; i++) {
      D512 v = io[i];
      if (ch == 1) PLSU::store(&m1[base + i], v);
      if (ch == 2) PLSU::store(&m2[base + i], v);
      if (ch == 3) PLSU::store(&m3[base + i], v);
      if (ch == 4) PLSU::store(&m4[base + i], v);
    }
  } else {
    for (int i = 0; i < n; i++) {
      D512 v;
      if (ch == 1) v = PLSU::load(&m1[base + i]);
      if (ch == 2) v = PLSU::load(&m2[base + i]);
      if (ch == 3) v = PLSU::load(&m3[base + i]);
      if (ch == 4) v = PLSU::load(&m4[base + i]);
      io[i] = v;
    }
  }
}

#ifndef NO_RDP
// RDP unit v4 (own clock domain): mode 0 gradient / 1 Hessian diagonal, slot-order output
hls_avalon_slave_component component int slab_rdp(
    hls_avalon_slave_register_argument HOSTA(D512, ASP_XR) &xin, hls_avalon_slave_register_argument HOSTA(D512U, ASP_XR) &kin,
    hls_avalon_slave_register_argument HOSTA(D512, ASP_XR) &mb, hls_avalon_slave_register_argument HOSTA(D512, ASP_GP) &mo,
    hls_avalon_slave_register_argument int mode, hls_avalon_slave_register_argument int braster,
    hls_avalon_slave_register_argument int nz, hls_avalon_slave_register_argument float eps2,
    hls_avalon_slave_register_argument float w1, hls_avalon_slave_register_argument float w2,
    hls_avalon_slave_register_argument float w3, hls_avalon_slave_register_argument float w4,
    hls_avalon_slave_register_argument float w5) {
#define MEMATTRX hls_singlepump hls_force_pow2_depth(0)
#define MEMATTRK hls_singlepump hls_force_pow2_depth(0)
#define MEMATTRC hls_singlepump hls_force_pow2_depth(0)
#include "rdp4_body.inc"
  return nz;
}
#endif
// Gaussian unit (preconditioner): raster in (+ boundary words), full raster out
hls_avalon_slave_component component int slab_gs(
    hls_avalon_slave_register_argument HOSTA(D512, ASP_XR) &xin, hls_avalon_slave_register_argument HOSTA(D512, ASP_XR) &mb,
    hls_avalon_slave_register_argument HOSTA(D512, ASP_XR) &mo, hls_avalon_slave_register_argument int nz,
    hls_avalon_slave_register_argument float gx0, hls_avalon_slave_register_argument float gx1,
    hls_avalon_slave_register_argument float gx2, hls_avalon_slave_register_argument float gx3,
    hls_avalon_slave_register_argument float gx4, hls_avalon_slave_register_argument float gy0,
    hls_avalon_slave_register_argument float gy1, hls_avalon_slave_register_argument float gy2,
    hls_avalon_slave_register_argument float gy3, hls_avalon_slave_register_argument float gy4,
    hls_avalon_slave_register_argument float gz0, hls_avalon_slave_register_argument float gz1,
    hls_avalon_slave_register_argument float gz2, hls_avalon_slave_register_argument float gz3) {
#define MEMATTRY hls_singlepump hls_force_pow2_depth(0)
#define MEMATTRZ hls_singlepump hls_force_pow2_depth(0)
#include "gs2_body.inc"
  return nz;
}
#include "seq_comp.inc"
#endif

int main() { return 0; }
#endif

#ifdef SWSIM
// ================================================================= software model of the same hardware
template <class T> struct SQ {
  std::deque<T> q;
  T read() { T x = q.front(); q.pop_front(); return x; }
  void write(T x) { q.push_back(x); }
  bool empty() { return q.empty(); }
};
struct LaneMem {
  float MEM[DEPTH][SETS * 4];
  float TT0[TOFN][SETS], TT1[TOFN][SETS];
  short TB_BASE[2][TMAX];
  unsigned char TB_ULO[2][TMAX], TB_NROW[2][TMAX];
  int PP[2], IP[2];
  Tok c;
  int jb, id, myid, rem;
  int rh, rk, rtx, rty, rz, wh, wk, wtx, wty, wz, jsw;
  bool rst;
  float F;
  long items;
};
static void lane_run(LaneMem &M, SQ<Tok> &in, SQ<Tok> &out, SQ<float> &fl, SQ<float> &vin, SQ<float> &vout) {
  SQ<Item> wq;
  {
    Tok &c = M.c; int &jb = M.jb, &id = M.id, &rem = M.rem;
    int &rh = M.rh, &rk = M.rk, &rtx = M.rtx, &rty = M.rty, &rz = M.rz, &wh = M.wh, &wk = M.wk, &wtx = M.wtx, &wty = M.wty, &wz = M.wz, &jsw = M.jsw;
    while (rem > 0 || !in.empty()) EXP_BODY
  }
  float(*MEM)[SETS * 4] = M.MEM;
  float(*TT0)[SETS] = M.TT0; float(*TT1)[SETS] = M.TT1;
  short(*TB_BASE)[TMAX] = M.TB_BASE; unsigned char(*TB_ULO)[TMAX] = M.TB_ULO; unsigned char(*TB_NROW)[TMAX] = M.TB_NROW;
  int *PP = M.PP, *IP = M.IP;
  float &F = M.F; bool &rst = M.rst; int &myid = M.myid;
  while (!wq.empty()) { M.items++; ENG_BODY }
}
static LaneMem *LM[LANES];

static SQ<float> VIN[LANES], VOUT[LANES];
#define MEMATTRV
static void vox_run(D512 *mx, D512 *mxn, D512U *mp, D512U *mt, D512U *mtw, D512 *mg, D512 *mgw, D512 *mgp, D512 *mxr, int mode, int nd,
                    int rep, float step, float Mf, float invM) {
  VOX_SWREFS;
#include "vox10_body.inc"
}
static void chain(SQ<Tok> &t0, SQ<PTok> &p0, SQ<Tok> &tN, SQ<PTok> &pN, long *items) {
  SQ<Tok> a = t0; SQ<PTok> pa = p0;
  for (int L = 0; L < LANES; L++) {
    SQ<Tok> b; SQ<float> fl; SQ<PTok> pb;
    long i0 = LM[L]->items;
    lane_run(*LM[L], a, b, fl, VIN[L], VOUT[L]);
    if (items) items[L] = LM[L]->items - i0;
    while (!pa.empty()) { PTok p = pa.read(); p.F += fl.read(); pb.write(p); }
    if (!fl.empty()) { printf("fl not drained in lane %d\n", L); exit(1); }
    a = b; pa = pb;
  }
  tN = a; pN = pa; t0.q.clear(); p0.q.clear();
}
#pragma pack(push, 1)
struct EvIn { short i0, na; int u0, v0, du, dv; float d0, dd, mw, y, a, pad; };   // prep_tof.py
#pragma pack(pop)
template <class T> std::vector<T> readf(const char *fn, bool must = true) {
  std::vector<T> v; FILE *f = fopen(fn, "rb");
  if (!f) { if (must) { printf("cannot open %s\n", fn); exit(1); } return v; }
  fseek(f, 0, SEEK_END); long n = ftell(f) / sizeof(T); fseek(f, 0, SEEK_SET); v.resize(n);
  if (fread(v.data(), sizeof(T), n, f) != (size_t)n) exit(1);
  fclose(f); return v;
}
template <class T> void writef(const char *fn, const std::vector<T> &v) { FILE *f = fopen(fn, "wb"); fwrite(v.data(), sizeof(T), v.size(), f); fclose(f); }

int main(int argc, char **argv) {
  const char *dir = argv[1];
  int HAZ = argc > 2 ? atoi(argv[2]) : 80;
  int NMAX = argc > 3 ? atoi(argv[3]) : 1 << 30;     // events used (board batches hold MAXEV tokens)
  char fn[1024];
  snprintf(fn, sizeof fn, "%s/ev_hw.bin", dir); auto evin = readf<EvIn>(fn);
  snprintf(fn, sizeof fn, "%s/img_fov.bin", dir); auto img = readf<float>(fn);
  snprintf(fn, sizeof fn, "%s/fov_rows.bin", dir); auto rows = readf<int>(fn);
  int NE = std::min((int)evin.size(), NMAX);
  std::vector<Ev> ev(NE);
  for (int i = 0; i < NE; i++) {
    const EvIn &r = evin[i]; Ev &e = ev[i];
    e.i0 = r.i0; e.na = r.na; e.u0 = r.u0; e.v0 = r.v0; e.du = r.du; e.dv = r.dv; e.d0 = r.d0; e.dd = r.dd;
    e.mw = r.mw; e.y = r.y; e.a = r.a;
    int p0 = ((r.i0 + LANES - 1) / LANES) * LANES;
    e.p0 = (short)p0; e.t0 = (short)(p0 / LANES);
    e.c0 = local_cnt(e.p0, e.i0, e.na & 0x7fff); e.g0 = (short)((e.c0 + SETS - 1) / SETS);
  }
  // ---- plane tables
  int ulo[2][NPL], nrow[2][NPL];
  for (int c = 0; c < 2; c++)
    for (int p = 0; p < NPL; p++) {
      int lo = rows[(c * NPL + p) * 2], hi = rows[(c * NPL + p) * 2 + 1];
      ulo[c][p] = lo < 0 ? 0 : lo >> 1;
      nrow[c][p] = lo < 0 ? 0 : (hi >> 1) - (lo >> 1) + 1;
    }
  static int base[LANES][2][TMAX], perm[LANES][2];
  long dmax = 0;
  for (int L = 0; L < LANES; L++) {
    // copy 0: identity; copy 1: the permutation of t % 4 -> set minimising the deepest set of this lane
    int pi[4] = {0, 1, 2, 3}, best[4] = {0, 1, 2, 3};
    long bm = -1;
    do {
      long acc[SETS] = {0, 0, 0, 0};
      for (int c = 0; c < 2; c++)
        for (int t = 0; t < TMAX; t++) {
          int p = L + LANES * t;
          if (p < NPL) acc[c ? pi[t & 3] : (t & 3)] += (long)nrow[c][p] * HZ;
        }
      long m = *std::max_element(acc, acc + SETS);
      if (bm < 0 || m < bm) { bm = m; std::copy(pi, pi + 4, best); }
    } while (std::next_permutation(pi, pi + 4));
    perm[L][0] = PERM_ID; perm[L][1] = best[0] | (best[1] << 2) | (best[2] << 4) | (best[3] << 6);
    for (int s = 0; s < SETS; s++) {
      long acc = 0;
      for (int c = 0; c < 2; c++)
        for (int t = 0; t < TMAX; t++) {
          int p = L + LANES * t;
          if (p >= NPL || ((perm[L][c] >> (2 * (t & 3))) & 3) != s) continue;
          base[L][c][t] = (int)acc;
          acc += (long)nrow[c][p] * HZ;
        }
      dmax = std::max(dmax, acc);
    }
  }
  printf("lanes %d sets %d: bank depth needed %ld (DEPTH %d)\n", LANES, SETS, dmax, DEPTH);
  if (dmax > DEPTH) { printf("DEPTH too small\n"); return 1; }
  auto inrow = [&](int c, int p, int u) { return nrow[c][p] > 0 && (u >> 1) >= ulo[c][p] && (u >> 1) < ulo[c][p] + nrow[c][p]; };
  // ---- hazard-free order (back projection read-modify-write): lane time model = items of the exp
  auto lane_view = [&](const Ev &e, int L, int &pl, int &cl) {
    int n = e.na & 0x7fff;
    int r = ((L - e.i0) % LANES + LANES) % LANES;
    pl = e.i0 + r;
    cl = local_cnt((short)pl, e.i0, (short)n);
  };
  std::vector<long long> last((size_t)2 * NPL * (NU + 1) * (NZ + 1), -(1LL << 40));
  long long tl[LANES];
  for (int L = 0; L < LANES; L++) tl[L] = 0;
  auto voxkeys = [&](const Ev &e, int k, int p, long long *keys) {
    int c = (e.na >> 15) & 1, nk = 0;
    int uu = e.u0 + k * e.du, vv = e.v0 + k * e.dv;
    int iu = uu >> FRAC, iv = vv >> FRAC;
    for (int b = 0; b < 4; b++) {
      int cu = iu + (b & 1), cz = iv + (b >> 1);
      if (cu < 0 || cu >= NU || cz < 0 || cz >= NZ || !inrow(c, p, cu)) continue;
      keys[nk++] = (((long long)c * NPL + p) * (NU + 1) + cu) * (NZ + 1) + cz;
    }
    return nk;
  };
  auto need = [&](const Ev &e, long long nd[LANES]) {
    long long tot = 0; long long kv[4];
    for (int L = 0; L < LANES; L++) {
      nd[L] = 0;
      int pl, cl; lane_view(e, L, pl, cl);
      for (int j = 0; j < cl; j++) {
        int p = pl + LANES * j, k = p - e.i0;
        long long t = tl[L] + j / SETS;
        int nv = voxkeys(e, k, p, kv);
        for (int q = 0; q < nv; q++) { long long gap = t - last[kv[q]]; if (gap < HAZ && HAZ - gap > nd[L]) nd[L] = HAZ - gap; }
      }
      tot += nd[L];
    }
    return tot;
  };
  std::vector<Ev> sch; std::vector<int> gidx;
  std::vector<int> pend; size_t next = 0; long nops = 0, bub = 0;
  long long nd[LANES], bn[LANES], kv[4];
  while (next < (size_t)NE || !pend.empty()) {
    while (pend.size() < 64 && next < (size_t)NE) pend.push_back((int)next++);
    int best = -1; long long bs = 1LL << 60;
    for (size_t i = 0; i < pend.size(); i++) {
      long long s = need(ev[pend[i]], nd);
      if (s < bs) { bs = s; best = (int)i; memcpy(bn, nd, sizeof(bn)); }
      if (s == 0) break;
    }
    const Ev &e = ev[pend[best]];
    while (bs > 0) {
      for (int L = 0; L < LANES; L++)
        if (bn[L] > 0) {
          Ev d; memset(&d, 0, sizeof(d)); d.i0 = -1000; d.u0 = L; d.na = (short)bn[L];
          sch.push_back(d); gidx.push_back(-1);
          for (int M = 0; M < LANES; M++) tl[M] += 1;
          tl[L] += bn[L] - 1; nops++; bub += bn[L];
        }
      bs = need(e, bn);
    }
    for (int L = 0; L < LANES; L++) {
      int pl, cl; lane_view(e, L, pl, cl);
      for (int j = 0; j < cl; j++) {
        int p = pl + LANES * j, k = p - e.i0;
        int nv = voxkeys(e, k, p, kv);
        for (int q = 0; q < nv; q++) last[kv[q]] = tl[L] + j / SETS;
      }
      tl[L] += std::max(1, (cl + SETS - 1) / SETS);
    }
    sch.push_back(e); gidx.push_back(pend[best]);
    pend.erase(pend.begin() + best);
  }
  long long tmax = 0, tsum = 0;
  for (int L = 0; L < LANES; L++) { tmax = std::max(tmax, tl[L]); tsum += tl[L]; }
  int NS = (int)sch.size();
  printf("scheduled %d tokens (%d events, %ld NOP, %ld bubbles); lane items max %lld mean %.0f\n", NS, NE, nops, bub, tmax,
         (double)tsum / LANES);
  if (NS > MAXEV) printf("WARNING: %d tokens > MAXEV %d (board batch)\n", NS, MAXEV);
  // ---- board files: raw setup tokens, row table + sweep, chunk starts
  std::vector<Tok> raw;
  std::vector<float> su, tt;     // host files (unchanged format): setup_io 7 floats per entry, toftab_io [k(i), k(i+1)]
  raw.push_back(ctok(K_SETID, 0, 0, 0, 0, 0, 0, 0, 0));
  for (int L = 0; L < LANES; L++)
    for (int c = 0; c < 2; c++)
      for (int t = 0; t < TMAX; t++) {
        int p = L + LANES * t;
        int b = (p < NPL) ? base[L][c][t] : 0, u = (p < NPL) ? ulo[c][p] : 0, nr = (p < NPL) ? nrow[c][p] : 0;
        raw.push_back(setup_tok(L, c, t, b, u, nr, perm[L][c]));
        float v[7] = {(float)L, (float)c, (float)t, (float)b, (float)u, (float)nr, (float)perm[L][c]};
        su.insert(su.end(), v, v + 7);
      }
  const double W = 5 * 89 * 0.299792458 / 2, SIG = 0.5 * 550.0 * 0.299792458 / 2.354820045;
  auto kern = [&](double d) { return 0.5 * (erf((d + W / 2) / (sqrt(2.0) * SIG)) - erf((d - W / 2) / (sqrt(2.0) * SIG))); };
  for (int i = 0; i < TOFN; i++) {
    float k0 = (float)kern(TOFHALF * i / TOFN), k1 = (float)kern(TOFHALF * (i + 1) / TOFN);
    raw.push_back(toftab_tok(i, k0, k1));
    tt.push_back(k0); tt.push_back(k1);
  }
  snprintf(fn, sizeof fn, "%s/hw8/raw_setup.bin", dir); writef(fn, raw);
  {
    snprintf(fn, sizeof fn, "%s/hw8/setup_io.bin", dir); writef(fn, su);
    snprintf(fn, sizeof fn, "%s/hw8/toftab_io.bin", dir); writef(fn, tt);
  }
  std::vector<Tok> rclr(1, ctok(K_CLEAR, 0, 0, 0, 0, 0, 0, 0, 0));
  snprintf(fn, sizeof fn, "%s/hw8/raw_clear.bin", dir); writef(fn, rclr);
  struct RowE { short copy, plane, lane, t; short ulo2, nrow; int pad; };
  std::vector<RowE> rt;
  std::vector<float> sweepv; std::vector<int> sweeppos;
  for (int c = 0; c < 2; c++)
    for (int p = 0; p < NPL; p++) {
      if (nrow[c][p] == 0) continue;
      RowE r; r.copy = (short)c; r.plane = (short)p; r.lane = (short)(p % LANES); r.t = (short)(p / LANES);
      r.ulo2 = (short)ulo[c][p]; r.nrow = (short)nrow[c][p]; r.pad = std::min(2 * (ulo[c][p] + nrow[c][p]), NU);
      rt.push_back(r);
      for (int u = 2 * ulo[c][p]; u < r.pad; u++)
        for (int z = 0; z < NZ; z++) {
          int x = c ? u : p, y = c ? p : u;
          sweepv.push_back(img[((size_t)z * NPL + y) * NPL + x]);
          sweeppos.push_back((int)(((size_t)z * NPL + y) * NPL + x));
        }
    }
  RowE pad_; memset(&pad_, 0, sizeof(pad_)); rt.push_back(pad_);   // src reads one entry past the end
  snprintf(fn, sizeof fn, "%s/hw8/rowt.bin", dir); writef(fn, rt);
  snprintf(fn, sizeof fn, "%s/hw8/img_sweep.bin", dir); writef(fn, sweepv);
  {   // chunk starts (row entry, u, z) for chunks of IOCHUNK voxels
    snprintf(fn, sizeof fn, "%s/hw8/chunks.txt", dir); FILE *f = fopen(fn, "w");
    long i = 0; int r = 0, u = 2 * rt[0].ulo2, z = 0;
    while (i < (long)sweepv.size()) {
      long cnt = std::min((long)IOCHUNK, (long)sweepv.size() - i);
      fprintf(f, "%ld %d %d %d %ld\n", i, r, u, z, cnt);
      for (long q = 0; q < cnt; q++) {   // advance like the src sweep
        bool zw = z == NZ - 1, uw = u == rt[r].pad - 1;
        z = zw ? 0 : z + 1; u = zw ? (uw ? 0 : u + 1) : u;
        if (zw && uw) { r++; u = 2 * rt[r].ulo2; }
      }
      i += cnt;
    }
    fclose(f);
  }
  snprintf(fn, sizeof fn, "%s/hw8/ev7.bin", dir); writef(fn, sch);
  // ---- run the model on the scheduled tokens: setup, load (sweep), forward, clear, back, read (sweep)
  for (int L = 0; L < LANES; L++) { LM[L] = (LaneMem *)calloc(1, sizeof(LaneMem)); LM[L]->rst = true; LM[L]->c.kind = K_NOP;
    LM[L]->PP[0] = LM[L]->PP[1] = LM[L]->IP[0] = LM[L]->IP[1] = PERM_ID; }
  SQ<Tok> t0, tN; SQ<PTok> p0, pN;
  for (auto &r : raw) t0.write(r);
  chain(t0, p0, tN, pN, NULL);
  {
    size_t i = 0;
    for (size_t r = 0; r + 1 < rt.size(); r++)
      for (int u = 2 * rt[r].ulo2; u < rt[r].pad; u++)
        for (int z = 0; z < NZ; z++)
          t0.write(ctok(K_LOAD, u, z, rt[r].lane, rt[r].t, 0, 0, sweepv[i++], rt[r].copy));
  }
  chain(t0, p0, tN, pN, NULL);
  long items[LANES];
  int nf = 0;
  for (int i = 0; i < NS; i++) { t0.write(ev2tok(sch[i], 0, 0.0f)); if (sch[i].i0 != -1000) { p0.write(ev2ptok(sch[i], i, 0.0f)); nf++; } }
  chain(t0, p0, tN, pN, items);
  std::vector<float> s(NS, 0.0f), Fhw(NE, 0.0f);
  while (!pN.empty()) { PTok r = pN.read(); s[r.idx] = ratio(r); if (gidx[r.idx] >= 0) Fhw[gidx[r.idx]] = r.F * r.mw; }
  long imax = *std::max_element(items, items + LANES);
  printf("forward (model): lane items max %ld (scheduler %lld)\n", imax, tmax);
  t0.write(ctok(K_CLEAR, 0, 0, 0, 0, 0, 0, 0, 0));
  chain(t0, p0, tN, pN, NULL);
  for (int i = 0; i < NS; i++) t0.write(ev2tok(sch[i], 1, s[i]));
  chain(t0, p0, tN, pN, NULL);
  long nrd = 0;
  {
    for (size_t r = 0; r + 1 < rt.size(); r++)
      for (int u = 2 * rt[r].ulo2; u < rt[r].pad; u++)
        for (int z = 0; z < NZ; z++) {
          t0.write(ctok(K_READ, u, z, rt[r].lane, rt[r].t, 0, 0, 0, rt[r].copy));
          PTok q; q.F = 0.0f; q.mw = 0.0f; q.y = 0.0f; q.a = 0.0f; q.idx = (int)nrd++; p0.write(q);
        }
  }
  chain(t0, p0, tN, pN, NULL);
  std::vector<float> rd(sweepv.size()), back((size_t)NZ * NPL * NPL, 0.0f);
  while (!pN.empty()) { PTok q = pN.read(); rd[q.idx] = q.F; }
  for (size_t i = 0; i < rd.size(); i++) back[sweeppos[i]] += rd[i];
  snprintf(fn, sizeof fn, "%s/hw8/expect_s.bin", dir); writef(fn, s);
  snprintf(fn, sizeof fn, "%s/hw8/sw_back.bin", dir); writef(fn, back);
  snprintf(fn, sizeof fn, "%s/hw8/sw_F.bin", dir); writef(fn, Fhw);
  snprintf(fn, sizeof fn, "%s/hw8/expect_read.bin", dir); writef(fn, rd);
  snprintf(fn, sizeof fn, "%s/hw8/sweep_pos.bin", dir); writef(fn, sweeppos);
  snprintf(fn, sizeof fn, "%s/hw8/meta.txt", dir); FILE *mf = fopen(fn, "w");
  fprintf(mf, "nev %d\nnf %d\nnsweep %zu\nnrowt %zu\nnraw %zu\nhaz %d\nmax_lane_items %lld\nevents %d\nnops %ld\n", NS, nf,
          sweepv.size(), rt.size() - 1, raw.size(), HAZ, tmax, NE, nops);
  fclose(mf);
  // ---- compare with the GPU reference (events in input order, first NE)
  snprintf(fn, sizeof fn, "%s/F_ref.bin", dir); auto Fr = readf<double>(fn, false);
  snprintf(fn, sizeof fn, "%s/back_ref.bin", dir); auto Br = readf<float>(fn, false);
  if (!Fr.empty() && NE == (int)evin.size()) {
    std::vector<double> Fs(Fr.begin(), Fr.begin() + NE); std::sort(Fs.begin(), Fs.end()); double med = Fs[NE / 2], eF = 0;
    for (int i = 0; i < NE; i++) eF = std::max(eF, fabs(Fhw[i] - Fr[i]) / med);
    double bm = 0, be = 0;
    for (size_t i = 0; i < sweeppos.size(); i++) {
      int q = sweeppos[i], x = q % NPL, y = (q / NPL) % NPL;
      int lo = rows[(0 * NPL + x) * 2], hi = rows[(0 * NPL + x) * 2 + 1];
      if (lo < 0 || y < lo || y > hi) continue;                      // true FOV only (P = 0 outside)
      bm = std::max(bm, (double)fabs(Br[q])); be = std::max(be, (double)fabs(back[q] - Br[q]));
    }
    printf("vs GPU parallelproj: forward max |dF| / median F %.3e; back (FOV) max abs diff / max %.3e\n", eF, be / bm);
  }

  // ================= EXP-S18: voxel sweep (lanes hold ACC of the back projection above) + central voxel unit
  {
    const int ND = NZ * NTILE * NTILE * LANES, NSL = ND * LANES;
    std::vector<int> slotpos(NSL);
    for (int n = 0; n < NSL; n++) {
      int i = n % LANES, k = (n / LANES) % LANES, T = (n / (LANES * LANES)) % (NTILE * NTILE), z = n / (LANES * LANES * NTILE * NTILE);
      int y = LANES * (T / NTILE) + i, x = LANES * (T % NTILE) + (i + k) % LANES;
      slotpos[n] = (z * NPL + y) * NPL + x;
    }
    std::vector<float> accv((size_t)NZ * NPL * NPL, 0.0f);   // back projection per voxel (sum of both copies)
    for (size_t i = 0; i < rd.size(); i++) accv[sweeppos[i]] += rd[i];
    // test inputs (deterministic pseudo-random): X = image, P in FOV rows, T, GS, GP
    std::vector<D512> X(NSL / 16), XN(NSL / 16), GS(NSL / 16), GSW(NSL / 16), GP(NSL / 16);
    std::vector<D512U> PB(NSL / 32), TB(NSL / 32), TW(NSL / 32);
    unsigned rs = 12345u;
    auto rnd = [&]() { rs = rs * 1664525u + 1013904223u; return (float)((rs >> 8) & 0xffff) / 65536.0f; };
    std::vector<float> Pf(NSL), Tf(NSL);
    for (int n = 0; n < NSL; n++) {
      int q = slotpos[n], xx = q % NPL, yy = (q / NPL) % NPL;
      int lo = rows[(0 * NPL + xx) * 2], hi = rows[(0 * NPL + xx) * 2 + 1];
      bool fov = lo >= 0 && yy >= lo && yy <= hi;
      X[n / 16].v[n % 16] = img[q] + 0.01f * rnd();
      Pf[n] = fov ? bf2f(f2bf(0.5f + rnd())) : 0.0f;
      Tf[n] = bf2f(f2bf(accv[q] * (0.9f + 0.2f * rnd())));
      GS[n / 16].v[n % 16] = 0.1f * (rnd() - 0.5f);
      GP[n / 16].v[n % 16] = 0.05f * (rnd() - 0.5f);
      unsigned pb = f2bf(Pf[n]), tb = f2bf(Tf[n]);
      unsigned &pw = PB[n / 32].v[(n % 32) / 2], &tw = TB[n / 32].v[(n % 32) / 2];
      if (n & 1) { pw |= pb << 16; tw |= tb << 16; } else { pw = pb; tw = tb; }
    }
    const float STEP = 0.7f, MF = 8.0f, IM = 1.0f / 8.0f;
    // the READ sweep above cleared the accumulators (read-and-clear): back-project again
    t0.write(ctok(K_CLEAR, 0, 0, 0, 0, 0, 0, 0, 0));
    chain(t0, p0, tN, pN, NULL);
    for (int i = 0; i < NS; i++) t0.write(ev2tok(sch[i], 1, s[i]));
    chain(t0, p0, tN, pN, NULL);
    // run 1: lane reads (ACC) with dummy writes, on a copy of the lane state
    std::vector<LaneMem> bak(LANES);
    for (int L = 0; L < LANES; L++) bak[L] = *LM[L];
    for (int L = 0; L < LANES; L++) for (int j = 0; j < NSW; j++) VIN[L].write(0.0f);
    for (int q = 0; q < NSWTOK; q++) t0.write(swtok(q));
    chain(t0, p0, tN, pN, NULL);
    for (int L = 0; L < LANES; L++) {
      if (!VIN[L].empty() || (int)VOUT[L].q.size() != NSW) { printf("sweep run 1: lane %d vin left %zu vout %zu\n", L, VIN[L].q.size(), VOUT[L].q.size()); return 1; }
      *LM[L] = bak[L];
    }
    std::vector<D512> XR((size_t)NZ * PS / 16);
    memset(XR.data(), 0, XR.size() * sizeof(D512));
    vox_run(X.data(), XN.data(), PB.data(), TB.data(), TW.data(), GS.data(), GSW.data(), GP.data(), XR.data(), 0, ND, 1, STEP, MF, IM);
    {  // raster x' must equal XN at every slot, zeros in columns 200..207
      double re = 0; long nbad = 0;
      for (int n = 0; n < NSL; n++) {
        int q = slotpos[n], xx = q % NPL, yy = (q / NPL) % NPL, zz = q / (NPL * NPL);
        size_t e = (size_t)zz * PS + (size_t)yy * RS + xx;
        double dv = fabs(XR[e / 16].v[e % 16] - XN[n / 16].v[n % 16]); re = std::max(re, dv); nbad += dv > 0;
      }
      long nz8 = 0;
      for (int zz = 0; zz < NZ; zz++) for (int yy = 0; yy < 200; yy++) for (int xx = 200; xx < 208; xx++) {
        size_t e = (size_t)zz * PS + (size_t)yy * RS + xx; nz8 += XR[e / 16].v[e % 16] != 0.0f; }
      printf("S19 raster x': max |XR - XN| %.3e (%ld slots differ), nonzero pad columns %ld\n", re, nbad, nz8);
    }
    {  // mode 5 (preconditioner) on copies: P = T > 0 ? x / (gs + 2 gp x) : 0
      std::vector<D512U> TW5(NSL / 32);
      size_t vin0[LANES]; for (int L = 0; L < LANES; L++) vin0[L] = VIN[L].q.size();
      vox_run(X.data(), XN.data(), PB.data(), TB.data(), TW5.data(), GS.data(), GSW.data(), GP.data(), XR.data(), 5, ND, 1, STEP, MF, IM);
      double pe = 0;
      for (int n = 0; n < NSL; n++) {
        float x = X[n / 16].v[n % 16], gs = GS[n / 16].v[n % 16], gp = GP[n / 16].v[n % 16];
        float ref = Tf[n] > 0.0f ? x / (gs + 2.0f * gp * x) : 0.0f;
        unsigned w = TW5[n / 32].v[(n % 32) / 2]; float hw = bf2f((n & 1) ? (w >> 16) : (w & 0xffffu));
        float rb = bf2f(f2bf(ref)); if (rb == rb && fabs(rb) < 1e30) pe = std::max(pe, (double)fabs(hw - rb) / (fabs(rb) + 1e-6));
      }
      printf("S19 voxel unit mode 5 (preconditioner): max relative |hw - bf16(ref)| %.3e\n", pe);
      for (int L = 0; L < LANES; L++) if (!VOUT[L].empty() || VIN[L].q.size() != vin0[L]) { printf("mode 5 touched lane streams\n"); return 1; }
    }
    for (int L = 0; L < LANES; L++) if (!VOUT[L].empty() || (int)VIN[L].q.size() != NSW) { printf("vox: lane %d left %zu / vin %zu\n", L, VOUT[L].q.size(), VIN[L].q.size()); return 1; }
    for (int q = 0; q < NSWTOK; q++) t0.write(swtok(q));
    chain(t0, p0, tN, pN, NULL);
    for (int L = 0; L < LANES; L++) { VOUT[L].q.clear(); if (!VIN[L].empty()) { printf("sweep run 2: vin left\n"); return 1; } }
    // independent reference of mode 0
    double emax = 0, xmax = 0; long nlane = 0; int nbad = 0;
    std::vector<float> lanexp((size_t)NZ * NPL * NPL, 0.0f);
    for (int n = 0; n < NSL; n++) {
      int q = slotpos[n];
      float x = X[n / 16].v[n % 16], gs = GS[n / 16].v[n % 16], gp = GP[n / 16].v[n % 16];
      float d = (accv[q] - Tf[n]) * MF - gp + gs;
      float xn = x + STEP * Pf[n] * d; xn = xn > 0.0f ? xn : 0.0f;
      double e_ = fabs(xn - XN[n / 16].v[n % 16]);
      if (e_ > 1e-4 * (fabs(xn) + 1e-3) && nbad < 8) { nbad++; printf("bad slot %d (i %d k %d d %d): ref %g model %g acc %g x %g P %g\n", n, n % LANES, (n / LANES) % LANES, n / LANES, xn, XN[n / 16].v[n % 16], accv[q], x, Pf[n]); }
      emax = std::max(emax, e_); xmax = std::max(xmax, (double)fabs(xn));
      lanexp[q] = Pf[n] > 0.0f ? xn : 0.0f;
    }
    printf("S18 voxel unit (model) mode 0: max |XN - ref| / max %.3e over %d slots\n", emax / xmax, NSL);
    // read the lanes back (K_READ sweep) and compare with the expected image
    long nrd2 = 0;
    for (size_t r = 0; r + 1 < rt.size(); r++)
      for (int u = 2 * rt[r].ulo2; u < rt[r].pad; u++)
        for (int z = 0; z < NZ; z++) {
          t0.write(ctok(K_READ, u, z, rt[r].lane, rt[r].t, 0, 0, 0, rt[r].copy));
          PTok q; q.F = 0.0f; q.mw = 0.0f; q.y = 0.0f; q.a = 0.0f; q.idx = (int)nrd2++; p0.write(q);
        }
    chain(t0, p0, tN, pN, NULL);
    std::vector<float> rd2(sweepv.size()), exp2(sweepv.size());
    while (!pN.empty()) { PTok q = pN.read(); rd2[q.idx] = q.F; }
    double le = 0, lm = 0;
    for (size_t i = 0; i < rd2.size(); i++) {
      exp2[i] = lanexp[sweeppos[i]];
      le = std::max(le, (double)fabs(rd2[i] - exp2[i])); lm = std::max(lm, (double)fabs(exp2[i])); nlane++;
    }
    printf("S18 lanes after the sweep: max |IMG - expected| / max %.3e over %ld stored voxels\n", le / lm, nlane);
    snprintf(fn, sizeof fn, "%s/hw8/X.bin", dir); writef(fn, X);
    snprintf(fn, sizeof fn, "%s/hw8/P.bin", dir); writef(fn, PB);
    snprintf(fn, sizeof fn, "%s/hw8/T.bin", dir); writef(fn, TB);
    snprintf(fn, sizeof fn, "%s/hw8/GS.bin", dir); writef(fn, GS);
    snprintf(fn, sizeof fn, "%s/hw8/GP.bin", dir); writef(fn, GP);
    snprintf(fn, sizeof fn, "%s/hw8/expect_XN.bin", dir); writef(fn, XN);
    snprintf(fn, sizeof fn, "%s/hw8/expect_read8.bin", dir); writef(fn, rd2);
    snprintf(fn, sizeof fn, "%s/hw8/vox_meta.txt", dir); FILE *vf = fopen(fn, "w");
    fprintf(vf, "nd %d\nnslot %d\nstep %.9g\nM %.9g\ninvM %.9g\n", ND, NSL, STEP, MF, IM); fclose(vf);
  }
  return 0;
}
#endif

