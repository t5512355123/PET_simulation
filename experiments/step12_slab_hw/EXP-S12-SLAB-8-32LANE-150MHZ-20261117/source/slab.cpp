// Slab-partitioned list-mode projector (EXP-S12), v3 (local step range precomputed one lane ahead).
// The image is split along the main axis of each ray (x for x-major events, y for y-major events) into LANES slabs.
// Lane k keeps only slab k (both axis copies) and walks only the Joseph steps of each event that fall in slab k.
//   chain 1 (Tok):  src -> lane 0 -> lane 1 -> ... -> lane N-1 -> sink    (every token passes every lane)
//   chain 2 (PTok): src -> padd 0 -> padd 1 -> ... -> padd N-1 -> sink    (forward partial sums, one per FWD event)
//   lane = exp (token -> one work item per iteration) + eng (memory, forwarding); eng k -> padd k: local forward sum
// Each block is one HLS component; Platform Designer instantiates the lane blocks N times (HLS time does not grow with N).
// Back projection: predicated read-modify-write; the host orders events so that no voxel is touched twice within HAZ
// lane iterations (NOP tokens add bubbles in one lane only).
#ifndef SWSIM
#include "HLS/hls.h"
#endif
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vector>
#include <deque>

#ifndef NX
#define NX 128            // = NY (planes along the main axis)
#endif
#define NU NX
#ifndef NZ
#define NZ 32
#endif
#ifndef LANES
#define LANES 8
#endif
#define SP (NX / LANES)   // planes per slab
#define HU (NU / 2)
#define HZ (NZ / 2)
#define SLABSZ (2 * SP * HU * HZ)   // entries per bank (2 axis copies)
#define FRAC 16
#ifndef TOKBUF
#define TOKBUF 256        // token FIFO in front of each lane (lets a lane run ahead of the next one)
#endif
#ifndef MAXEV
#define MAXEV 16384
#endif
#ifndef IOCHUNK
#define IOCHUNK 16384
#endif
#define LZ 5              // log2 NZ
#define LU 7              // log2 NU
#define LX 7              // log2 NX

enum { K_FWD = 0, K_BACK = 1, K_LOAD = 2, K_READ = 3, K_SETID = 4, K_NOP = 5 };

struct Ev {               // 32 B, host memory format (i0 == -1000: NOP for lane u0, n_axis = bubbles)
  short i0;
  short n_axis;           // bit 15: axis, bits 0..14: steps
  int u0, v0, du, dv;
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
struct PTok { float F, mw, y, a; int idx; };   // 20 B, chain 2
// work item exp -> eng (one per lane iteration)
#define F_TOK 1      // forward the token t downstream
#define F_LD 2       // token: LOAD into my slab
#define F_RD 4       // token: READ (and clear) from my slab
#define F_SF 8       // forward-projection step
#define F_SB 16      // back-projection step
#define F_LAST 32    // last local step of a FWD event: emit the local sum
#define F_EMIT0 64   // FWD event that misses my slab: emit 0
struct Item {
  Tok t;             // the token (token items) or the current event (step items: s, axis)
  int u, v;          // step: fixed-point (u, z); token: voxel (u, z)
  short pl;          // plane inside my slab
  unsigned char fl;
  unsigned char pad;
};

// local step range of token t in the lane whose slab starts at plane lo and whose id is id
static inline void annot(Tok &t, int lo, int id) {
  int n = t.n_axis & 0x7fff;
  int ks = lo - t.i0, ke = lo + SP - t.i0;
  ks = ks < 0 ? 0 : ks;
  ke = ke > n ? n : ke;
  bool isev = t.kind == K_FWD || t.kind == K_BACK;
  bool isnop = t.kind == K_NOP && t.u0 == id;
  if (isnop) { ks = 0; ke = n; }
  bool has = (isev || isnop) && ke > ks;
  t.ks = (short)(has ? ks : 0);
  t.rem = (short)(has ? ke - ks : 0);
}
// ---------------------------------------------------------------- exp: one item per iteration (state c, k, rem, id)
#define EXP_BODY                                                                                             \
  {                                                                                                          \
    bool tokit = rem == 0;                                                                                   \
    Tok t;                                                                                                   \
    if (tokit) t = in.read(); else t = c;                                                                    \
    Item it;                                                                                                 \
    it.t = t;                                                                                                \
    it.pad = 0;                                                                                              \
    int kind = t.kind;                                                                                       \
    bool mine = t.i0 >= lo && t.i0 < lo + SP;                                                                \
    unsigned char f;                                                                                         \
    if (tokit) {                                                                                             \
      annot(it.t, lo + SP, id + 1);                                                                          \
      f = F_TOK;                                                                                             \
      if (kind == K_LOAD && mine) f |= F_LD;                                                                 \
      if (kind == K_READ && mine) f |= F_RD;                                                                 \
      if (kind == K_FWD && t.rem == 0) f |= F_EMIT0;                                                         \
      it.u = t.u0;                                                                                           \
      it.v = t.v0;                                                                                           \
      it.pl = (short)(mine ? t.i0 - lo : 0);                                                                 \
    } else {                                                                                                 \
      f = 0;                                                                                                 \
      if (c.kind == K_FWD) f |= F_SF;                                                                        \
      if (c.kind == K_BACK) f |= F_SB;                                                                       \
      if (c.kind == K_FWD && rem == 1) f |= F_LAST;                                                          \
      it.u = c.u0 + k * c.du;                                                                                \
      it.v = c.v0 + k * c.dv;                                                                                \
      it.pl = (short)((c.kind == K_NOP) ? 0 : c.i0 + k - lo);                                                \
    }                                                                                                        \
    it.fl = f;                                                                                               \
    wq.write(it);                                                                                            \
    if (tokit) {                                                                                             \
      if (kind == K_SETID) { id = t.u0; lo = t.u0 * SP; }                                                    \
      c = t;                                                                                                 \
      k = t.ks;                                                                                              \
      rem = t.rem;                                                                                           \
    } else {                                                                                                 \
      k = k + 1;                                                                                             \
      rem = rem - 1;                                                                                         \
    }                                                                                                        \
  }

// ---------------------------------------------------------------- eng: memory + forwarding (state F, rst)
#define ENG_BODY                                                                                             \
  {                                                                                                          \
    Item it = wq.read();                                                                                     \
    unsigned f = it.fl;                                                                                      \
    bool sf = f & F_SF, sb = f & F_SB, ld = f & F_LD, rd = f & F_RD;                                         \
    bool step = (f & F_TOK) == 0;                                                                            \
    int ax = (it.t.n_axis >> 15) & 1;                                                                        \
    int pl = it.pl;                                                                                          \
    int iu = it.u >> FRAC, iv = it.v >> FRAC;                                                                \
    float fu = (float)(it.u & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));                                     \
    float fv = (float)(it.v & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));                                     \
    int tu = it.u, tz = it.v;                                                                                \
    int tb = (tu & 1) | ((tz & 1) << 1);                                                                     \
    int ta = ((ax * SP + pl) * HU + ((tu >> 1) & (HU - 1))) * HZ + ((tz >> 1) & (HZ - 1));                   \
    int a[4];                                                                                                \
    float w[4];                                                                                              \
    bool okb[4];                                                                                             \
    _Pragma("unroll") for (int b = 0; b < 4; b++) {                                                          \
      int bu = b & 1, bz = b >> 1;                                                                           \
      int cu = ((iu & 1) == bu) ? iu : iu + 1;                                                               \
      float wu = (cu == iu) ? (1.0f - fu) : fu;                                                              \
      int cz = ((iv & 1) == bz) ? iv : iv + 1;                                                               \
      float wz = (cz == iv) ? (1.0f - fv) : fv;                                                              \
      bool o = (sf || sb) && cu >= 0 && cu < NU && cz >= 0 && cz < NZ;                                       \
      int cuc = o ? cu : bu, czc = o ? cz : bz;                                                              \
      int sa = ((ax * SP + pl) * HU + (cuc >> 1)) * HZ + (czc >> 1);                                         \
      a[b] = step ? sa : ta;                                                                                 \
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
  annot(t, 0, 0);
  return t;
}
static inline Tok vox_tok(int idx, int kind, float s) {   // idx = ((ax * NX + p) * NU + u) * NZ + z
  Tok t;
  t.v0 = idx & (NZ - 1);
  t.u0 = (idx >> LZ) & (NU - 1);
  t.i0 = (short)((idx >> (LZ + LU)) & (NX - 1));
  t.n_axis = (short)(((idx >> (LZ + LU + LX)) & 1) << 15);
  t.du = 0; t.dv = 0; t.s = s; t.kind = kind;
  t.ks = 0; t.rem = 0;
  return t;
}
static inline PTok ev2ptok(const Ev &e, int idx) {
  PTok q;
  q.F = 0.0f; q.mw = e.mw; q.y = e.y; q.a = e.a; q.idx = idx;
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
  int k = 0, rem = 0, id = 0, lo = 0;
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

hls_always_run_component component void padd(ihc::stream_in<PTok, ihc::buffer<TOKBUF>> &pin, ihc::stream_in<float, ihc::buffer<1024>> &fl,
                                              ihc::stream_out<PTok> &pout) {
  PTok p = pin.read();
  float f = fl.read();
  p.F += f;
  pout.write(p);
}

// source. mode 0: LOAD io[0..cnt) -> voxels off..; 3: READ voxels off..off+cnt; 4: SETID
//         mode 5: forward pass (tokens + PTok); 6: back pass (s from s_in); 1: rep x (forward, back)
hls_avalon_slave_component component void slab_src(
    hls_avalon_slave_memory_argument(MAXEV * sizeof(Ev)) Ev *ev,
    hls_avalon_slave_memory_argument(MAXEV * sizeof(float)) float *s_in,
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    ihc::stream_out<Tok> &tout, ihc::stream_out<PTok> &pout,
    hls_avalon_slave_register_argument int mode, hls_avalon_slave_register_argument int nev,
    hls_avalon_slave_register_argument int off, hls_avalon_slave_register_argument int cnt,
    hls_avalon_slave_register_argument int rep) {
  if (mode == 4) {
    Tok t = vox_tok(0, K_SETID, 0.0f);
    t.u0 = 0;
    tout.write(t);
    return;
  }
  if (mode == 0 || mode == 3) {
    for (int i = 0; i < cnt; i++) {
      float v = io[i];
      tout.write(vox_tok(off + i, mode == 0 ? K_LOAD : K_READ, mode == 0 ? v : 0.0f));
    }
    return;
  }
  int np = (mode == 1) ? 2 * rep : 1;
  for (int r = 0; r < np; r++) {
    int ph = (mode == 1) ? (r & 1) : (mode == 6 ? 1 : 0);
    for (int i = 0; i < nev; i++) {
      Ev e = ev[i];
      float s = s_in[i];
      tout.write(ev2tok(e, ph, s));
      if (ph == 0 && e.i0 != -1000) pout.write(ev2ptok(e, i));
    }
  }
}

// sink: consume nm chain-1 tokens (token s -> io, ring) and nq chain-2 sums (ratio -> s_out[idx])
hls_avalon_slave_component component void slab_sink(
    hls_avalon_slave_memory_argument(MAXEV * sizeof(float)) float *s_out,
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    ihc::stream_in<Tok> &tin, ihc::stream_in<PTok> &pin,
    hls_avalon_slave_register_argument int nm, hls_avalon_slave_register_argument int nq) {
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
      if (ok) { s_out[p.idx & (MAXEV - 1)] = ratio(p); qi++; }
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
  int k, rem, id, lo;
  float F;
  bool rst;
  long long iters;
};
static void lane_run(LaneMem &M, SQ<Tok> &in, SQ<Tok> &out, SQ<float> &fl) {
  SQ<Item> wq;
  {
    Tok &c = M.c;
    int &k = M.k, &rem = M.rem, &id = M.id, &lo = M.lo;
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
// run one source transaction through the chain; returns tokens at the end of chain 1 / chain 2
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

// ---------------- geometry shared by scheduler and reference
static inline int key(int ax, int p, int u, int z) { return ((ax * NX + p) * NU + u) * NZ + z; }
static int hw_vox(int ax, int u, int v, int p, int keys[4]) {   // voxels touched by one step (same rule as the lane)
  int iu = u >> FRAC, iv = v >> FRAC, n = 0;
  for (int b = 0; b < 4; b++) {
    int bu = b & 1, bz = b >> 1;
    int cu = ((iu & 1) == bu) ? iu : iu + 1;
    int cz = ((iv & 1) == bz) ? iv : iv + 1;
    if (cu >= 0 && cu < NU && cz >= 0 && cz < NZ) keys[n++] = key(ax, p, cu, cz);
  }
  return n;
}
static void ref_step(int axis, int p, double u, double v, int vox[4], double w[4], int &nv) {   // vox = (x*NY+y)*NZ+z
  int iu = (int)floor(u), iv = (int)floor(v);
  double fu = u - iu, fv = v - iv;
  nv = 0;
  for (int du = 0; du < 2; du++)
    for (int dz = 0; dz < 2; dz++) {
      int cu = iu + du, cz = iv + dz;
      int x = axis ? cu : p, y = axis ? p : cu;
      if (x < 0 || x >= NX || y < 0 || y >= NX || cz < 0 || cz >= NZ) continue;
      vox[nv] = (x * NX + y) * NZ + cz;
      w[nv] = (du ? fu : 1 - fu) * (dz ? fv : 1 - fv);
      nv++;
    }
}
static unsigned long long rs = 88172645463325252ULL;
static double urand() { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return (rs >> 11) * (1.0 / 9007199254740992.0); }
static int poisson(double l) { double L = exp(-l), p = 1; int k = 0; do { k++; p *= urand(); } while (p > L); return k - 1; }
static bool make_event(double ph, double s, double z1, double z2, double R, Ev &e) {
  double cx = (NX - 1) / 2.0, cy = (NX - 1) / 2.0;
  double h = sqrt(R * R - s * s);
  double x1 = cx + s * cos(ph) - h * sin(ph), y1 = cy + s * sin(ph) + h * cos(ph);
  double x2 = cx + s * cos(ph) + h * sin(ph), y2 = cy + s * sin(ph) - h * cos(ph);
  double dx = x2 - x1, dy = y2 - y1, dz = z2 - z1;
  int axis = fabs(dy) > fabs(dx) ? 1 : 0;
  double dd = axis ? dy : dx;
  if (dd < 0) { double t; t = x1; x1 = x2; x2 = t; t = y1; y1 = y2; y2 = t; t = z1; z1 = z2; z2 = t; dx = -dx; dy = -dy; dz = -dz; dd = -dd; }
  double du = (axis ? dx : dy) / dd, dv = dz / dd;
  double d0 = axis ? y1 : x1, u1 = axis ? x1 : y1;
  int i0 = (int)ceil(d0), i1 = (int)floor(d0 + dd);
  if (i0 < 0) i0 = 0;
  if (i1 > NX - 1) i1 = NX - 1;
  int a = -1, b = -1;
  for (int p = i0; p <= i1; p++) {
    double u = u1 + (p - d0) * du, v = z1 + (p - d0) * dv;
    if (u > -1 && u < NU && v > -1 && v < NZ) { if (a < 0) a = p; b = p; }
  }
  if (a < 0) return false;
  double u0 = u1 + (a - d0) * du, v0 = z1 + (a - d0) * dv;
  e.i0 = (short)a;
  e.n_axis = (short)((b - a + 1) | (axis << 15));
  e.u0 = (int)lround(u0 * 65536.0);
  e.v0 = (int)lround(v0 * 65536.0);
  e.du = (int)lround(du * 65536.0);
  e.dv = (int)lround(dv * 65536.0);
  e.mw = (float)sqrt(1 + du * du + dv * dv);
  return true;
}

// order events so that, in every lane, no voxel is written twice within HAZ lane iterations
static std::vector<Ev> schedule(const std::vector<Ev> &in, int HAZ, long long tl[LANES], long long &nops, long long &bub) {
  const int WIN = 64;
  std::vector<Ev> out;
  std::vector<long long> last((size_t)2 * NX * NU * NZ, -(1LL << 40));
  std::vector<int> pend;
  size_t next = 0;
  for (int L = 0; L < LANES; L++) tl[L] = 0;
  nops = bub = 0;
  int kv[4];
  auto need = [&](const Ev &e, long long nd[LANES]) {
    int ax = (e.n_axis >> 15) & 1, n = e.n_axis & 0x7fff;
    long long tot = 0;
    for (int L = 0; L < LANES; L++) {
      nd[L] = 0;
      int lo = L * SP, ks = lo - e.i0, ke = lo + SP - e.i0;
      if (ks < 0) ks = 0;
      if (ke > n) ke = n;
      for (int k = ks; k < ke; k++) {
        long long t = tl[L] + 1 + (k - ks);
        int nv = hw_vox(ax, e.u0 + k * e.du, e.v0 + k * e.dv, e.i0 + k, kv);
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
          for (int M = 0; M < LANES; M++) tl[M] += 1;
          tl[L] += bn[L];
          nops++;
          bub += bn[L];
        }
      bs = need(e, bn);
    }
    int ax = (e.n_axis >> 15) & 1, n = e.n_axis & 0x7fff;
    for (int L = 0; L < LANES; L++) {
      int lo = L * SP, ks = lo - e.i0, ke = lo + SP - e.i0;
      if (ks < 0) ks = 0;
      if (ke > n) ke = n;
      tl[L] += 1;
      for (int k = ks; k < ke; k++) {
        int nv = hw_vox(ax, e.u0 + k * e.du, e.v0 + k * e.dv, e.i0 + k, kv);
        for (int j = 0; j < nv; j++) last[kv[j]] = tl[L] + (k - ks);
      }
      if (ke > ks) tl[L] += ke - ks;
    }
    out.push_back(e);
    pend.erase(pend.begin() + best);
  }
  return out;
}

int main(int argc, char **argv) {
  int NEVR = argc > 1 ? atoi(argv[1]) : 8000;
  int HAZ = argc > 2 ? atoi(argv[2]) : 64;
  const int NV = NX * NX * NZ, NFLAT = 2 * NV;
  std::vector<double> phantom(NV), back_ref(NV, 0.0);
  std::vector<float> img(NFLAT), acc(NFLAT);
  double cx = (NX - 1) / 2.0, cz = (NZ - 1) / 2.0;
  for (int x = 0; x < NX; x++)
    for (int y = 0; y < NX; y++)
      for (int z = 0; z < NZ; z++) {
        double r = hypot(x - cx, y - cx), val = r < 0.42 * NX ? 1.0 : 0.0;
        if (hypot(x - cx - 16, y - cx) < 8 && fabs(z - cz) < 4) val = 4.0;
        phantom[(x * NX + y) * NZ + z] = val;
        img[key(0, x, y, z)] = (float)val;   // axis 0 copy: p = x, u = y
        img[key(1, y, x, z)] = (float)val;   // axis 1 copy: p = y, u = x
      }
  std::vector<Ev> raw;
  double R = 0.75 * NX;
  int tries = 0;
  while ((int)raw.size() < NEVR && tries < 50 * NEVR) {
    tries++;
    Ev e;
    double ph = urand() * M_PI, s = (urand() - 0.5) * 0.9 * NX;
    double zc = urand() * (NZ - 1), dzr = (urand() - 0.5) * 0.4 * NZ;
    if (!make_event(ph, s, zc - dzr / 2, zc + dzr / 2, R, e)) continue;
    int axis = (e.n_axis >> 15) & 1, n = e.n_axis & 0x7fff;
    double F = 0, w[4];
    int vx[4], nv;
    for (int k = 0; k < n; k++) {
      ref_step(axis, e.i0 + k, (e.u0 + (double)k * e.du) / 65536.0, (e.v0 + (double)k * e.dv) / 65536.0, vx, w, nv);
      for (int j = 0; j < nv; j++) F += w[j] * phantom[vx[j]];
    }
    e.a = 0.2f;
    int yv = poisson(0.05 * (e.mw * F + e.a));
    if (yv <= 0) continue;
    e.y = (float)yv;
    raw.push_back(e);
  }
  long long tl[LANES], nops, bub, real_steps = 0;
  std::vector<Ev> sch = schedule(raw, HAZ, tl, nops, bub);
  for (auto &e : raw) real_steps += e.n_axis & 0x7fff;
  int ne = (int)sch.size(), nf = (int)raw.size();
  if (ne > MAXEV) { printf("too many tokens %d\n", ne); return 1; }
  long long mx = 0, sum = 0;
  for (int L = 0; L < LANES; L++) { mx = tl[L] > mx ? tl[L] : mx; sum += tl[L]; }
  printf("lanes %d SP %d HAZ %d: events %d, tokens %d (NOP %lld, bubbles %lld), real steps %lld (%.1f/event)\n", LANES, SP,
         HAZ, nf, ne, nops, bub, real_steps, (double)real_steps / nf);
  printf("lane iterations per pass: max %lld, mean %.0f -> efficiency (steps / lanes / max) %.3f, balance %.3f\n", mx,
         (double)sum / LANES, (double)real_steps / LANES / mx, (double)sum / LANES / mx);

  // ---- run the software model of the hardware chain
  for (int L = 0; L < LANES; L++) { LM[L] = (LaneMem *)calloc(1, sizeof(LaneMem)); LM[L]->rst = true; LM[L]->c.kind = K_NOP; }
  SQ<Tok> t0, tN;
  SQ<PTok> p0, pN;
  t0.write(vox_tok(0, K_SETID, 0.0f));
  chain(t0, p0, tN, pN, NULL);
  for (int i = 0; i < NFLAT; i++) t0.write(vox_tok(i, K_LOAD, img[i]));
  chain(t0, p0, tN, pN, NULL);
  std::vector<float> s_out(ne, 0.0f);
  long long it[LANES];
  for (int i = 0; i < ne; i++) {
    t0.write(ev2tok(sch[i], 0, 0.0f));
    if (sch[i].i0 != -1000) p0.write(ev2ptok(sch[i], i));
  }
  chain(t0, p0, tN, pN, it);
  while (!pN.empty()) { PTok r = pN.read(); s_out[r.idx] = ratio(r); }
  for (int L = 0; L < LANES; L++)
    if (it[L] != tl[L]) { printf("lane %d: model iterations %lld != scheduler %lld\n", L, it[L], tl[L]); return 1; }
  for (int i = 0; i < ne; i++) t0.write(ev2tok(sch[i], 1, s_out[i]));
  chain(t0, p0, tN, pN, NULL);
  for (int i = 0; i < NFLAT; i++) t0.write(vox_tok(i, K_READ, 0.0f));
  chain(t0, p0, tN, pN, NULL);
  for (int i = 0; i < NFLAT; i++) acc[i] = tN.read().s;

  // ---- double reference
  double max_s_err = 0;
  for (int i = 0; i < ne; i++) {
    Ev &e = sch[i];
    if (e.i0 == -1000) continue;
    int axis = (e.n_axis >> 15) & 1, n = e.n_axis & 0x7fff;
    double F = 0, w[4];
    int vx[4], nv;
    for (int k = 0; k < n; k++) {
      ref_step(axis, e.i0 + k, (e.u0 + (double)k * e.du) / 65536.0, (e.v0 + (double)k * e.dv) / 65536.0, vx, w, nv);
      for (int j = 0; j < nv; j++) F += w[j] * phantom[vx[j]];
    }
    double s = e.mw * e.y / (e.mw * F + e.a);
    max_s_err = fmax(max_s_err, fabs(s - s_out[i]) / s);
    for (int k = 0; k < n; k++) {
      ref_step(axis, e.i0 + k, (e.u0 + (double)k * e.du) / 65536.0, (e.v0 + (double)k * e.dv) / 65536.0, vx, w, nv);
      for (int j = 0; j < nv; j++) back_ref[vx[j]] += s * w[j];
    }
  }
  double max_b = 0, max_b_err = 0;
  for (int x = 0; x < NX; x++)
    for (int y = 0; y < NX; y++)
      for (int z = 0; z < NZ; z++) {
        double rf = back_ref[(x * NX + y) * NZ + z];
        double hw = (double)acc[key(0, x, y, z)] + acc[key(1, y, x, z)];
        max_b = fmax(max_b, fabs(rf));
        max_b_err = fmax(max_b_err, fabs(hw - rf));
      }
  printf("max rel err forward ratio s: %.3e\nmax abs err back / max back: %.3e\n", max_s_err, max_b_err / max_b);
  if (getenv("DUMP")) {
    FILE *f;
    f = fopen("ev.bin", "wb"); fwrite(sch.data(), sizeof(Ev), ne, f); fclose(f);
    f = fopen("img.bin", "wb"); fwrite(img.data(), sizeof(float), NFLAT, f); fclose(f);
    f = fopen("expect_s.bin", "wb"); fwrite(s_out.data(), sizeof(float), ne, f); fclose(f);
    f = fopen("expect_acc.bin", "wb"); fwrite(acc.data(), sizeof(float), NFLAT, f); fclose(f);
    f = fopen("meta.txt", "w");
    fprintf(f, "nev %d\nnf %d\nvoxels %d\nreal_steps %lld\nlanes %d\nmax_lane_iters %lld\nhaz %d\nnops %lld\nbubbles %lld\n", ne, nf,
            NFLAT, real_steps, LANES, mx, HAZ, nops, bub);
    fclose(f);
    printf("dumped\n");
  }
  bool ok = max_s_err < 1e-4 && max_b_err / max_b < 1e-4;
  printf(ok ? "PASSED\n" : "FAILED\n");
  return ok ? 0 : 1;
}
#endif
