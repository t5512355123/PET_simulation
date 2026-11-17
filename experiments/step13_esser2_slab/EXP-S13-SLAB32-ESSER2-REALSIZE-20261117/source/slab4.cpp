// Slab-partitioned list-mode projector, v4 (EXP-S13): real PETRIC2 Esser2 geometry (95 x 163 x 163, fp32).
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
#define ENG_BODY                                                                                             \
  {                                                                                                          \
    Item it = wq.read();                                                                                     \
    unsigned f = it.fl;                                                                                      \
    bool sf = f & F_SF, sb = f & F_SB, ld = f & F_LD, rd = f & F_RD;                                         \
    bool st = sf || sb;                                                                                      \
    int pl = it.pl;                                                                                          \
    int iu = it.u >> FRAC, iv = it.v >> FRAC;                                                                \
    float fu = (float)(it.u & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));                                     \
    float fv = (float)(it.v & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));                                     \
    int tu = it.u, tz = it.v;                                                                                \
    int tb = (tu & 1) | ((tz & 1) << 1);                                                                     \
    int ta = (ld || rd) ? (pl * HU + (tu >> 1)) * HZ + (tz >> 1) : 0;                                  \
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
    _Pragma("unroll") for (int b = 0; b < 4; b++) {                                                          \
      float iv_ = IMG[a[b]][b];                                                                              \
      if (ld && b == tb) IMG[a[b]][b] = it.t.s;                                                              \
      float av = ACC[a[b]][b];                                                                               \
      bool wr = (sb && okb[b]) || (rd && b == tb);                                                           \
      if (wr) ACC[a[b]][b] = sb ? av + it.t.s * w[b] : 0.0f;                                                 \
      val += (sf ? w[b] : 0.0f) * iv_;                                                                       \
      rv += (b == tb) ? av : 0.0f;                                                                           \
    }                                                                                                        \
    F = (rst ? 0.0f : F) + val;                                                                              \
    bool emitF = (f & F_LAST) != 0, emit0 = (f & F_EMIT0) != 0;                                              \
    if (f & F_TOK) {                                                                                         \
      Tok fw = it.t;                                                                                         \
      if (fw.kind == K_SETID) fw.u0 = fw.u0 + 1;                                                             \
      if (rd) fw.s = rv;                                                                                     \
      out.write(fw);                                                                                         \
    }                                                                                                        \
    if (emitF || emit0) fl.write(emitF ? F : 0.0f);                                                          \
    rst = emitF;                                                                                             \
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
                                                  ihc::stream_out<float> &fl) {
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

int main() { return 0; }   // hardware build only; the testbench is the SWSIM build (g++ -DSWSIM)

#else
// ================================================================= software model of the same hardware (g++ -DSWSIM)
template <class T> struct SQ {
  std::deque<T> q;
  T read() { T x = q.front(); q.pop_front(); return x; }
  void write(T x) { q.push_back(x); }
  bool empty() { return q.empty(); }
};
struct LaneMem {
  float IMG[SLABSZ][4];
  float ACC[SLABSZ][4];
  Tok c;
  int k, rem, id, lo, hi, hn;
  float F;
  bool rst;
  long long iters;
};
static void lane_run(LaneMem &M, SQ<Tok> &in, SQ<Tok> &out, SQ<float> &fl) {
  SQ<Item> wq;
  {
    Tok &c = M.c;
    int &k = M.k, &rem = M.rem, &id = M.id, &lo = M.lo, &hi = M.hi, &hn = M.hn;
    while (rem > 0 || !in.empty()) EXP_BODY
  }
  float(*IMG)[4] = M.IMG;
  float(*ACC)[4] = M.ACC;
  float &F = M.F;
  bool &rst = M.rst;
  while (!wq.empty()) {
    M.iters++;
    ENG_BODY
  }
}
static void padd_run(SQ<PTok> &pin, SQ<float> &fl, SQ<PTok> &pout) {
  while (!pin.empty()) { PTok p = pin.read(); p.F += fl.read(); pout.write(p); }
}
static LaneMem *LM[LANES];
static void chain(SQ<Tok> &t0, SQ<PTok> &p0, SQ<Tok> &tN, SQ<PTok> &pN, long long iters[LANES]) {
  SQ<Tok> a = t0;
  SQ<PTok> pa = p0;
  for (int L = 0; L < LANES; L++) {
    SQ<Tok> b;
    SQ<float> fl;
    SQ<PTok> pb;
    long long i0 = LM[L]->iters;
    lane_run(*LM[L], a, b, fl);
    if (iters) iters[L] = LM[L]->iters - i0;
    padd_run(pa, fl, pb);
    if (!fl.empty()) { printf("fl not drained in lane %d\n", L); exit(1); }
    a = b;
    pa = pb;
  }
  tN = a;
  pN = pa;
  t0.q.clear();
  p0.q.clear();
}

// ---------------- helpers
static void lane_range(const Ev &e, int L, int &ks, int &ke) {   // local steps of a pass event in lane L
  int n = e.n_axis & 0x7fff, lo = slab_lo(L), hi = slab_lo(L + 1);
  ks = lo - e.i0; ke = hi - e.i0;
  if (ks < 0) ks = 0;
  if (ke > n) ke = n;
  if (ke < ks) ke = ks;
}
static int hw_vox(int u, int v, int p, int keys[4]) {   // pass voxels touched by one step (key = (p*NU + u)*NZ + z)
  int iu = u >> FRAC, iv = v >> FRAC, n = 0;
  for (int b = 0; b < 4; b++) {
    int bu = b & 1, bz = b >> 1;
    int cu = ((iu & 1) == bu) ? iu : iu + 1;
    int cz = ((iv & 1) == bz) ? iv : iv + 1;
    if (cu >= 0 && cu < NU && cz >= 0 && cz < NZ) keys[n++] = (p * NU + cu) * NZ + cz;
  }
  return n;
}
// order events so that, in every lane, no voxel is written twice within HAZ lane iterations.
// lane time model: a token costs max(1, local steps) iterations, its first local step is in the token iteration.
static std::vector<Ev> schedule(const std::vector<Ev> &in, const std::vector<int> &gin, std::vector<int> &gout, int HAZ,
                                long long tl[LANES], long long &nops, long long &bub) {
  const int WIN = 64;
  std::vector<Ev> out;
  std::vector<long long> last((size_t)NPP * NU * NZ, -(1LL << 40));
  std::vector<int> pend;
  size_t next = 0;
  for (int L = 0; L < LANES; L++) tl[L] = 0;
  nops = bub = 0;
  gout.clear();
  int kv[4];
  auto need = [&](const Ev &e, long long nd[LANES]) {
    long long tot = 0;
    for (int L = 0; L < LANES; L++) {
      nd[L] = 0;
      int ks, ke;
      lane_range(e, L, ks, ke);
      for (int k = ks; k < ke; k++) {
        long long t = tl[L] + (k - ks);
        int nv = hw_vox(e.u0 + k * e.du, e.v0 + k * e.dv, e.i0 + k, kv);
        for (int j = 0; j < nv; j++) {
          long long gap = t - last[kv[j]];
          if (gap < HAZ && HAZ - gap > nd[L]) nd[L] = HAZ - gap;
        }
      }
      tot += nd[L];
    }
    return tot;
  };
  long long nd[LANES], bn[LANES];
  while (next < in.size() || !pend.empty()) {
    while ((int)pend.size() < WIN && next < in.size()) pend.push_back((int)next++);
    int best = -1;
    long long bs = 1LL << 60;
    for (size_t i = 0; i < pend.size(); i++) {
      long long s = need(in[pend[i]], nd);
      if (s < bs) { bs = s; best = (int)i; memcpy(bn, nd, sizeof(bn)); }
      if (s == 0) break;
    }
    const Ev &e = in[pend[best]];
    while (bs > 0) {
      for (int L = 0; L < LANES; L++)
        if (bn[L] > 0) {
          Ev d;
          memset(&d, 0, sizeof(d));
          d.i0 = -1000; d.u0 = L; d.n_axis = (short)bn[L];
          out.push_back(d);
          gout.push_back(-1);
          for (int M = 0; M < LANES; M++) tl[M] += 1;
          tl[L] += bn[L] - 1;
          nops++;
          bub += bn[L];
        }
      bs = need(e, bn);
    }
    for (int L = 0; L < LANES; L++) {
      int ks, ke;
      lane_range(e, L, ks, ke);
      for (int k = ks; k < ke; k++) {
        int nv = hw_vox(e.u0 + k * e.du, e.v0 + k * e.dv, e.i0 + k, kv);
        for (int j = 0; j < nv; j++) last[kv[j]] = tl[L] + (k - ks);
      }
      tl[L] += (ke > ks) ? ke - ks : 1;
    }
    out.push_back(e);
    gout.push_back(gin[pend[best]]);
    pend.erase(pend.begin() + best);
  }
  return out;
}
static long long lane_iters(const std::vector<Ev> &v, long long tl[LANES]) {   // fwd lists (no scheduling)
  long long mx = 0;
  for (int L = 0; L < LANES; L++) {
    tl[L] = 0;
    for (auto &e : v) {
      if (e.i0 == -1000) { tl[L] += (e.u0 == L) ? (e.n_axis & 0x7fff) : 1; continue; }
      int ks, ke;
      lane_range(e, L, ks, ke);
      tl[L] += (ke > ks) ? ke - ks : 1;
    }
    mx = tl[L] > mx ? tl[L] : mx;
  }
  return mx;
}
template <class T> static std::vector<T> readf(const char *fn) {
  FILE *f = fopen(fn, "rb");
  if (!f) { printf("cannot open %s\n", fn); exit(1); }
  fseek(f, 0, SEEK_END);
  long n = ftell(f) / sizeof(T);
  fseek(f, 0, SEEK_SET);
  std::vector<T> v(n);
  if (fread(v.data(), sizeof(T), n, f) != (size_t)n) exit(1);
  fclose(f);
  return v;
}
template <class T> static void writef(const char *fn, const std::vector<T> &v) {
  FILE *f = fopen(fn, "wb");
  fwrite(v.data(), sizeof(T), v.size(), f);
  fclose(f);
}
static void reset_lanes() {
  for (int L = 0; L < LANES; L++) {
    if (!LM[L]) LM[L] = (LaneMem *)calloc(1, sizeof(LaneMem));
    memset(LM[L], 0, sizeof(LaneMem));
    LM[L]->rst = true;
    LM[L]->c.kind = K_NOP;
    LM[L]->hi = slab_lo(1);
    LM[L]->hn = slab_lo(2);
  }
  SQ<Tok> t0, tN;
  SQ<PTok> p0, pN;
  t0.write(vtok(0, 0, 0, K_SETID, 0.0f));
  chain(t0, p0, tN, pN, NULL);
}
static void load_or_read(const std::vector<float> &vals, std::vector<float> *outv, int kind) {
  SQ<Tok> t0, tN;
  SQ<PTok> p0, pN;
  int n = NPP * NU * NZ;
  for (int i = 0; i < n; i++) {
    int p = i / (NU * NZ), r = i % (NU * NZ);
    t0.write(vtok(p, r / NZ, r % NZ, kind, kind == K_LOAD ? vals[i] : 0.0f));
  }
  chain(t0, p0, tN, pN, NULL);
  if (outv) { outv->resize(n); for (int i = 0; i < n; i++) (*outv)[i] = tN.read().s; }
}

// usage: sim <dir with ev_global.bin img.bin s_ref.bin back_ref.bin> <HAZ> ; writes pass files into <dir>/hw
int main(int argc, char **argv) {
  const char *dir = argv[1];
  int HAZ = argc > 2 ? atoi(argv[2]) : 64;
  char fn[1024];
  snprintf(fn, sizeof fn, "%s/ev_global.bin", dir);
  std::vector<Ev> evg = readf<Ev>(fn);
  snprintf(fn, sizeof fn, "%s/img.bin", dir);
  std::vector<float> img = readf<float>(fn);   // (z, y, x)
  snprintf(fn, sizeof fn, "%s/s_ref.bin", dir);
  std::vector<double> s_ref = readf<double>(fn);
  snprintf(fn, sizeof fn, "%s/back_ref.bin", dir);
  std::vector<float> back_ref = readf<float>(fn);
  int NE = (int)evg.size();
  auto IMGV = [&](int x, int y, int z) { return img[((size_t)z * NPL + y) * NPL + x]; };
  long long real_steps = 0;
  for (auto &e : evg) real_steps += e.n_axis & 0x7fff;
  printf("events %d, real steps %lld (%.1f/event), lanes %d, NPP %d, SPMAX %d, SLABSZ %d\n", NE, real_steps,
         (double)real_steps / NE, LANES, NPP, SPMAX, SLABSZ);
  std::vector<float> s_hw(NE, 0.0f), Fhalf(NE, 0.0f);
  std::vector<double> back_hw((size_t)NPL * NPL * NZ, 0.0);
  long long tot_fwd = 0, tot_back = 0;
  FILE *meta;
  snprintf(fn, sizeof fn, "%s/hw/meta.txt", dir);
  meta = fopen(fn, "w");
  if (!meta) { printf("mkdir %s/hw first\n", dir); return 1; }
  fprintf(meta, "events %d\nreal_steps %lld\nlanes %d\nhaz %d\n", NE, real_steps, LANES, HAZ);
  for (int ax = 0; ax < 2; ax++) {
    // pass lists
    std::vector<Ev> fl[2], bl[2];
    std::vector<int> fg[2], bg[2];
    for (int h = 0; h < 2; h++)
      for (int i = 0; i < NE; i++) {
        const Ev &e = evg[i];
        if (((e.n_axis >> 15) & 1) != ax) continue;
        int n = e.n_axis & 0x7fff, a = e.i0, b = e.i0 + n - 1;
        bool touch = b >= h * NPP && a < h * NPP + NPP;
        Ev l = e;
        l.i0 = (short)(e.i0 - h * NPP);
        l.n_axis = (short)n;
        if (touch || h == 1) { fl[h].push_back(l); fg[h].push_back(i); }   // second half: every event (ratio)
        if (touch) { bl[h].push_back(l); bg[h].push_back(i); }
      }
    std::vector<Ev> bs[2];
    std::vector<int> bsg[2];
    for (int h = 0; h < 2; h++) {
      long long tl[LANES], nops, bub;
      bs[h] = schedule(bl[h], bg[h], bsg[h], HAZ, tl, nops, bub);
      long long tf[LANES];
      long long mf = lane_iters(fl[h], tf), mb = 0, sum = 0, sf = 0;
      for (int L = 0; L < LANES; L++) { mb = tl[L] > mb ? tl[L] : mb; sum += tl[L]; sf += tf[L]; }
      int p = ax * 2 + h;
      long long st = 0;
      for (auto &e : bl[h]) { int ks, ke; for (int L = 0; L < LANES; L++) { lane_range(e, L, ks, ke); st += ke - ks; } }
      printf("pass %d (axis %d half %d): fwd %zu tokens, busiest lane %lld (mean %.0f); back %zu tokens (NOP %lld, bubbles %lld), "
             "busiest lane %lld (mean %.0f); steps in pass %lld\n", p, ax, h, fl[h].size(), mf, (double)sf / LANES, bs[h].size(),
             nops, bub, mb, (double)sum / LANES, st);
      fprintf(meta, "pass%d_fwd_tokens %zu\npass%d_fwd_nf %zu\npass%d_fwd_maxlane %lld\npass%d_back_tokens %zu\npass%d_back_maxlane %lld\n"
              "pass%d_steps %lld\n", p, fl[h].size(), p, fl[h].size(), p, mf, p, bs[h].size(), p, mb, p, st);
      tot_fwd += mf;
      tot_back += mb;
      if (fl[h].size() > MAXEV || bs[h].size() > MAXEV) { printf("too many tokens\n"); return 1; }
    }
    // forward: half 0 raw sums, half 1 with start values -> ratio
    for (int h = 0; h < 2; h++) {
      reset_lanes();
      std::vector<float> pimg((size_t)NPP * NU * NZ, 0.0f);
      for (int pl = 0; pl < NPP; pl++) {
        int P = h * NPP + pl;
        if (P >= NPL) continue;
        for (int u = 0; u < NU; u++)
          for (int z = 0; z < NZ; z++) pimg[((size_t)pl * NU + u) * NZ + z] = ax ? IMGV(u, P, z) : IMGV(P, u, z);
      }
      load_or_read(pimg, NULL, K_LOAD);
      SQ<Tok> t0, tN;
      SQ<PTok> p0, pN;
      std::vector<float> finit(fl[h].size(), 0.0f);
      for (size_t i = 0; i < fl[h].size(); i++) {
        if (h == 1) finit[i] = Fhalf[fg[h][i]];
        t0.write(ev2tok(fl[h][i], 0, finit[i]));
        p0.write(ev2ptok(fl[h][i], (int)i, h ? finit[i] : 0.0f));
      }
      chain(t0, p0, tN, pN, NULL);
      std::vector<float> res(fl[h].size());
      while (!pN.empty()) { PTok r = pN.read(); res[r.idx] = h ? ratio(r) : r.F; }
      for (size_t i = 0; i < fl[h].size(); i++) {
        if (h == 0) Fhalf[fg[h][i]] = res[i]; else s_hw[fg[h][i]] = res[i];
      }
      int p = ax * 2 + h;
      snprintf(fn, sizeof fn, "%s/hw/img_p%d.bin", dir, p);       writef(fn, pimg);
      snprintf(fn, sizeof fn, "%s/hw/fwd_p%d.bin", dir, p);       writef(fn, fl[h]);
      snprintf(fn, sizeof fn, "%s/hw/fwd_map_p%d.bin", dir, p);   writef(fn, fg[h]);
      snprintf(fn, sizeof fn, "%s/hw/expect_fwd_p%d.bin", dir, p); writef(fn, res);
    }
    // back
    for (int h = 0; h < 2; h++) {
      SQ<Tok> t0, tN;
      SQ<PTok> p0, pN;
      std::vector<float> sv(bs[h].size(), 0.0f);
      for (size_t i = 0; i < bs[h].size(); i++) {
        if (bsg[h][i] >= 0) sv[i] = s_hw[bsg[h][i]];
        t0.write(ev2tok(bs[h][i], 1, sv[i]));
      }
      chain(t0, p0, tN, pN, NULL);
      std::vector<float> acc;
      load_or_read(std::vector<float>(), &acc, K_READ);
      for (int pl = 0; pl < NPP; pl++) {
        int P = h * NPP + pl;
        if (P >= NPL) continue;
        for (int u = 0; u < NU; u++)
          for (int z = 0; z < NZ; z++) {
            int x = ax ? u : P, y = ax ? P : u;
            back_hw[((size_t)z * NPL + y) * NPL + x] += acc[((size_t)pl * NU + u) * NZ + z];
          }
      }
      int p = ax * 2 + h;
      snprintf(fn, sizeof fn, "%s/hw/back_p%d.bin", dir, p);       writef(fn, bs[h]);
      snprintf(fn, sizeof fn, "%s/hw/back_map_p%d.bin", dir, p);   writef(fn, bsg[h]);
      snprintf(fn, sizeof fn, "%s/hw/expect_acc_p%d.bin", dir, p); writef(fn, acc);
    }
  }
  // compare with the GPU parallelproj reference
  double es = 0, eb = 0, mb = 0;
  for (int i = 0; i < NE; i++) es = fmax(es, fabs(s_hw[i] / evg[i].mw - s_ref[i]) / s_ref[i]);
  for (size_t i = 0; i < back_hw.size(); i++) { mb = fmax(mb, fabs(back_ref[i])); eb = fmax(eb, fabs(back_hw[i] - back_ref[i])); }
  printf("vs GPU parallelproj: max rel err s %.3e, max abs err back / max back %.3e\n", es, eb / mb);
  printf("lane iterations per full forward + back (sum over 4 passes of the busiest lane): fwd %lld + back %lld = %lld\n", tot_fwd,
         tot_back, tot_fwd + tot_back);
  printf("efficiency = 2 * steps / lanes / iterations = %.3f\n", 2.0 * real_steps / LANES / (tot_fwd + tot_back));
  fprintf(meta, "total_fwd_iters %lld\ntotal_back_iters %lld\n", tot_fwd, tot_back);
  fclose(meta);
  std::vector<float> sv(s_hw.begin(), s_hw.end()), bv(back_hw.begin(), back_hw.end());
  snprintf(fn, sizeof fn, "%s/hw/expect_s_global.bin", dir);   writef(fn, sv);
  snprintf(fn, sizeof fn, "%s/hw/expect_back.bin", dir);       writef(fn, bv);
  bool ok = es < 1e-3 && eb / mb < 1e-3;
  printf(ok ? "PASSED\n" : "FAILED\n");
  return ok ? 0 : 1;
}
#endif
