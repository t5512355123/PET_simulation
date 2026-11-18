// Slab-partitioned list-mode projector, v5 (EXP-S15): v4 + parallel slab load / accumulator readout over a
// 512-bit "wide chain" from DDR4 (loader -> 32 lanes -> storer). Hardware only; the event path is unchanged
// from slab4.cpp, whose software model and expected outputs are reused.
// v4 notes:: real PETRIC2 Esser2 geometry (95 x 163 x 163, fp32).
// Changes from EXP-S12 (slab.cpp):
//  * one main-axis copy per pass; each main axis is split into two halves of NPP planes -> 4 passes
//    (x-major events with x planes 0..81, x 82..162, then y-major events) so the real image fits in M20K;
//  * slabs need not be equal: lane id owns planes [id*NPP/LANES, (id+1)*NPP/LANES) of the pass;
//  * the token iteration also does the first local step (a token costs max(1, local steps) lane iterations);
//  * forward partial sums of the first half are fed back as the start value of the second half (src finit),
//    the sink returns raw sums (raw = 1) or the ratio s = mw*y/(mw*F + a) (raw = 0).
//   chain 1 (Tok):  src -> N x (exp -> eng) -> sink ; chain 2 (PTok): src -> N x padd -> sink ; eng k -> padd k
#ifndef SWSIM
#include "HLS/hls.h"
#endif
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vector>
#include <deque>

#define NPL 163           // planes along x (= y)
#define NU 163            // transverse size (= the other transaxial axis)
#define NZ 95             // axial size
#define NPP 82            // planes per pass (half of the main axis)
#ifndef LANES
#define LANES 32
#endif
#if LANES == 32
#define LOGL 5
#elif LANES == 8
#define LOGL 3
#endif
#define SPMAX ((NPP + LANES - 1) / LANES)   // planes per lane at most
#define HU ((NU + 1) / 2)
#define HZ ((NZ + 1) / 2)
#define SLABSZ (SPMAX * HU * HZ)            // entries per bank
#define FRAC 20
#ifndef MAXEV
#define MAXEV 16384
#endif
#ifndef IOCHUNK
#define IOCHUNK 16384
#endif
#ifndef TOKBUF
#define TOKBUF 256
#endif

enum { K_FWD = 0, K_BACK = 1, K_LOAD = 2, K_READ = 3, K_SETID = 4, K_NOP = 5 };

struct Ev {               // 32 B, host memory format (i0 == -1000: NOP for lane u0, n_axis = bubbles)
  short i0;               // first plane, relative to the pass (may be < 0)
  short n_axis;           // bits 0..14: steps (bit 15 unused: one axis per pass)
  int u0, v0, du, dv;     // fixed point FRAC
  float mw, y, a;
};
struct Tok {              // 32 B, chain 1
  short i0;
  short n_axis;
  int u0, v0, du, dv;
  float s;
  int kind;
  short ks, rem;          // first local step and local step count for the lane that receives this token
};
struct PTok { float F, mw, y, a; int idx; };
#define F_TOK 1
#define F_LD 2
#define F_RD 4
#define F_SF 8
#define F_SB 16
#define F_LAST 32
#define F_EMIT0 64
// wide chain word: 16 voxels = 4 groups of 2x2 (u, z); a lane writes / reads one group (4 banks, one address) per iteration
#define W_LOAD 1
#define W_READ 2
#define W_SETID 3
struct Grp { float v[4]; int addr; int op; };   // one 2x2 group for the engine
struct GRes { float v[4]; };                    // accumulator group read back
struct WW {
  float v[4][4];     // [group][bank]
  int hdr;           // bits 0-5 lane, 6-7 op, 8-31 slot (bank addresses 4*slot .. 4*slot+3)
};
struct D512 { float v[16]; };
#define SLOTS(np) (((np) * HU * HZ) / 4)
struct Item {
  Tok t;
  int u, v;
  short pl;
  unsigned char fl;
  unsigned char pad;
};

static inline int slab_lo(int id) { return (id * NPP) >> LOGL; }
// local step range of token t in the lane [lo, hi) with id
static inline void annot(Tok &t, int lo, int hi, int id) {
  int n = t.n_axis & 0x7fff;
  int ks = lo - t.i0, ke = hi - t.i0;
  ks = ks < 0 ? 0 : ks;
  ke = ke > n ? n : ke;
  bool isev = t.kind == K_FWD || t.kind == K_BACK;
  bool isnop = t.kind == K_NOP && t.u0 == id;
  if (isnop) { ks = 0; ke = n; }
  bool has = (isev || isnop) && ke > ks;
  t.ks = (short)(has ? ks : 0);
  t.rem = (short)(has ? ke - ks : 0);
}

// ---------------------------------------------------------------- exp: one item per iteration
// state: c (current event), k (next step), rem (steps left), id, lo, hi, hn (= hi of the next lane)
#define EXP_BODY                                                                                             \
  {                                                                                                          \
    bool tokit = rem == 0;                                                                                   \
    Tok t;                                                                                                   \
    if (tokit) t = in.read(); else t = c;                                                                    \
    int kind = t.kind;                                                                                       \
    int kk = tokit ? (int)t.ks : k;                                                                          \
    int remnow = tokit ? (int)t.rem : rem;                                                                   \
    bool stepnow = remnow > 0;                                                                               \
    bool mine = t.i0 >= lo && t.i0 < hi;                                                                     \
    Item it;                                                                                                 \
    it.t = t;                                                                                                \
    it.pad = 0;                                                                                              \
    unsigned char f = 0;                                                                                     \
    if (tokit) {                                                                                             \
      annot(it.t, hi, hn, id + 1);                                                                           \
      f |= F_TOK;                                                                                            \
      if (kind == K_LOAD && mine) f |= F_LD;                                                                 \
      if (kind == K_READ && mine) f |= F_RD;                                                                 \
      if (kind == K_FWD && !stepnow) f |= F_EMIT0;                                                           \
    }                                                                                                        \
    if (stepnow) {                                                                                           \
      if (kind == K_FWD) f |= F_SF;                                                                          \
      if (kind == K_BACK) f |= F_SB;                                                                         \
      if (kind == K_FWD && remnow == 1) f |= F_LAST;                                                         \
      it.u = t.u0 + kk * t.du;                                                                               \
      it.v = t.v0 + kk * t.dv;                                                                               \
      it.pl = (short)((kind == K_NOP) ? 0 : t.i0 + kk - lo);                                                 \
    } else {                                                                                                 \
      it.u = t.u0;                                                                                           \
      it.v = t.v0;                                                                                           \
      it.pl = (short)(mine ? t.i0 - lo : 0);                                                                 \
    }                                                                                                        \
    it.fl = f;                                                                                               \
    wq.write(it);                                                                                            \
    if (tokit && kind == K_SETID) {                                                                          \
      id = t.u0; lo = slab_lo(t.u0); hi = slab_lo(t.u0 + 1); hn = slab_lo(t.u0 + 2);                         \
    }                                                                                                        \
    c = t;                                                                                                   \
    k = kk + 1;                                                                                              \
    rem = stepnow ? remnow - 1 : 0;                                                                          \
  }

// ---------------------------------------------------------------- eng: memory + forwarding (state F, rst)
// One iteration = one event item (priority) or one 2x2 group from the lane's wide port (load into IMG, or read+clear ACC).
#define ENG_BODY                                                                                             \
  {                                                                                                          \
    bool oki = false, okg = false;                                                                           \
    Item it = wq.tryRead(oki);                                                                               \
    Grp q;                                                                                                   \
    q.addr = 0; q.op = 0;                                                                                    \
    _Pragma("unroll") for (int b = 0; b < 4; b++) q.v[b] = 0.0f;                                             \
    if (!oki) q = gq.tryRead(okg);                                                                           \
    int gop = okg ? q.op : 0;                                                                                \
    bool gl = gop == W_LOAD, gr = gop == W_READ;                                                             \
    unsigned f = oki ? it.fl : 0;                                                                            \
    bool sf = f & F_SF, sb = f & F_SB, ld = f & F_LD, rd = f & F_RD;                                         \
    bool st = sf || sb;                                                                                      \
    int pl = it.pl;                                                                                          \
    int iu = it.u >> FRAC, iv = it.v >> FRAC;                                                                \
    float fu = (float)(it.u & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));                                     \
    float fv = (float)(it.v & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));                                     \
    int tu = it.u, tz = it.v;                                                                                \
    int tb = (tu & 1) | ((tz & 1) << 1);                                                                     \
    int ta = okg ? q.addr : ((ld || rd) ? (pl * HU + (tu >> 1)) * HZ + (tz >> 1) : 0);                       \
    int a[4];                                                                                                \
    float w[4];                                                                                              \
    bool okb[4];                                                                                             \
    _Pragma("unroll") for (int b = 0; b < 4; b++) {                                                          \
      int bu = b & 1, bz = b >> 1;                                                                           \
      int cu = ((iu & 1) == bu) ? iu : iu + 1;                                                               \
      float wu = (cu == iu) ? (1.0f - fu) : fu;                                                              \
      int cz = ((iv & 1) == bz) ? iv : iv + 1;                                                               \
      float wz = (cz == iv) ? (1.0f - fv) : fv;                                                              \
      bool o = st && cu >= 0 && cu < NU && cz >= 0 && cz < NZ;                                               \
      int cuc = o ? cu : bu, czc = o ? cz : bz;                                                              \
      int sa = (pl * HU + (cuc >> 1)) * HZ + (czc >> 1);                                                     \
      a[b] = st ? sa : ta;                                                                                   \
      w[b] = o ? wu * wz : 0.0f;                                                                             \
      okb[b] = o;                                                                                            \
    }                                                                                                        \
    float val = 0.0f, rv = 0.0f;                                                                             \
    GRes res;                                                                                                \
    _Pragma("unroll") for (int b = 0; b < 4; b++) {                                                          \
      float iv_ = IMG[a[b]][b];                                                                              \
      if ((ld && b == tb) || gl) IMG[a[b]][b] = gl ? q.v[b] : it.t.s;                                        \
      float av = ACC[a[b]][b];                                                                               \
      bool wr = (sb && okb[b]) || (rd && b == tb) || gr;                                                     \
      if (wr) ACC[a[b]][b] = sb ? av + it.t.s * w[b] : 0.0f;                                                 \
      val += (sf ? w[b] : 0.0f) * iv_;                                                                       \
      rv += (b == tb) ? av : 0.0f;                                                                           \
      res.v[b] = av;                                                                                         \
    }                                                                                                        \
    if (gr) rq.write(res);                                                                                   \
    F = (rst ? 0.0f : F) + val;                                                                              \
    if (oki) {                                                                                               \
      bool emitF = (f & F_LAST) != 0, emit0 = (f & F_EMIT0) != 0;                                            \
      if (f & F_TOK) {                                                                                       \
        Tok fw = it.t;                                                                                       \
        if (fw.kind == K_SETID) fw.u0 = fw.u0 + 1;                                                           \
        if (rd) fw.s = rv;                                                                                   \
        out.write(fw);                                                                                       \
      }                                                                                                      \
      if (emitF || emit0) fl.write(emitF ? F : 0.0f);                                                        \
    }                                                                                                        \
    rst = oki ? ((f & F_LAST) != 0) : rst;                                                                   \
  }

static inline Tok ev2tok(const Ev &e, int ph, float s) {
  Tok t;
  t.i0 = e.i0; t.n_axis = e.n_axis; t.u0 = e.u0; t.v0 = e.v0; t.du = e.du; t.dv = e.dv; t.s = s;
  t.kind = (e.i0 == -1000) ? K_NOP : (ph ? K_BACK : K_FWD);
  annot(t, 0, slab_lo(1), 0);
  return t;
}
static inline Tok vtok(int p, int u, int z, int kind, float s) {
  Tok t;
  t.i0 = (short)p; t.n_axis = 0; t.u0 = u; t.v0 = z; t.du = 0; t.dv = 0; t.s = s; t.kind = kind; t.ks = 0; t.rem = 0;
  return t;
}
static inline PTok ev2ptok(const Ev &e, int idx, float f0) {
  PTok q;
  q.F = f0; q.mw = e.mw; q.y = e.y; q.a = e.a; q.idx = idx;
  return q;
}
static inline float ratio(const PTok &r) {
  float yh = r.mw * r.F + r.a;
  return (yh > 0.0f) ? r.mw * r.y / yh : 0.0f;
}

#ifndef SWSIM
// ================================================================= hardware components
hls_always_run_component component void slab_exp(ihc::stream_in<Tok, ihc::buffer<TOKBUF>> &in, ihc::stream_out<Item> &wq) {
  Tok c;
  c.i0 = 0; c.n_axis = 0; c.u0 = 0; c.v0 = 0; c.du = 0; c.dv = 0; c.s = 0.0f; c.kind = K_NOP; c.ks = 0; c.rem = 0;
  int k = 0, rem = 0, id = 0, lo = 0, hi = slab_lo(1), hn = slab_lo(2);
  while (1) EXP_BODY
}

hls_always_run_component component void slab_eng(ihc::stream_in<Item, ihc::buffer<64>> &wq, ihc::stream_out<Tok> &out,
                                                  ihc::stream_out<float> &fl, ihc::stream_in<Grp, ihc::buffer<8>> &gq,
                                                  ihc::stream_out<GRes> &rq) {
  hls_numbanks(4) hls_bankwidth(4) hls_singlepump static float IMG[SLABSZ][4];
  hls_numbanks(4) hls_bankwidth(4) hls_singlepump static float ACC[SLABSZ][4];
  float F = 0.0f;
  bool rst = true;
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

// mode 0: LOAD io[0..cnt) -> pass voxels off..off+cnt (flat (p*NU + u)*NZ + z); 3: READ (and clear) them; 4: SETID
// mode 5: rep x forward pass (PTok start value = finit ? s_in[i] : 0); 6: rep x back pass (s = s_in[i])
hls_avalon_slave_component component void slab_src(
    hls_avalon_slave_memory_argument(MAXEV * sizeof(Ev)) Ev *ev,
    hls_avalon_slave_memory_argument(MAXEV * sizeof(float)) float *s_in,
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    ihc::stream_out<Tok> &tout, ihc::stream_out<PTok> &pout,
    hls_avalon_slave_register_argument int mode, hls_avalon_slave_register_argument int nev,
    hls_avalon_slave_register_argument int off, hls_avalon_slave_register_argument int cnt,
    hls_avalon_slave_register_argument int rep, hls_avalon_slave_register_argument int finit) {
  if (mode == 4) {
    tout.write(vtok(0, 0, 0, K_SETID, 0.0f));
    return;
  }
  if (mode == 0 || mode == 3) {
    int p = off / (NU * NZ), r = off - p * (NU * NZ);
    int u = r / NZ, z = r - u * NZ;
    for (int i = 0; i < cnt; i++) {
      float v = io[i];
      tout.write(vtok(p, u, z, mode == 0 ? K_LOAD : K_READ, mode == 0 ? v : 0.0f));
      bool zw = z == NZ - 1, uw = u == NU - 1;
      z = zw ? 0 : z + 1;
      u = zw ? (uw ? 0 : u + 1) : u;
      p = (zw && uw) ? p + 1 : p;
    }
    return;
  }
  int ph = (mode == 6) ? 1 : 0;
  for (int r = 0; r < rep; r++) {
    for (int i = 0; i < nev; i++) {
      Ev e = ev[i];
      float s = s_in[i];
      tout.write(ev2tok(e, ph, s));
      if (ph == 0 && e.i0 != -1000) pout.write(ev2ptok(e, i, finit ? s : 0.0f));
    }
  }
}

// sink: consume nm chain-1 tokens (token s -> io, ring) and nq chain-2 sums (raw F or ratio -> s_out[idx])
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
      if (ok) { s_out[p.idx & (MAXEV - 1)] = raw ? p.F : ratio(p); qi++; }
    }
  }
}

// ---- wide chain: loader (DDR -> lanes, read requests, or lane ids), per-lane wide port, storer (lanes -> DDR),
//      DMA (on-chip io <-> DDR for the host)
// word order (= DDR order): phase A: slot s in [0, SLOTS(2)), lane 0..LANES-1;
//                           phase B: slot s in [SLOTS(2), SLOTS(3)), lanes with 3 planes in increasing order
#define DDRHOST                                                                                              \
  ihc::mm_master<D512, ihc::aspace<1>, ihc::awidth<34>, ihc::dwidth<512>, ihc::latency<0>, ihc::maxburst<64>, \
                 ihc::waitrequest<true>>
static inline int lane_np(int L) { return slab_lo(L + 1) - slab_lo(L); }

// wide port of one lane: words for other lanes pass in one iteration; a word for this lane is split into 4 groups for
// the engine (LOAD) or 4 groups are read back (READ); every word is forwarded so the storer can count completion.
hls_always_run_component component void slab_wp(ihc::stream_in<WW, ihc::buffer<8>> &lin, ihc::stream_out<WW> &lout,
                                                 ihc::stream_out<Grp> &gq, ihc::stream_in<GRes, ihc::buffer<8>> &rq) {
  int myid = 0, ph = 0, g = 0;
  hls_register float cv[4][4];
  int ch = 0;
#pragma unroll
  for (int i = 0; i < 4; i++)
#pragma unroll
    for (int b = 0; b < 4; b++) cv[i][b] = 0.0f;
  while (1) {
    if (ph == 0) {
      WW w = lin.read();
      int op = (w.hdr >> 6) & 3;
      bool own = op != 0 && (w.hdr & 63) == myid;
      if (op == W_SETID) { myid = w.hdr & 63; w.hdr = (w.hdr & ~63) | ((myid + 1) & 63); }
      if (own) {
        ch = w.hdr;
#pragma unroll
        for (int i = 0; i < 4; i++)
#pragma unroll
          for (int b = 0; b < 4; b++) cv[i][b] = w.v[i][b];
        ph = 1;
        g = 0;
      } else {
        lout.write(w);
      }
    } else if (ph == 1) {
      Grp q;
#pragma unroll
      for (int b = 0; b < 4; b++) {
        float x = cv[0][b];
#pragma unroll
        for (int i = 1; i < 4; i++) x = (g == i) ? cv[i][b] : x;
        q.v[b] = x;
      }
      q.addr = (ch >> 8) * 4 + g;
      q.op = (ch >> 6) & 3;
      gq.write(q);
      bool last = g == 3;
      g = last ? 0 : g + 1;
      ph = last ? (q.op == W_READ ? 2 : 3) : 1;
    } else if (ph == 2) {
      GRes r = rq.read();
#pragma unroll
      for (int i = 0; i < 4; i++)
#pragma unroll
        for (int b = 0; b < 4; b++) cv[i][b] = (g == i) ? r.v[b] : cv[i][b];
      bool last = g == 3;
      g = last ? 0 : g + 1;
      ph = last ? 3 : 2;
    } else {
      WW w;
#pragma unroll
      for (int i = 0; i < 4; i++)
#pragma unroll
        for (int b = 0; b < 4; b++) w.v[i][b] = cv[i][b];
      w.hdr = ch;
      lout.write(w);
      ph = 0;
    }
  }
}

// op W_LOAD: stream the pass image from DDR word base..; W_READ: read requests (no data); W_SETID: one id word
hls_avalon_slave_component component int slab_ld(hls_avalon_slave_register_argument DDRHOST &m, ihc::stream_out<WW> &lout,
                                                  hls_avalon_slave_register_argument int op,
                                                  hls_avalon_slave_register_argument int base,
                                                  hls_avalon_slave_register_argument int rep) {
  if (op == W_SETID) {
    WW w;
#pragma unroll
    for (int i = 0; i < 4; i++)
#pragma unroll
      for (int b = 0; b < 4; b++) w.v[i][b] = 0.0f;
    w.hdr = W_SETID << 6;
    lout.write(w);
    return 1;
  }
  int n3 = 0;
  int l3[LANES];
  for (int L = 0; L < LANES; L++) l3[L] = 0;
  for (int L = 0; L < LANES; L++)
    if (lane_np(L) == 3) l3[n3++] = L;
  const int SA = SLOTS(2), SB = SLOTS(3) - SLOTS(2);
  int nw = SA * LANES + SB * n3;
  for (int r = 0; r < rep; r++) {
    int ja = 0, sa = 0, jb = 0, sb = SA;
    for (int i = 0; i < nw; i++) {
      bool ph = i >= SA * LANES;
      int L = ph ? l3[jb] : ja;
      int s = ph ? sb : sa;
      D512 d;
#pragma unroll
      for (int k = 0; k < 16; k++) d.v[k] = 0.0f;
      if (op == W_LOAD) d = m[base + i];
      WW w;
#pragma unroll
      for (int g = 0; g < 4; g++)
#pragma unroll
        for (int b = 0; b < 4; b++) w.v[g][b] = d.v[4 * g + b];
      w.hdr = L | (op << 6) | (s << 8);
      lout.write(w);
      if (!ph) { bool wrap = ja == LANES - 1; ja = wrap ? 0 : ja + 1; sa = wrap ? sa + 1 : sa; }
      else { bool wrap = jb == n3 - 1; jb = wrap ? 0 : jb + 1; sb = wrap ? sb + 1 : sb; }
    }
  }
  return nw;
}

// consume n words; READ words are written to DDR word base + (loader order index of (lane, slot))
hls_avalon_slave_component component int slab_st(hls_avalon_slave_register_argument DDRHOST &m, ihc::stream_in<WW> &lin,
                                                  hls_avalon_slave_register_argument int n,
                                                  hls_avalon_slave_register_argument int base) {
  int p3[LANES];
  int n3 = 0;
  for (int L = 0; L < LANES; L++) p3[L] = 0;
  for (int L = 0; L < LANES; L++)
    if (lane_np(L) == 3) p3[L] = n3++;
  const int SA = SLOTS(2);
  int nr = 0;
  for (int i = 0; i < n; i++) {
    WW w = lin.read();
    int L = w.hdr & 63, s = w.hdr >> 8;
    int idx = (s < SA) ? s * LANES + L : SA * LANES + (s - SA) * n3 + p3[L];
    D512 d;
#pragma unroll
    for (int g = 0; g < 4; g++)
#pragma unroll
      for (int b = 0; b < 4; b++) d.v[4 * g + b] = w.v[g][b];
    bool wr = ((w.hdr >> 6) & 3) == W_READ;
    if (wr) m[base + idx] = d;
    nr += wr ? 1 : 0;
  }
  return nr;
}

#define IOW 1024
hls_avalon_slave_component component void slab_dma(hls_avalon_slave_register_argument DDRHOST &m,
                                                    hls_avalon_slave_memory_argument(IOW * sizeof(D512)) D512 *io,
                                                    hls_avalon_slave_register_argument int dir,
                                                    hls_avalon_slave_register_argument int base,
                                                    hls_avalon_slave_register_argument int n) {
  if (dir == 0) {
    for (int i = 0; i < n; i++) m[base + i] = io[i];
  } else {
    for (int i = 0; i < n; i++) io[i] = m[base + i];
  }
}

int main() { return 0; }   // hardware build only (event path model: slab4.cpp -DSWSIM)

#endif
