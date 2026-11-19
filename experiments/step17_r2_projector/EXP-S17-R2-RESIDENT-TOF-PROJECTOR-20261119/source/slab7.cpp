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
#define DEPTH 6144
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

enum { K_FWD = 0, K_BACK = 1, K_LOAD = 2, K_READ = 3, K_SETID = 4, K_NOP = 5, K_SETUP = 6, K_CLEAR = 7, K_TOFTAB = 8 };

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
  float d0, dd;
  float s;
  int kind;
  short pl, tl;           // annotation for the receiving lane: first plane, its local index
  short cl, gl;           // local steps and items in the receiving lane
};
struct PTok { float F, mw, y, a; int idx; };
struct Step { int u, v; float d; short t; short ok; };
#define F_TOK 1
#define F_SF 2
#define F_SB 4
#define F_LAST 8
#define F_EMIT0 16
#define F_CLR 32
struct Item {
  Tok t;                  // token (forwarded with the next lane's annotation)
  int jb;                 // item index within the token (steps jb*SETS .. jb*SETS+SETS-1 of this lane; CLEAR address)
  short pl, tl, cl;       // this lane's first plane, its local index, local steps
  unsigned char fl;
};

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

// ---------------------------------------------------------------- exp (state: c, jb, more, id)
// exp state: c (current token), jb (item index within the token), rem (items left after this one), id
// items per token: events -> gl (from the annotation), CLEAR -> DEPTH, own NOP -> n, other tokens -> 1
// exp state: c (current token), jb (item index within the token), rem (items left after this one), id
// items per token: events -> gl (from the annotation), CLEAR -> DEPTH, own NOP -> n, other tokens -> 1.
// exp only counts; the engine computes the steps (k, u, v, d) of the item from (token, jb, this lane's pl / tl / cl).
#define EXP_BODY                                                                                             \
  {                                                                                                          \
    bool tokit = rem == 0;                                                                                   \
    Tok t;                                                                                                   \
    if (tokit) t = in.read(); else t = c;                                                                    \
    int kind = t.kind;                                                                                       \
    bool isev = kind == K_FWD || kind == K_BACK;                                                             \
    bool isclr = kind == K_CLEAR;                                                                            \
    bool isnop = kind == K_NOP && t.u0 == id;                                                                \
    int ng = isev ? (int)t.gl : (isclr ? DEPTH : (isnop ? (int)(t.na & 0x7fff) : 0));                         \
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
    it.fl = f;                                                                                               \
    if (tokit) {                                                                                             \
      if (kind == K_SETID) id = t.u0;                                                                        \
      annot_next(it.t, t.pl, t.tl);                                                                          \
    }                                                                                                        \
    wq.write(it);                                                                                            \
    c = t;                                                                                                   \
    rem = remn;                                                                                              \
    jb = jbase + 1;                                                                                          \
  }

// ---------------------------------------------------------------- eng (state: F, rst, myid, plane table, TOF table)
#define ENG_BODY                                                                                             \
  {                                                                                                          \
    Item it = wq.read();                                                                                     \
    unsigned f = it.fl;                                                                                      \
    int kind = it.t.kind;                                                                                    \
    bool sf = f & F_SF, sb = f & F_SB, tokf = f & F_TOK, clr = f & F_CLR;                                    \
    int cp = (it.t.na >> 15) & 1;                                                                            \
    bool vtok = tokf && (kind == K_LOAD || kind == K_READ);                                                  \
    bool vmine = vtok && it.t.du == myid;                                                                    \
    int vt = (vtok && it.t.dv >= 0 && it.t.dv < TMAX) ? it.t.dv : 0, vu = vtok ? it.t.u0 : 0, vz = vtok ? it.t.v0 : 0;                                    \
    int vset = vt & (SETS - 1), vb = (vu & 1) | ((vz & 1) << 1);                                             \
    int va = TB_BASE[cp][vt] + ((vu >> 1) - TB_ULO[cp][vt]) * HZ + (vz >> 1);                                \
    float val = 0.0f, rv = 0.0f;                                                                             \
    _Pragma("unroll") for (int s = 0; s < SETS; s++) {                                                       \
      int o_ = (s - (it.tl + it.jb * SETS)) & (SETS - 1);                                                    \
      int j_ = it.jb * SETS + o_;                                                                            \
      int k_ = (it.pl - it.t.i0) + LANES * j_;                                                               \
      Step st;                                                                                               \
      st.u = it.t.u0 + k_ * it.t.du; st.v = it.t.v0 + k_ * it.t.dv;                                          \
      st.d = it.t.d0 + (float)k_ * it.t.dd; st.t = (short)(it.tl + j_); st.ok = j_ < it.cl;                  \
      bool sok = (sf || sb) && st.ok;                                                                        \
      int tl_ = (st.t >= 0 && st.t < TMAX) ? st.t : 0;                                                       \
      int iu = st.u >> FRAC, iv = st.v >> FRAC;                                                              \
      float fu = (float)(st.u & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));                                   \
      float fv = (float)(st.v & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));                                   \
      float ad = fabsf(st.d) * ((float)TOFN / TOFHALF);                                                      \
      int ti = (int)ad;                                                                                      \
      float tf = ad - (float)ti;                                                                             \
      bool tin = ti < TOFN;                                                                                  \
      int ti0 = tin ? ti : 0;                                                                                \
      float t0v = TT0[ti0][s], t1v = TT1[ti0][s];                                                            \
      if (tokf && kind == K_TOFTAB) { TT0[it.t.u0 & (TOFN - 1)][s] = it.t.d0; TT1[it.t.u0 & (TOFN - 1)][s] = it.t.dd; } \
      float tw = tin ? (t0v + tf * (t1v - t0v)) : 0.0f;                                                      \
      int base = TB_BASE[cp][tl_], ulo = TB_ULO[cp][tl_], nrw = TB_NROW[cp][tl_];                            \
      _Pragma("unroll") for (int b = 0; b < 4; b++) {                                                        \
        int bu = b & 1, bz = b >> 1;                                                                         \
        int cu = ((iu & 1) == bu) ? iu : iu + 1;                                                             \
        float wu = (cu == iu) ? (1.0f - fu) : fu;                                                            \
        int cz = ((iv & 1) == bz) ? iv : iv + 1;                                                             \
        float wz = (cz == iv) ? (1.0f - fv) : fv;                                                            \
        int row = (cu >> 1) - ulo;                                                                           \
        bool o = sok && cu >= 0 && cu < NU && cz >= 0 && cz < NZ && row >= 0 && row < nrw;                   \
        int sa = base + row * HZ + (cz >> 1);                                                                \
        bool vhere = vmine && vset == s && vb == b;                                                          \
        int a = clr ? it.jb : (vhere ? va : (o ? sa : 0));                                                   \
        float m = MEM[a][s * 4 + b];                                                                         \
        float w = o ? wu * wz * tw : 0.0f;                                                                   \
        val += (sf ? w : 0.0f) * m;                                                                          \
        rv += (vhere && kind == K_READ) ? m : 0.0f;                                                          \
        bool wr = (sb && o) || clr || vhere;                                                                 \
        float nv = sb ? m + it.t.s * w : ((vhere && kind == K_LOAD) ? it.t.s : 0.0f);                        \
        if (wr) MEM[a][s * 4 + b] = nv;                                                                      \
      }                                                                                                      \
    }                                                                                                        \
    F = (rst ? 0.0f : F) + val;                                                                              \
    bool emitF = (f & F_LAST) != 0, emit0 = (f & F_EMIT0) != 0;                                              \
    if (tokf) {                                                                                              \
      Tok fw = it.t;                                                                                         \
      if (kind == K_SETID) { myid = fw.u0; fw.u0 = fw.u0 + 1; }                                              \
      if (kind == K_SETUP && fw.u0 == myid) {                                                                \
        int sc = fw.v0 & 1, st_ = (fw.du >= 0 && fw.du < TMAX) ? fw.du : 0;                                  \
        TB_BASE[sc][st_] = fw.dv; TB_ULO[sc][st_] = (int)fw.d0; TB_NROW[sc][st_] = (int)fw.dd;               \
      }                                                                                                      \
      out.write(fw);                                                                                         \
    }                                                                                                        \
    bool emitR = tokf && kind == K_READ;                                                                     \
    if (emitF || emit0 || emitR) fl.write(emitF ? F : (emitR ? rv : 0.0f));                                  \
    rst = emitF;                                                                                             \
  }

static inline Tok ev2tok(const Ev &e, int ph, float s) {
  Tok t;
  t.i0 = e.i0; t.na = e.na; t.u0 = e.u0; t.v0 = e.v0; t.du = e.du; t.dv = e.dv; t.d0 = e.d0; t.dd = e.dd; t.s = s;
  t.kind = (e.i0 == -1000) ? K_NOP : (ph ? K_BACK : K_FWD);
  t.pl = e.p0; t.tl = e.t0; t.cl = e.c0; t.gl = e.g0;
  return t;
}
static inline Tok ctok(int kind, int u0, int v0, int du, int dv, float d0, float dd, float s, int copy) {
  Tok t;
  t.i0 = 0; t.na = (short)(copy << 15); t.u0 = u0; t.v0 = v0; t.du = du; t.dv = dv; t.d0 = d0; t.dd = dd; t.s = s;
  t.kind = kind; t.pl = 0; t.tl = 0; t.cl = 0; t.gl = 0;
  return t;
}
static inline PTok ev2ptok(const Ev &e, int idx, float f0) { PTok q; q.F = f0; q.mw = e.mw; q.y = e.y; q.a = e.a; q.idx = idx; return q; }
static inline float ratio(const PTok &r) { float yh = r.mw * r.F + r.a; return (yh > 0.0f) ? r.mw * r.y / yh : 0.0f; }

#ifndef SWSIM
// ================================================================= hardware components
hls_always_run_component component void slab_exp(ihc::stream_in<Tok, ihc::buffer<TOKBUF>> &in, ihc::stream_out<Item> &wq) {
  Tok c;
  c.i0 = 0; c.na = 0; c.u0 = 0; c.v0 = 0; c.du = 0; c.dv = 0; c.d0 = 0.0f; c.dd = 0.0f; c.s = 0.0f; c.kind = K_NOP; c.pl = 0; c.tl = 0;
  c.cl = 0; c.gl = 0;
  int jb = 0, id = 0, rem = 0;
  while (1) EXP_BODY
}

hls_always_run_component component void slab_eng(ihc::stream_in<Item, ihc::buffer<64>> &wq, ihc::stream_out<Tok> &out,
                                                  ihc::stream_out<float> &fl) {
  hls_numbanks(SETS * 4) hls_bankwidth(4) hls_singlepump hls_force_pow2_depth(0) static float MEM[DEPTH][SETS * 4];
  hls_numbanks(SETS) hls_bankwidth(4) hls_singlepump static float TT0[TOFN][SETS];
  hls_numbanks(SETS) hls_bankwidth(4) hls_singlepump static float TT1[TOFN][SETS];
  hls_register int TB_BASE[2][TMAX], TB_ULO[2][TMAX], TB_NROW[2][TMAX];
#pragma unroll
  for (int c = 0; c < 2; c++)
#pragma unroll
    for (int t = 0; t < TMAX; t++) { TB_BASE[c][t] = 0; TB_ULO[c][t] = 0; TB_NROW[c][t] = 0; }
  float F = 0.0f;
  bool rst = true;
  int myid = 0;
#pragma ivdep
  while (1) ENG_BODY
}

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
    hls_avalon_slave_memory_argument(MAXEV * sizeof(Ev)) Ev *ev,
    hls_avalon_slave_memory_argument(MAXEV * sizeof(float)) float *s_in,
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    hls_avalon_slave_memory_argument(NROWTAB * sizeof(RowEnt)) RowEnt *rowt,
    ihc::stream_out<Tok> &tout, ihc::stream_out<PTok> &pout,
    hls_avalon_slave_register_argument int mode, hls_avalon_slave_register_argument int nev,
    hls_avalon_slave_register_argument int off, hls_avalon_slave_register_argument int cnt,
    hls_avalon_slave_register_argument int rep, hls_avalon_slave_register_argument int finit,
    hls_avalon_slave_register_argument int rstart, hls_avalon_slave_register_argument int ustart,
    hls_avalon_slave_register_argument int zstart) {
  if (mode == 4 || mode == 10) {
    tout.write(ctok(mode == 4 ? K_SETID : K_CLEAR, 0, 0, 0, 0, 0.0f, 0.0f, 0.0f, 0));
    return;
  }
  if (mode == 7) {      // SETUP: io = [lane, copy, t, base, ulo, nrow] per entry
    for (int i = 0; i < cnt; i++)
      tout.write(ctok(K_SETUP, (int)io[6 * i], (int)io[6 * i + 1], (int)io[6 * i + 2], (int)io[6 * i + 3], io[6 * i + 4],
                      io[6 * i + 5], 0.0f, 0));
    return;
  }
  if (mode == 9) {      // TOFTAB: io = [k(i), k(i+1)] per entry, entries off .. off + cnt
    for (int i = 0; i < cnt; i++) tout.write(ctok(K_TOFTAB, off + i, 0, 0, 0, io[2 * i], io[2 * i + 1], 0.0f, 0));
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
  int ph = (mode == 6) ? 1 : 0;
  for (int rr = 0; rr < rep; rr++) {
    for (int i = 0; i < nev; i++) {
      Ev e = ev[i];
      float s = s_in[i];
      tout.write(ev2tok(e, ph, s));
      if (ph == 0 && e.i0 != -1000) pout.write(ev2ptok(e, i, finit ? s : 0.0f));
    }
  }
}

hls_avalon_slave_component component void slab_sink(
    hls_avalon_slave_memory_argument(MAXEV * sizeof(float)) float *s_out,
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    ihc::stream_in<Tok> &tin, ihc::stream_in<PTok> &pin,
    hls_avalon_slave_register_argument int nm, hls_avalon_slave_register_argument int nq,
    hls_avalon_slave_register_argument int raw) {
  int mi = 0, qi = 0;
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
      if (ok) { if (raw == 2) io[p.idx & (IOCHUNK - 1)] = p.F; else s_out[p.idx & (MAXEV - 1)] = raw ? p.F : ratio(p); qi++; }
    }
  }
}

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
  int TB_BASE[2][TMAX], TB_ULO[2][TMAX], TB_NROW[2][TMAX];
  Tok c;
  int jb, id, myid, rem;
  bool rst;
  float F;
  long items;
};
static void lane_run(LaneMem &M, SQ<Tok> &in, SQ<Tok> &out, SQ<float> &fl) {
  SQ<Item> wq;
  {
    Tok &c = M.c; int &jb = M.jb, &id = M.id, &rem = M.rem;
    while (rem > 0 || !in.empty()) EXP_BODY
  }
  float(*MEM)[SETS * 4] = M.MEM;
  float(*TT0)[SETS] = M.TT0; float(*TT1)[SETS] = M.TT1;
  int(*TB_BASE)[TMAX] = M.TB_BASE; int(*TB_ULO)[TMAX] = M.TB_ULO; int(*TB_NROW)[TMAX] = M.TB_NROW;
  float &F = M.F; bool &rst = M.rst; int &myid = M.myid;
  while (!wq.empty()) { M.items++; ENG_BODY }
}
static LaneMem *LM[LANES];
static void chain(SQ<Tok> &t0, SQ<PTok> &p0, SQ<Tok> &tN, SQ<PTok> &pN, long *items) {
  SQ<Tok> a = t0; SQ<PTok> pa = p0;
  for (int L = 0; L < LANES; L++) {
    SQ<Tok> b; SQ<float> fl; SQ<PTok> pb;
    long i0 = LM[L]->items;
    lane_run(*LM[L], a, b, fl);
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
  static int base[LANES][2][TMAX];
  long dmax = 0;
  for (int L = 0; L < LANES; L++)
    for (int s = 0; s < SETS; s++) {
      long acc = 0;
      for (int c = 0; c < 2; c++)
        for (int t = s; t < TMAX; t += SETS) {
          int p = L + LANES * t;
          if (p >= NPL) continue;
          base[L][c][t] = (int)acc;
          acc += (long)nrow[c][p] * HZ;
        }
      dmax = std::max(dmax, acc);
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
  raw.push_back(ctok(K_SETID, 0, 0, 0, 0, 0, 0, 0, 0));
  for (int L = 0; L < LANES; L++)
    for (int c = 0; c < 2; c++)
      for (int t = 0; t < TMAX; t++) {
        int p = L + LANES * t;
        int b = (p < NPL) ? base[L][c][t] : 0, u = (p < NPL) ? ulo[c][p] : 0, nr = (p < NPL) ? nrow[c][p] : 0;
        raw.push_back(ctok(K_SETUP, L, c, t, b, (float)u, (float)nr, 0, 0));
      }
  const double W = 5 * 89 * 0.299792458 / 2, SIG = 0.5 * 550.0 * 0.299792458 / 2.354820045;
  auto kern = [&](double d) { return 0.5 * (erf((d + W / 2) / (sqrt(2.0) * SIG)) - erf((d - W / 2) / (sqrt(2.0) * SIG))); };
  for (int i = 0; i < TOFN; i++)
    raw.push_back(ctok(K_TOFTAB, i, 0, 0, 0, (float)kern(TOFHALF * i / TOFN), (float)kern(TOFHALF * (i + 1) / TOFN), 0, 0));
  snprintf(fn, sizeof fn, "%s/hw7/raw_setup.bin", dir); writef(fn, raw);
  {
    std::vector<float> su, tt;
    for (auto &r : raw) {
      if (r.kind == K_SETUP) { float v[6] = {(float)r.u0, (float)r.v0, (float)r.du, (float)r.dv, r.d0, r.dd}; su.insert(su.end(), v, v + 6); }
      if (r.kind == K_TOFTAB) { tt.push_back(r.d0); tt.push_back(r.dd); }
    }
    snprintf(fn, sizeof fn, "%s/hw7/setup_io.bin", dir); writef(fn, su);
    snprintf(fn, sizeof fn, "%s/hw7/toftab_io.bin", dir); writef(fn, tt);
  }
  std::vector<Tok> rclr(1, ctok(K_CLEAR, 0, 0, 0, 0, 0, 0, 0, 0));
  snprintf(fn, sizeof fn, "%s/hw7/raw_clear.bin", dir); writef(fn, rclr);
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
  snprintf(fn, sizeof fn, "%s/hw7/rowt.bin", dir); writef(fn, rt);
  snprintf(fn, sizeof fn, "%s/hw7/img_sweep.bin", dir); writef(fn, sweepv);
  {   // chunk starts (row entry, u, z) for chunks of IOCHUNK voxels
    snprintf(fn, sizeof fn, "%s/hw7/chunks.txt", dir); FILE *f = fopen(fn, "w");
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
  snprintf(fn, sizeof fn, "%s/hw7/ev7.bin", dir); writef(fn, sch);
  // ---- run the model on the scheduled tokens: setup, load (sweep), forward, clear, back, read (sweep)
  for (int L = 0; L < LANES; L++) { LM[L] = (LaneMem *)calloc(1, sizeof(LaneMem)); LM[L]->rst = true; LM[L]->c.kind = K_NOP; }
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
  snprintf(fn, sizeof fn, "%s/hw7/expect_s.bin", dir); writef(fn, s);
  snprintf(fn, sizeof fn, "%s/hw7/sw_back.bin", dir); writef(fn, back);
  snprintf(fn, sizeof fn, "%s/hw7/sw_F.bin", dir); writef(fn, Fhw);
  snprintf(fn, sizeof fn, "%s/hw7/expect_read.bin", dir); writef(fn, rd);
  snprintf(fn, sizeof fn, "%s/hw7/sweep_pos.bin", dir); writef(fn, sweeppos);
  snprintf(fn, sizeof fn, "%s/hw7/meta.txt", dir); FILE *mf = fopen(fn, "w");
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
  return 0;
}
#endif
